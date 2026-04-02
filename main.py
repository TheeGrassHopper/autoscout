#!/usr/bin/env python3
"""
main.py — AutoScout AI Pipeline Entry Point

Runs the full vehicle deal hunting pipeline:
  1. Scrape Craigslist + Facebook Marketplace for listings
  1.5 AI-normalize listings (make/model/year/mileage extraction via Claude)
  2. Look up market values: KBB + Carvana + CarMax
  3. Score each listing (0–100 deal score, blended across all price sources)
  4. Draft seller messages for good deals (Claude or template)
  5. Export results to CSV + SQLite
  6. Print a summary + queue messages for review

Usage:
    python main.py
    python main.py --dry-run          # Scrape + score, skip messaging
    python main.py --query "tacoma"   # Search a specific vehicle
    python main.py --schedule         # Run on a schedule
"""

import argparse
import asyncio
import csv
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

# ── Load environment variables ───────────────────────────────────────────────
load_dotenv()

# ── Logging setup ────────────────────────────────────────────────────────────
os.makedirs("output", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("output/autoscout.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("autoscout.main")

# ── Project imports ───────────────────────────────────────────────────────────
from config import (
    LOCATION, VEHICLE_TYPES, SEARCH_QUERIES, FILTERS,
    SCORING, SOURCES, PRICING_SOURCES, MESSAGING, NOTIFICATIONS, OUTPUT
)
from scrapers.craigslist import CraigslistScraper
from scrapers.facebook import scrape_facebook
from pricing.kbb import PriceEstimate as _PE  # noqa: used by _fetch_prices closure
from pricing.carvana import get_carvana_price
from pricing.carmax import get_carmax_price
from pricing.vinaudit import get_vinaudit_price
from pricing.kbb_apify import get_kbb_apify_price
from pricing.carsxe import get_carsxe_price
from scoring.engine import DealScorer, ScoredListing, sort_listings, print_summary
from utils.db import Database
from utils.notifier import Notifier


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def run_pipeline(query: str = "", dry_run: bool = False, zip_code: str = None,
                 radius_miles: int = None, stop_check=None,
                 include_facebook: bool = True,
                 min_year: int = None, max_year: int = None,
                 max_price: int = None, max_mileage: int = None) -> list[ScoredListing]:
    """
    Execute the full AutoScout pipeline.
    Returns a list of scored listings.
    """
    start = time.time()
    os.makedirs("output/.price_cache", exist_ok=True)

    # Merge config defaults with runtime overrides
    effective_zip = zip_code or LOCATION.get("zip_code", "85001")
    effective_radius = radius_miles or LOCATION.get("search_radius_miles", 50)
    effective_filters = {
        **FILTERS,
        "min_year":    min_year    or FILTERS["min_year"],
        "max_year":    max_year    or FILTERS["max_year"],
        "max_price":   max_price   or FILTERS["max_price"],
        "max_mileage": max_mileage or FILTERS["max_mileage"],
    }

    logger.info("=" * 60)
    logger.info("AutoScout AI — Starting pipeline")
    logger.info(f"Location: {LOCATION['city']} | zip {effective_zip} | {effective_radius}mi radius")
    logger.info(f"Filters: year {effective_filters['min_year']}–{effective_filters['max_year']}, "
                f"max ${effective_filters['max_price']:,}, max {effective_filters['max_mileage']:,}mi")
    logger.info("=" * 60)

    # ── Step 1: Scrape listings (CL + FB concurrently) ───────────────────────
    logger.info("STEP 1 — Scraping listings (Craigslist + Facebook in parallel)")

    seen_ids: set[str] = set()

    async def _scrape_cl():
        if not SOURCES.get("craigslist"):
            return []
        scraper = CraigslistScraper(
            city=LOCATION["city"],
            config={**effective_filters, "search_radius_miles": effective_radius, "zip_code": effective_zip},
            vehicle_types=VEHICLE_TYPES,
        )
        results = await asyncio.to_thread(scraper.scrape, query)
        logger.info(f"Craigslist: {len(results)} listings after filtering")
        return results

    async def _scrape_fb():
        fb_env_enabled = os.getenv("FB_SCRAPER_ENABLED", "").lower()
        fb_active = SOURCES.get("facebook_marketplace") and fb_env_enabled != "false" and include_facebook
        if not fb_active:
            if not include_facebook:
                logger.info("FB Marketplace scrape skipped (disabled by caller)")
            elif fb_env_enabled == "false":
                logger.info("FB Marketplace scrape skipped (FB_SCRAPER_ENABLED=false)")
            return []
        import json as _json
        apify_token = os.getenv("APIFY_API_TOKEN", "")
        fb_cookies_raw = os.getenv("FB_COOKIES", "")
        fb_cookies = None
        if fb_cookies_raw:
            try:
                fb_cookies = _json.loads(fb_cookies_raw)
            except Exception:
                logger.warning("FB_COOKIES in .env is not valid JSON — skipping FB scrape")
        keywords = [query] if query else (SEARCH_QUERIES or [""])
        results = await asyncio.to_thread(
            scrape_facebook,
            location=LOCATION["city"],
            keywords=[k for k in keywords if k],
            min_price=effective_filters["min_price"],
            max_price=effective_filters["max_price"],
            max_mileage=effective_filters["max_mileage"],
            radius_miles=effective_radius,
            apify_token=apify_token,
            seen_ids=seen_ids,
            fb_cookies=fb_cookies,
        )
        logger.info(f"Facebook Marketplace: {len(results)} new listings")
        return results

    cl_listings, fb_listings = await asyncio.gather(_scrape_cl(), _scrape_fb())

    all_raw = []
    for l in cl_listings:
        if l.listing_id not in seen_ids:
            seen_ids.add(l.listing_id)
            all_raw.append(l)
    # FB listings were already deduplicated inside scrape_facebook() via seen_ids,
    # so they won't be in seen_ids yet — but fb_ prefix guarantees no CL collision anyway.
    for l in fb_listings:
        all_raw.append(l)

    if not all_raw:
        logger.warning("No listings found. Check your filters or try a broader search.")
        return []

    if stop_check and stop_check():
        logger.info("Stop requested after scraping — halting pipeline")
        return []

    logger.info(f"Total raw listings: {len(all_raw)}")

    # ── Step 1.5: AI normalization (fills in missing make/model/year) ─────────
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        incomplete = [l for l in all_raw if not (l.make and l.model and l.year)]
        complete   = [l for l in all_raw if l.make and l.model and l.year]
        if incomplete:
            logger.info(
                f"STEP 1.5 — AI normalizing {len(incomplete)} incomplete listings "
                f"({len(complete)} already complete, skipped)"
            )
            from utils.normalizer import normalize_batch
            normalized = normalize_batch(incomplete, api_key=anthropic_key)
            all_raw = complete + normalized
        else:
            logger.info("STEP 1.5 — All listings already complete, skipping AI normalization")
    else:
        logger.info("STEP 1.5 — Skipping AI normalization (no ANTHROPIC_API_KEY)")

    # ── Step 1.75: Build market comps (national CL + FB from main run) ───────
    # Comps filtered per-listing to year ±1 and mileage ±10k miles.
    # National Craigslist (no city limit) + Facebook 500mi (already scraped).
    logger.info("STEP 1.75 — Building market comps (national CL + FB from main run)")
    from utils.comps import CompsEngine
    comps_engine = CompsEngine(all_raw)   # pre-load main-run listings as initial comps
    unique_vehicles = {
        (l.make, l.model)
        for l in all_raw
        if l.make and l.model
    }
    await asyncio.to_thread(comps_engine.fetch_all_comps, unique_vehicles)

    # ── Step 1.9: Skip already-scored listings (TICKET-006) ──────────────────
    db = Database(db_path=OUTPUT["db_path"])
    existing_prices = db.get_existing_listing_prices()

    new_listings   = []
    known_listings = []
    for raw in all_raw:
        stored_price = existing_prices.get(raw.listing_id)
        if stored_price is None:
            # Never seen before
            new_listings.append(raw)
        else:
            # Re-score if asking price dropped/changed by more than 5%
            current = raw.asking_price or 0
            if stored_price and current and abs(current - stored_price) / stored_price > 0.05:
                new_listings.append(raw)
                logger.debug(
                    f"  Re-scoring {raw.listing_id[:12]}… (price changed "
                    f"${stored_price:,} → ${current:,})"
                )
            else:
                known_listings.append(raw)

    logger.info(
        f"STEP 1.9 — Skip check: {len(new_listings)} new / "
        f"{len(known_listings)} already scored (skipping pricing)"
    )
    db.touch_last_seen([l.listing_id for l in known_listings])
    all_raw = new_listings

    if not all_raw:
        logger.info("No new listings to price — pipeline complete (all known).")
        return []

    # ── Step 2: Price lookups ─────────────────────────────────────────────────
    logger.info("STEP 2 — Fetching market values (Carvana + Local Market + KBB)")

    use_carvana = PRICING_SOURCES.get("carvana", False)
    use_carmax = PRICING_SOURCES.get("carmax", False)
    use_vinaudit  = PRICING_SOURCES.get("vinaudit", False)  and bool(os.getenv("VINAUDIT_API_KEY"))
    use_kbb_apify = PRICING_SOURCES.get("kbb_apify", False) and bool(os.getenv("APIFY_API_TOKEN"))
    use_carsxe    = PRICING_SOURCES.get("carsxe", False)    and bool(os.getenv("CARSXE_API_KEY"))
    active = [s for s, on in [
        ("VinAudit", use_vinaudit),
        ("KBB/Apify", use_kbb_apify),
        ("CarsXE", use_carsxe),
        ("Carvana comps", use_carvana),
        ("local market", True),
    ] if on]
    logger.info("Pricing chain: " + " → ".join(active) if active else "Pricing chain: no sources enabled")

    # ── Step 3: Score listings ────────────────────────────────────────────────
    logger.info("STEP 3 — Scoring listings (parallel price lookups)")

    scorer = DealScorer(config={**SCORING, **MESSAGING})

    def _fetch_prices(raw):
        """
        Fetch all price sources for one listing.
        Checks the pricing cache first per-source; only hits external APIs on miss.
        Returns (price_est, carvana_price, carmax_price, local_mkt_price).
        """
        mileage = raw.mileage or 50000
        has_vehicle = raw.make and raw.model and raw.year

        # ── Cache helpers ─────────────────────────────────────────────────────
        def _cached(source: str) -> Optional[tuple]:
            if not has_vehicle:
                return None
            return db.get_price_cache(raw.make, raw.model, raw.year, mileage, source)

        def _store(source: str, value, kbb_value=None):
            if has_vehicle:
                db.set_price_cache(raw.make, raw.model, raw.year, mileage, source,
                                   value, kbb_value)

        # ── Per-source cache checks ───────────────────────────────────────────
        cached_carvana = _cached("carvana")
        cached_carmax  = _cached("carmax")
        cached_kbb     = _cached("kbb_apify")
        cached_carsxe  = _cached("carsxe")

        # ── Launch only uncached sources in parallel ───────────────────────────
        futures = {}
        with ThreadPoolExecutor(max_workers=5) as p:
            if use_vinaudit and raw.vin and raw.make and raw.model:
                # VinAudit is VIN-specific — not worth caching by make/model/mileage
                futures["vinaudit"] = p.submit(
                    get_vinaudit_price, vin=raw.vin, mileage=mileage,
                    make=raw.make, model=raw.model, year=raw.year or 0,
                )
            if use_kbb_apify and has_vehicle and cached_kbb is None:
                futures["kbb_apify"] = p.submit(
                    get_kbb_apify_price, make=raw.make, model=raw.model,
                    year=raw.year, mileage=mileage,
                )
            if use_carsxe and has_vehicle and cached_carsxe is None:
                futures["carsxe"] = p.submit(
                    get_carsxe_price, make=raw.make, model=raw.model,
                    year=raw.year, mileage=mileage, vin=raw.vin or "",
                )
            if use_carvana and has_vehicle and cached_carvana is None:
                futures["carvana"] = p.submit(
                    get_carvana_price, make=raw.make, model=raw.model,
                    year=raw.year, mileage=mileage,
                )
            if use_carmax and has_vehicle and cached_carmax is None:
                futures["carmax"] = p.submit(
                    get_carmax_price, make=raw.make, model=raw.model,
                    year=raw.year, mileage=mileage,
                )

        # ── Collect + cache results ───────────────────────────────────────────
        va_result  = futures["vinaudit"].result()  if "vinaudit"  in futures else None
        kbb_result = futures["kbb_apify"].result() if "kbb_apify" in futures else None
        cx_result  = futures["carsxe"].result()    if "carsxe"    in futures else None

        carvana_result = futures["carvana"].result() if "carvana" in futures else None
        carmax_result  = futures["carmax"].result()  if "carmax"  in futures else None

        # Write fresh results to cache
        if kbb_result and kbb_result.fair_market_value:
            _store("kbb_apify", kbb_result.fair_market_value)
        if cx_result and cx_result.fair_market_value:
            _store("carsxe", cx_result.fair_market_value)
        if carvana_result:
            cv_price, cv_kbb = carvana_result
            _store("carvana", cv_price, cv_kbb)
        if carmax_result:
            _store("carmax", carmax_result)

        # ── Resolve carvana values (fresh or cached) ──────────────────────────
        carvana_price = carvana_kbb = None
        if carvana_result:
            carvana_price, carvana_kbb = carvana_result
        elif cached_carvana:
            carvana_price, carvana_kbb = cached_carvana
            if carvana_price:
                logger.debug(f"  [cache hit] Carvana ${carvana_price:,} — {raw.title[:40]}")

        carmax_price = None
        if carmax_result:
            carmax_price = carmax_result
        elif cached_carmax:
            carmax_price = cached_carmax[0]
            if carmax_price:
                logger.debug(f"  [cache hit] CarMax ${carmax_price:,} — {raw.title[:40]}")

        # Resolve KBB (fresh or cached)
        if kbb_result is None and cached_kbb:
            from pricing.kbb import PriceEstimate as PE
            kbb_result = PE(
                source="kbb_apify_cached", make=raw.make, model=raw.model,
                year=raw.year, mileage=mileage,
                fair_market_value=cached_kbb[0], confidence="high",
            )
            logger.debug(f"  [cache hit] KBB ${cached_kbb[0]:,} — {raw.title[:40]}")

        if cx_result is None and cached_carsxe:
            from pricing.kbb import PriceEstimate as PE
            cx_result = PE(
                source="carsxe_cached", make=raw.make, model=raw.model,
                year=raw.year, mileage=mileage,
                fair_market_value=cached_carsxe[0], confidence="medium",
            )

        # ── Priority: VinAudit > KBB/Apify > CarsXE > Carvana KBB ───────────
        price_est = None
        if va_result and va_result.fair_market_value:
            price_est = va_result
        elif kbb_result and kbb_result.fair_market_value:
            price_est = kbb_result
        elif cx_result and cx_result.fair_market_value:
            price_est = cx_result
        if carvana_kbb and price_est is None:
            from pricing.kbb import PriceEstimate as PE
            price_est = PE(
                source="carvana_kbb", make=raw.make, model=raw.model,
                year=raw.year, mileage=mileage,
                fair_market_value=carvana_kbb, confidence="high",
            )

        local_mkt_price = None
        local_mkt_urls: list = []
        if raw.make and raw.model:
            local_mkt_price, local_mkt_urls = comps_engine.get_market_price(
                raw.make, raw.model, raw.year, raw.mileage
            )

        return price_est, carvana_price, carmax_price, local_mkt_price, local_mkt_urls

    scored_listings = []
    # D: fetch prices for all listings in parallel (8 listings at a time)
    _PRICE_WORKERS = 8
    price_results: dict = {}

    logger.info(f"  Fetching prices for {len(all_raw)} new listings ({_PRICE_WORKERS} parallel workers)…")
    with ThreadPoolExecutor(max_workers=_PRICE_WORKERS) as pool:
        future_map = {pool.submit(_fetch_prices, raw): raw for raw in all_raw}
        for future in as_completed(future_map):
            raw = future_map[future]
            try:
                price_results[raw.listing_id] = future.result()
            except Exception as e:
                logger.warning(f"  Price fetch failed for {raw.title[:40]}: {e}")
                price_results[raw.listing_id] = (None, None, None, None, [])

    if stop_check and stop_check():
        logger.info("Stop requested after pricing — halting pipeline")
        return []

    for i, raw in enumerate(all_raw, 1):
        logger.info(f"  [{i}/{len(all_raw)}] {raw.title[:50]}")
        price_est, carvana_price, carmax_price, local_mkt_price, local_mkt_urls = price_results.get(
            raw.listing_id, (None, None, None, None, [])
        )

        # Score (blends all available price sources)
        scored = scorer.score(
            raw, price_est,
            carvana_price=carvana_price,
            carmax_price=carmax_price,
            local_market_price=local_mkt_price,
            local_market_comp_urls=local_mkt_urls,
        )
        scored_listings.append(scored)
        db.upsert_listing(scored)
        if stop_check and stop_check():
            logger.info("Stop requested during scoring — halting pipeline")
            return sort_listings(scored_listings)

    # ── Step 3.5: Carvana cash offer enrichment (VIN listings only) ──────────
    if PRICING_SOURCES.get("carvana_offer_flow") and any(s.vin for s in scored_listings):
        candidates = [
            s for s in scored_listings
            if s.vin and s.deal_class in ("fair", "great")
        ]
        if candidates:
            logger.info(
                f"STEP 3.5 — Carvana offer flow for {len(candidates)} VIN listing(s)"
            )
            scored_listings = await _enrich_with_carvana_offers(
                scored_listings, candidates, scorer, db
            )

    # Sort: best deals first
    scored_listings = sort_listings(scored_listings)

    if stop_check and stop_check():
        logger.info("Stop requested — halting pipeline")
        return scored_listings

    # ── Step 4: Export CSV ────────────────────────────────────────────────────
    logger.info("STEP 4 — Exporting results")
    export_csv(scored_listings)

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = time.time() - start
    print_summary(scored_listings)

    stats = db.stats()
    logger.info(
        f"Pipeline complete in {elapsed:.1f}s — "
        f"{stats['great_deals']} great / {stats['fair_deals']} fair deals in DB"
    )

    # Purge expired pricing cache rows (lightweight, run at end of each pipeline)
    db.purge_expired_price_cache()

    # Purge listings older than 7 days — keeps the DB rotating with fresh listings only
    db.purge_stale_listings(max_age_days=7)

    return scored_listings


async def _enrich_with_carvana_offers(
    all_listings: list,
    candidates: list,
    scorer,
    db,
    max_concurrent: int = 2,
) -> list:
    """
    Run the Carvana sell-my-car offer flow in parallel for candidate listings.
    Updates each listing's carvana_offer + deal_class in-place, re-saves to DB.
    max_concurrent: how many browser sessions to run at once (keep low to avoid blocks).
    """
    from utils.carvana_sell import run_carvana_offer

    semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_offer(scored):
        async with semaphore:
            try:
                result = await run_carvana_offer(
                    vin=scored.vin,
                    mileage=scored.mileage or 50000,
                    title=scored.title,
                    description=scored.description,
                )
                offer_str = result.get("offer")
                if offer_str:
                    # Parse "$X,XXX" → int
                    offer_int = int(offer_str.replace("$", "").replace(",", ""))
                    scorer.apply_carvana_offer(scored, offer_int)
                    db.upsert_listing(scored)
                else:
                    logger.debug(
                        f"[CarvanaOffer] No offer returned for {scored.vin} "
                        f"({result.get('status')}: {result.get('error')})"
                    )
            except Exception as e:
                logger.warning(f"[CarvanaOffer] Enrichment failed for {scored.vin}: {e}")

    await asyncio.gather(*[fetch_offer(s) for s in candidates])
    return all_listings


def export_csv(listings: list[ScoredListing]):
    """Write all scored listings to a CSV file."""
    if not listings:
        return

    path = OUTPUT.get("csv_path", "output/deals.csv")
    fieldnames = [
        "total_score", "deal_class", "title", "year", "make", "model",
        "asking_price", "kbb_value", "carvana_value", "carmax_value",
        "blended_market_value", "savings_vs_kbb", "savings_pct",
        "mileage", "transmission", "location", "source",
        "posted_date", "url", "suggested_offer", "message_draft",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for l in listings:
            row = l.to_dict()
            if row.get("savings_pct"):
                row["savings_pct"] = f"{row['savings_pct']:.1%}"
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    logger.info(f"Results exported to {path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="AutoScout AI — Vehicle Deal Hunter")
    p.add_argument("--query",        default="",  help="Vehicle search query (e.g. 'tacoma')")
    p.add_argument("--dry-run",      action="store_true", help="Score deals but don't queue messages")
    p.add_argument("--schedule",     action="store_true", help="Run on a schedule (uses config frequency)")
    p.add_argument("--zip-code",     default="",  help="Search center ZIP code")
    p.add_argument("--radius-miles", type=int, default=0, help="Search radius in miles")
    p.add_argument("--no-facebook",  action="store_true", help="Skip Facebook Marketplace scraping")
    p.add_argument("--min-year",     type=int, default=0, help="Minimum vehicle year")
    p.add_argument("--max-year",     type=int, default=0, help="Maximum vehicle year")
    p.add_argument("--max-price",    type=int, default=0, help="Maximum asking price")
    p.add_argument("--max-mileage",  type=int, default=0, help="Maximum mileage")
    return p.parse_args()


def main():
    args = parse_args()

    if args.schedule:
        import schedule as sched

        interval_hours = 1
        logger.info(f"Scheduled mode: running every {interval_hours} hour(s)")

        def _run():
            asyncio.run(run_pipeline(query=args.query, dry_run=args.dry_run))

        sched.every(interval_hours).hours.do(_run)
        _run()

        while True:
            sched.run_pending()
            time.sleep(60)
    else:
        asyncio.run(run_pipeline(
            query=args.query,
            dry_run=args.dry_run,
            zip_code=args.zip_code or None,
            radius_miles=args.radius_miles or None,
            include_facebook=not args.no_facebook,
            min_year=args.min_year or None,
            max_year=args.max_year or None,
            max_price=args.max_price or None,
            max_mileage=args.max_mileage or None,
        ))


if __name__ == "__main__":
    main()
