"""
config.py — AutoScout AI Search Configuration
Edit this file to define what vehicles you're hunting for.
"""

# ── LOCATION ────────────────────────────────────────────────────────────────
LOCATION = {
    "city": "phoenix",          # Craigslist city subdomain (phoenix.craigslist.org)
    "zip_code": "85001",
    "search_radius_miles": 50,
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
    "min_year": 2018,
    "max_year": 2025,
    "max_price": 40000,         # USD
    "min_price": 3000,          # Avoid junk listings
    "max_mileage": 100000,
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
