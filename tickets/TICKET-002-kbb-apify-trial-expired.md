# TICKET-002 — KBB Pricing Broken: Apify Free Trial Expired

**Status:** Open — Awaiting Decision
**Priority:** High
**Created:** 2026-03-31
**Component:** `pricing/kbb_apify.py`, `scoring/engine.py`

---

## Problem

The Apify `parseforge/kelley-blue-book-scraper` actor used to fetch real KBB pricing
has exhausted its free trial on Railway. Every listing now fails KBB pricing silently,
falling back to `kbb_value = None`. This means:

- All blended market valuations use only Carvana + local comps (no KBB weight)
- Listings without Carvana data (no comparable inventory) get `blended_market_value = None`
- Deal scoring degrades significantly — savings calculations are unreliable

The actor is `parseforge/kelley-blue-book-scraper` on Apify.
Current token: `APIFY_API_TOKEN` env var on Railway.

---

## Root Cause

Apify free plan allows a limited number of actor runs. The `parseforge/kelley-blue-book-scraper`
actor exhausted its free compute units. Every call now returns a 402 or quota error,
which is caught silently and returns `None`.

```python
# pricing/kbb_apify.py — failure is swallowed
except Exception:
    return None   # ← no log, pipeline continues unpriced
```

---

## Options

### Option A — Pay for Apify Actor (~$5/mo) ✅ Recommended if budget allows
- Upgrade Apify account to Starter plan
- No code changes required
- Most accurate KBB data (real KBB fppPrice + fairMarketPriceAverage)
- **Decision needed from owner**

### Option B — Swap to Free KBB Scraper (no cost, more brittle)
Replace `kbb_apify.py` with a direct KBB scraper using Playwright:
- Scrape `kbb.com/MAKE/MODEL/YEAR/` HTML directly
- Parse `#js-page-data` JSON blob embedded in the page (KBB renders it server-side)
- No API key required, but KBB may add bot protection over time
- Estimated build: 2–3 hours

### Option C — Use NHTSA + vAuto/Marketcheck public APIs (free, VIN-based)
- NHTSA API is free and returns MSRP, body style, engine for a given VIN
- Marketcheck has a free tier (100 req/day) returning market average price
- Requires VIN — listings without VIN would still fall back to nothing
- Estimated build: 3–4 hours

---

## Recommended Fix (Option B sketch)

```python
# pricing/kbb_playwright.py — new file
from playwright.sync_api import sync_playwright

def get_kbb_price(make, model, year, mileage):
    url = f"https://www.kbb.com/{make}/{model}/{year}/"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        # KBB embeds pricing JSON in a <script id="js-page-data"> tag
        raw = page.eval_on_selector("#js-page-data", "el => el.textContent")
        data = json.loads(raw)
        # parse private party / trade-in / retail from data["initialState"]
        ...
```

---

## Acceptance Criteria

- [ ] KBB pricing returns a value for at least 80% of listings in a test run
- [ ] Failed KBB lookups log a WARNING (not silent None)
- [ ] 7-day disk cache still applies to avoid redundant fetches
- [ ] Blended score uses correct 20% KBB weight when value is available
- [ ] Run logs show `KBB: $18,400 (medium confidence)` per listing

---

## Files to Change

- `pricing/kbb_apify.py` — add error logging on quota failure
- `pricing/kbb_playwright.py` — new file (Option B) or `pricing/kbb_nhtsa.py` (Option C)
- `main.py` — swap import to new pricing module
- `config.py` — remove or repurpose `APIFY_API_TOKEN` dependency

---

## Notes

- Carvana pricing (`pricing/carvana.py`) also crashes on Railway due to camoufox/GPU issue —
  see **TICKET-003**. Both pricing sources are broken simultaneously on Railway.
- With both KBB and Carvana broken, the blended score falls back to local market comps only
  (which uses asking prices of similar scraped listings — a reasonable but less reliable signal).
- Related: **TICKET-003** (Carvana camoufox crash), **TICKET-004** (thread limit)
