# TICKET-006: Skip Already Scored Listings (Incremental Runs)

**Priority:** High
**Status:** ✅ Completed — 2026-04-01
**Area:** `main.py`, `utils/db.py`

---

## Problem

Every pipeline run re-scrapes and re-scores **all** listings — including ones already in the database from previous runs. On a typical run with 200 Craigslist + 300 Facebook listings, ~90% may already be in the DB. We're wasting:

- **Apify credits** (Facebook actor costs credits per run regardless)
- **Pricing API calls** (Carvana, KBB, VinAudit — each charged per lookup)
- **Pipeline time** (full pricing chain runs on every listing every time)

The `seen_ids` set in `main.py` only deduplicates within a single run session. It never checks the database.

---

## Root Cause

In `main.py`, after scraping, `_fetch_prices()` is called on every listing unconditionally:

```python
for raw in all_listings:
    scored = await scorer.score(raw, ...)  # runs pricing chain on everything
    db.upsert_listing(scored)
```

There is no check like `if listing_id not in db` before pricing.

---

## Proposed Solution

### Step 1 — Load existing IDs from DB before pricing loop

```python
existing_ids = set(db.get_all_listing_ids())
```

### Step 2 — Split listings into new vs known

```python
new_listings = [r for r in all_listings if r.listing_id not in existing_ids]
known_listings = [r for r in all_listings if r.listing_id in existing_ids]
```

### Step 3 — Only run full pricing on new listings

```python
for raw in new_listings:
    scored = await scorer.score(raw, ...)  # full pricing chain
    db.upsert_listing(scored)

# Known listings: skip re-scoring entirely
# (their existing DB record already has pricing data)
```

### Step 4 — Add `get_all_listing_ids()` to `utils/db.py`

```python
def get_all_listing_ids(self) -> list[str]:
    rows = self.conn.execute("SELECT listing_id FROM listings").fetchall()
    return [r[0] for r in rows]
```

---

## Edge Cases to Handle

- **Price changed on a known listing** — consider re-pricing if `price` changed significantly (>10%) since last scrape. Could check `price != db_price` as a re-score trigger.
- **Listings removed from source** — not in scope; DB keeps them as-is.
- **Forced re-score** — add a `--force-rescore` CLI flag or UI toggle for full refresh when needed.

---

## Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| Listings priced per run | ~500 | ~50 (new only) |
| Apify pricing calls/run | ~500 | ~50 |
| Pipeline run time | ~8 min | ~2 min |
| DB writes | ~500 | ~50 |

---

## Files to Modify

- `utils/db.py` — add `get_all_listing_ids()`
- `main.py` — split new vs known before pricing loop
- `web/app/page.tsx` (optional) — show "X new listings found" in run output
