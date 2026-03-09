#!/usr/bin/env python3
"""
main.py — AutoScout AI Pipeline Entry Point

Runs the full vehicle deal hunting pipeline:
  1. Scrape Craigslist for listings matching your config
  2. Look up KBB market values for each listing
  3. Score each listing (0–100 deal score)
  4. Draft seller messages for good deals
  5. Export results to CSV + SQLite
  6. Print a summary + queue messages for review

Usage:
    python main.py
    python main.py --dry-run          # Scrape + score, skip messaging
    python main.py --query "tacoma"   # Search a specific vehicle
    python main.py --once             # Run once (vs. scheduled mode)
"""

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# ── Load environment variables ───────────────────────────────────────────────
load_dotenv()

# ── Logging setup ────────────────────────────────────────────────────────────
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
from pricing.kbb import KBBPricer
from scoring.engine import DealScorer, ScoredListing, sort_listings, print_summary
from messaging.drafter import MessageDrafter
from messaging.sender import MessageSender
from utils.db import Database
from utils.notifier import Notifier


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_pipeline(query: str = "", dry_run: bool = False) -> list[ScoredListing]:
    """
    Execute the full AutoScout pipeline.
    Returns a list of scored listings.
    """
    start = time.time()
    os.makedirs("output", exist_ok=True)
    os.makedirs("output/.price_cache", exist_ok=True)

    logger.info("=" * 60)
    logger.info("AutoScout AI — Starting pipeline")
    logger.info(f"Location: {LOCATION['city']} ({LOCATION['search_radius_miles']}mi radius)")
    logger.info(f"Filters: year {FILTERS['min_year']}–{FILTERS['max_year']}, "
                f"max ${FILTERS['max_price']:,}, max {FILTERS['max_mileage']:,}mi")
    logger.info("=" * 60)

    # ── Step 1: Scrape listings ───────────────────────────────────────────────
    logger.info("STEP 1 — Scraping listings")

    all_raw = []

    if SOURCES.get("craigslist"):
        scraper = CraigslistScraper(
            city=LOCATION["city"],
            config=FILTERS,
            vehicle_types=VEHICLE_TYPES,
        )
        raw_listings = scraper.scrape(query=query)
        all_raw.extend(raw_listings)
        logger.info(f"Craigslist: {len(raw_listings)} listings after filtering")

    if not all_raw:
        logger.warning("No listings found. Check your filters or try a broader search.")
        return []

    logger.info(f"Total raw listings: {len(all_raw)}")

    # ── Step 2: Price lookups ─────────────────────────────────────────────────
    logger.info("STEP 2 — Fetching market values (KBB)")

    pricer = KBBPricer() if PRICING_SOURCES.get("kbb") else None

    # ── Step 3: Score listings ────────────────────────────────────────────────
    logger.info("STEP 3 — Scoring listings")

    scorer = DealScorer(config={**SCORING, **MESSAGING})
    db = Database(db_path=OUTPUT["db_path"])

    scored_listings = []
    for i, raw in enumerate(all_raw, 1):
        logger.info(f"  [{i}/{len(all_raw)}] {raw.title[:50]}")

        # Price lookup
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
            # We have a pricer but couldn't parse make/model — use fallback
            logger.debug(f"  Skipping price lookup (missing make/model/year for: {raw.title})")

        # Score
        scored = scorer.score(raw, price_est)
        scored_listings.append(scored)
        db.upsert_listing(scored)

    # Sort: best deals first
    scored_listings = sort_listings(scored_listings)

    # ── Step 4: Draft messages ────────────────────────────────────────────────
    logger.info("STEP 4 — Drafting messages for deals")

    drafter = MessageDrafter(
        use_claude=bool(os.getenv("ANTHROPIC_API_KEY"))
    )

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
        "asking_price", "kbb_value", "savings_vs_kbb", "savings_pct",
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
        # Simple built-in scheduler (use n8n/cron for production)
        import schedule as sched

        interval_hours = 1  # Change this or read from config
        logger.info(f"Scheduled mode: running every {interval_hours} hour(s)")

        sched.every(interval_hours).hours.do(
            run_pipeline, query=args.query, dry_run=args.dry_run
        )

        # Run immediately on start
        run_pipeline(query=args.query, dry_run=args.dry_run)

        while True:
            sched.run_pending()
            time.sleep(60)
    else:
        run_pipeline(query=args.query, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
