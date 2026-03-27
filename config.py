"""
config.py — AutoScout AI Search Configuration
Edit this file to define what vehicles you're hunting for.
"""

# ── LOCATION ────────────────────────────────────────────────────────────────
LOCATION = {
    "city": "phoenix",          # Craigslist city subdomain (phoenix.craigslist.org)
    "zip_code": "85001",
    "search_radius_miles": 500,
}

# ── VEHICLE FILTERS ─────────────────────────────────────────────────────────
VEHICLE_TYPES = ["cars", "trucks", "suvs"]   # Filter categories

SEARCH_QUERIES = [
    # Add any search terms you want Craigslist to match
    # Leave empty to get all listings and filter locally
    "",   # empty = all vehicles in your filters
    # "tacoma",
    # "f-150",
    # "honda civic",
]

FILTERS = {
    "min_year": 2009,
    "max_year": 2025,
    "max_price": 40000,         # USD
    "min_price": 2000,          # Avoid junk listings
    "max_mileage": 190000,
    "min_mileage": 0,
    "exclude_salvage": True,    # Skip salvage/rebuilt titles
}

# ── SCORING THRESHOLDS ──────────────────────────────────────────────────────
SCORING = {
    # Deal classification by score (0–100)
    "great_deal_min_score": 75,     # 🔥 Auto-message (if enabled)
    "fair_deal_min_score": 50,      # ⚡ Notify me

    # Score components
    "price_weight": 0.65,           # % of score based on price vs market
    "mileage_weight": 0.20,         # % based on mileage
    "age_weight": 0.15,             # % based on vehicle age

    # Mileage scoring: penalty per 10,000 miles over 30k baseline
    "mileage_baseline": 30000,
    "mileage_penalty_per_10k": 3,   # points deducted

    # Great deal = asking price is X% below KBB
    "great_deal_pct_below_kbb": 0.15,    # 15% below
    "fair_deal_pct_below_kbb": 0.05,     # 5% below
}

# ── SOURCES ─────────────────────────────────────────────────────────────────
SOURCES = {
    "craigslist": True,
    "facebook_marketplace": True,   # Enabled — APIFY_API_TOKEN set in .env
    "offerup": False,               # Phase 2
}

PRICING_SOURCES = {
    "kbb": True,
    "carvana": True,        # Enabled — scrapes Carvana for comparable prices
    "carmax": True,         # Enabled — scrapes CarMax for comparable prices

    # VinAudit: real transaction data via VIN (requires VINAUDIT_API_KEY in .env)
    # 500 free calls, then ~$0.01/call. Used only for listings that have a VIN.
    "vinaudit": True,

    # KBB via Apify: real KBB fair market price + MSRP via parseforge/kelley-blue-book-scraper
    # Uses existing APIFY_API_TOKEN — free plan covers ~100 items/run (4-16 per vehicle).
    # Returns fair purchase price + fair market range across all trims. No VIN needed.
    "kbb_apify": True,

    # CarsXE: make/model/year/mileage market value (requires CARSXE_API_KEY in .env)
    # 100 free calls, then ~$0.01–$0.05/call. Used as KBB fallback when no VIN.
    "carsxe": True,

    # Carvana cash offer flow: runs the full sell-my-car automation for listings
    # that have a VIN and score fair/great. SLOW (~2 min/VIN), runs in parallel.
    # Only enable if you want guaranteed exit price validation per listing.
    "carvana_offer_flow": False,
}

# ── MESSAGING ────────────────────────────────────────────────────────────────
MESSAGING = {
    "auto_send_great_deals": False,     # Set True only after testing!
    "require_approval_fair_deals": True,
    "skip_already_contacted": True,
    "include_offer_price": True,
    "offer_pct_below_asking": 0.08,     # Offer 8% below asking price
}

# ── NOTIFICATIONS ─────────────────────────────────────────────────────────
NOTIFICATIONS = {
    "sms_on_great_deal": False,     # Requires Twilio in .env
    "email_on_great_deal": False,
}

# ── OUTPUT ───────────────────────────────────────────────────────────────────
OUTPUT = {
    "csv_path": "output/deals.csv",
    "db_path": "output/autoscout.db",
    "print_all": True,              # Print all listings to terminal
    "print_great_only": False,      # Only print great deals
}
