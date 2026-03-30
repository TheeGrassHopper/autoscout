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
from messaging.drafter import MessageDrafter
from messaging.sender import MessageSender
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

    # ── Step 1: Scrape listings ───────────────────────────────────────────────
    logger.info("STEP 1 — Scraping listings")

    all_raw = []
    seen_ids: set[str] = set()

    # Craigslist
    if SOURCES.get("craigslist"):
        scraper = CraigslistScraper(
            city=LOCATION["city"],
            config={**effective_filters, "search_radius_miles": effective_radius, "zip_code": effective_zip},
            vehicle_types=VEHICLE_TYPES,
        )
        cl_listings = await asyncio.to_thread(scraper.scrape, query)
        for l in cl_listings:
            if l.listing_id not in seen_ids:
                seen_ids.add(l.listing_id)
                all_raw.append(l)
        logger.info(f"Craigslist: {len(cl_listings)} listings after filtering")

    # Facebook Marketplace (requires APIFY_API_TOKEN + FB_COOKIES)
    fb_env_enabled = os.getenv("FB_SCRAPER_ENABLED", "").lower()
    fb_active = SOURCES.get("facebook_marketplace") and fb_env_enabled != "false" and include_facebook
    if not fb_active:
        if not include_facebook:
            logger.info("FB Marketplace scrape skipped (disabled by caller)")
        elif fb_env_enabled == "false":
            logger.info("FB Marketplace scrape skipped (FB_SCRAPER_ENABLED=false)")
    if fb_active:
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
        fb_listings = await asyncio.to_thread(
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
        all_raw.extend(fb_listings)
        logger.info(f"Facebook Marketplace: {len(fb_listings)} new listings")

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
        logger.info("STEP 1.5 — AI normalizing listings (Claude)")
        from utils.normalizer import normalize_batch
        all_raw = normalize_batch(all_raw, api_key=anthropic_key)
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

    # ── Step 2: Price lookups ─────────────────────────────────────────────────
    logger.info("STEP 2 — Fetching market values (Carvana + Local Market + KBB)")

    use_carvana = PRICING_SOURCES.get("carvana", False)
    use_carmax = PRICING_SOURCES.get("carmax", False)
    use_vinaudit  = PRICING_SOURCES.get("vinaudit", False)  and bool(os.getenv("VINAUDIT_API_KEY"))
    use_kbb_apify = PRICING_SOURCES.get("kbb_apify", False) and bool(os.getenv("APIFY_API_TOKEN"))
    use_carsxe    = PRICING_SOURCES.get("carsxe", False)    and bool(os.getenv("CARSXE_API_KEY"))
    logger.info(
        "Pricing chain: "
        + ("VinAudit → " if use_vinaudit else "")
        + ("KBB/Apify → " if use_kbb_apify else "")
        + ("CarsXE → " if use_carsxe else "")
        + "depreciation model (fallback)"
    )

    # ── Step 3: Score listings ────────────────────────────────────────────────
    logger.info("STEP 3 — Scoring listings (parallel price lookups)")

    scorer = DealScorer(config={**SCORING, **MESSAGING})
    db = Database(db_path=OUTPUT["db_path"])

    def _fetch_prices(raw):
        """
        D: Fetch all price sources for one listing in parallel threads.
        Returns (price_est, carvana_price, carmax_price, local_mkt_price).
        """
        mileage = raw.mileage or 50000
        has_vehicle = raw.make and raw.model and raw.year

        price_est = None

        # Launch VinAudit + KBB/Apify + CarsXE + Carvana + CarMax concurrently
        futures = {}
        with ThreadPoolExecutor(max_workers=5) as p:
            if use_vinaudit and raw.vin and raw.make and raw.model:
                futures["vinaudit"] = p.submit(
                    get_vinaudit_price, vin=raw.vin, mileage=mileage,
                    make=raw.make, model=raw.model, year=raw.year or 0,
                )
            if use_kbb_apify and has_vehicle:
                futures["kbb_apify"] = p.submit(
                    get_kbb_apify_price, make=raw.make, model=raw.model,
                    year=raw.year, mileage=mileage,
                )
            if use_carsxe and has_vehicle:
                futures["carsxe"] = p.submit(
                    get_carsxe_price, make=raw.make, model=raw.model,
                    year=raw.year, mileage=mileage, vin=raw.vin or "",
                )
            if use_carvana and has_vehicle:
                futures["carvana"] = p.submit(
                    get_carvana_price, make=raw.make, model=raw.model,
                    year=raw.year, mileage=mileage,
                )
            if use_carmax and has_vehicle:
                futures["carmax"] = p.submit(
                    get_carmax_price, make=raw.make, model=raw.model,
                    year=raw.year, mileage=mileage,
                )

        # Collect results
        va_result      = futures["vinaudit"].result()  if "vinaudit"  in futures else None
        kbb_result     = futures["kbb_apify"].result() if "kbb_apify" in futures else None
        cx_result      = futures["carsxe"].result()    if "carsxe"    in futures else None
        carvana_result = futures["carvana"].result()   if "carvana"   in futures else None
        carmax_result  = futures["carmax"].result()    if "carmax"    in futures else None

        carvana_price = carvana_kbb = carmax_price = None
        if carvana_result:
            carvana_price, carvana_kbb = carvana_result

        # Priority: VinAudit (VIN, high) > KBB/Apify (real KBB, high) > CarsXE (medium)
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

        if carmax_result:
            carmax_price = carmax_result

        local_mkt_price = None
        if raw.make and raw.model:
            local_mkt_price = comps_engine.get_market_price(
                raw.make, raw.model, raw.year, raw.mileage
            )

        return price_est, carvana_price, carmax_price, local_mkt_price

    scored_listings = []
    # D: fetch prices for all listings in parallel (8 listings at a time)
    _PRICE_WORKERS = 8
    price_results: dict = {}

    logger.info(f"  Fetching prices for {len(all_raw)} listings ({_PRICE_WORKERS} parallel workers)…")
    with ThreadPoolExecutor(max_workers=_PRICE_WORKERS) as pool:
        future_map = {pool.submit(_fetch_prices, raw): raw for raw in all_raw}
        for future in as_completed(future_map):
            raw = future_map[future]
            try:
                price_results[raw.listing_id] = future.result()
            except Exception as e:
                logger.warning(f"  Price fetch failed for {raw.title[:40]}: {e}")
                price_results[raw.listing_id] = (None, None, None, None)

    if stop_check and stop_check():
        logger.info("Stop requested after pricing — halting pipeline")
        return []

    for i, raw in enumerate(all_raw, 1):
        logger.info(f"  [{i}/{len(all_raw)}] {raw.title[:50]}")
        price_est, carvana_price, carmax_price, local_mkt_price = price_results.get(
            raw.listing_id, (None, None, None, None)
        )

        # Score (blends all available price sources)
        scored = scorer.score(
            raw, price_est,
            carvana_price=carvana_price,
            carmax_price=carmax_price,
            local_market_price=local_mkt_price,
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
        logger.info("Stop requested before messaging — halting pipeline")
        return scored_listings

    # ── Step 4: Draft messages ────────────────────────────────────────────────
    logger.info("STEP 4 — Drafting messages for deals")

    drafter = MessageDrafter(use_claude=bool(anthropic_key))

    great_deals = [l for l in scored_listings if l.is_great_deal]
    fair_deals = [l for l in scored_listings if l.is_fair_deal]
    actionable = great_deals + fair_deals

    for listing in actionable:
        listing.message_draft = drafter.draft(listing)
        db.log_message(listing.listing_id, listing.message_draft)

    logger.info(f"Messages drafted: {len(actionable)}")

    # ── Step 5: Queue/send messages ───────────────────────────────────────────
    if not dry_run:
        logger.info("STEP 5 — Processing messages")

        sender = MessageSender(
            db=db,
            auto_send=MESSAGING.get("auto_send_great_deals", False),
            output_dir="output",
        )
        notifier = Notifier()

        for listing in great_deals:
            sender.process(listing)
            if NOTIFICATIONS.get("sms_on_great_deal"):
                notifier.alert_great_deal(listing)

        if MESSAGING.get("require_approval_fair_deals"):
            for listing in fair_deals[:5]:  # Cap at 5 fair deals for review
                sender.process(listing)
    else:
        logger.info("STEP 5 — Dry run: skipping message sending")

    # ── Step 6: Export CSV ────────────────────────────────────────────────────
    logger.info("STEP 6 — Exporting results")
    export_csv(scored_listings)

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = time.time() - start
    print_summary(scored_listings)

    stats = db.stats()
    logger.info(
        f"Pipeline complete in {elapsed:.1f}s — "
        f"{stats['great_deals']} great / {stats['fair_deals']} fair deals in DB"
    )

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
    p.add_argument("--query", default="", help="Vehicle search query (e.g. 'tacoma')")
    p.add_argument("--dry-run", action="store_true", help="Score deals but don't queue messages")
    p.add_argument("--schedule", action="store_true", help="Run on a schedule (uses config frequency)")
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
        asyncio.run(run_pipeline(query=args.query, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
