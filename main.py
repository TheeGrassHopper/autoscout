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
import csv
import logging
import os
import sys
import time
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
from pricing.kbb import KBBPricer
from pricing.carvana import get_carvana_price
from pricing.carmax import get_carmax_price
from scoring.engine import DealScorer, ScoredListing, sort_listings, print_summary
from messaging.drafter import MessageDrafter
from messaging.sender import MessageSender
from utils.db import Database
from utils.notifier import Notifier


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_pipeline(query: str = "", dry_run: bool = False, zip_code: str = None,
                 radius_miles: int = None, stop_check=None) -> list[ScoredListing]:
    """
    Execute the full AutoScout pipeline.
    Returns a list of scored listings.
    """
    start = time.time()
    os.makedirs("output/.price_cache", exist_ok=True)

    logger.info("=" * 60)
    logger.info("AutoScout AI — Starting pipeline")
    # Runtime overrides from the UI
    effective_zip = zip_code or LOCATION.get("zip_code", "85001")
    effective_radius = radius_miles or LOCATION.get("search_radius_miles", 50)
    logger.info(f"Location: {LOCATION['city']} | zip {effective_zip} | {effective_radius}mi radius")
    logger.info(f"Filters: year {FILTERS['min_year']}–{FILTERS['max_year']}, "
                f"max ${FILTERS['max_price']:,}, max {FILTERS['max_mileage']:,}mi")
    logger.info("=" * 60)

    # ── Step 1: Scrape listings ───────────────────────────────────────────────
    logger.info("STEP 1 — Scraping listings")

    all_raw = []
    seen_ids: set[str] = set()

    # Craigslist
    if SOURCES.get("craigslist"):
        scraper = CraigslistScraper(
            city=LOCATION["city"],
            config={**FILTERS, "search_radius_miles": effective_radius, "zip_code": effective_zip},
            vehicle_types=VEHICLE_TYPES,
        )
        cl_listings = scraper.scrape(query=query)
        for l in cl_listings:
            if l.listing_id not in seen_ids:
                seen_ids.add(l.listing_id)
                all_raw.append(l)
        logger.info(f"Craigslist: {len(cl_listings)} listings after filtering")

    # Facebook Marketplace (requires APIFY_API_TOKEN + FB_COOKIES)
    fb_env_enabled = os.getenv("FB_SCRAPER_ENABLED", "").lower()
    fb_active = SOURCES.get("facebook_marketplace") and fb_env_enabled != "false"
    if not fb_active and fb_env_enabled == "false":
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
        fb_listings = scrape_facebook(
            location=LOCATION["city"],
            keywords=[k for k in keywords if k],
            min_price=FILTERS["min_price"],
            max_price=FILTERS["max_price"],
            max_mileage=FILTERS["max_mileage"],
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
    comps_engine.fetch_all_comps(unique_vehicles)

    # ── Step 2: Price lookups ─────────────────────────────────────────────────
    logger.info("STEP 2 — Fetching market values (Carvana + Local Market + KBB)")

    pricer = KBBPricer() if PRICING_SOURCES.get("kbb") else None
    use_carvana = PRICING_SOURCES.get("carvana", False)
    use_carmax = PRICING_SOURCES.get("carmax", False)

    # ── Step 3: Score listings ────────────────────────────────────────────────
    logger.info("STEP 3 — Scoring listings")

    scorer = DealScorer(config={**SCORING, **MESSAGING})
    db = Database(db_path=OUTPUT["db_path"])

    scored_listings = []
    for i, raw in enumerate(all_raw, 1):
        logger.info(f"  [{i}/{len(all_raw)}] {raw.title[:50]}")

        # KBB lookup
        price_est = None
        if pricer and raw.make and raw.model and raw.year:
            price_est = pricer.get_price(
                year=raw.year,
                make=raw.make,
                model=raw.model,
                mileage=raw.mileage or 50000,
                zip_code=LOCATION.get("zip_code", "85001"),
            )
        elif pricer:
            logger.debug(f"  Skipping KBB lookup (missing make/model/year for: {raw.title})")

        # Carvana lookup — returns (carvana_price, kbb_from_carvana)
        carvana_price = None
        carvana_kbb = None
        if use_carvana and raw.make and raw.model and raw.year:
            carvana_price, carvana_kbb = get_carvana_price(
                make=raw.make,
                model=raw.model,
                year=raw.year,
                mileage=raw.mileage or 50000,
            )
            if carvana_price:
                logger.debug(f"  Carvana: ${carvana_price:,}")
            if carvana_kbb:
                logger.debug(f"  Carvana KBB: ${carvana_kbb:,}")
            # Use Carvana's real KBB value if we don't have one (or it's an estimate)
            if carvana_kbb and (
                price_est is None or price_est.source == "kbb_estimate"
            ):
                from pricing.kbb import PriceEstimate
                price_est = PriceEstimate(
                    source="carvana_kbb",
                    make=raw.make, model=raw.model,
                    year=raw.year, mileage=raw.mileage or 50000,
                    fair_market_value=carvana_kbb,
                    confidence="high",
                )

        # CarMax lookup
        carmax_price = None
        if use_carmax and raw.make and raw.model and raw.year:
            carmax_price = get_carmax_price(
                make=raw.make,
                model=raw.model,
                year=raw.year,
                mileage=raw.mileage or 50000,
            )
            if carmax_price:
                logger.debug(f"  CarMax: ${carmax_price:,}")

        # Local market comp — year ±1, mileage ±10k, national CL + FB pool
        local_mkt_price = None
        if raw.make and raw.model:
            local_mkt_price = comps_engine.get_market_price(
                raw.make, raw.model, raw.year, raw.mileage
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

        sched.every(interval_hours).hours.do(
            run_pipeline, query=args.query, dry_run=args.dry_run
        )

        run_pipeline(query=args.query, dry_run=args.dry_run)

        while True:
            sched.run_pending()
            time.sleep(60)
    else:
        run_pipeline(query=args.query, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
