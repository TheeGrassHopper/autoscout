# TICKET-001 — Craigslist Pagination: Lift the 120-Listing Cap

**Status:** Open
**Priority:** Medium
**Created:** 2026-03-31
**Component:** `scrapers/craigslist.py`

---

## Problem

The Craigslist scraper fetches only the **first page of results** per category.
Craigslist returns **120 listings per page**, so every run is hard-capped at 120 listings
regardless of how many are actually available in the search area.

There is no pagination loop. `_build_url()` produces a single URL with no offset,
and `_scrape_page()` is called exactly once per category.

```python
# Current — single page only
for cat in self.CATEGORIES:
    url = self._build_url(cat, query)   # no &s= offset
    listings = self._scrape_page(context, url)
```

---

## Root Cause

`_build_url()` never appends Craigslist's pagination offset parameter (`&s=N`).
Craigslist uses `s=0`, `s=120`, `s=240`, … to paginate results.

---

## Proposed Fix

1. Add `max_pages` to `SCRAPING` config (default `3`, giving up to 360 listings per run).
2. Add a pagination loop in `CraigslistScraper.scrape()` that:
   - Builds URLs with `&s=0`, `&s=120`, `&s=240`, …
   - Stops early if a page returns 0 new listings (end of results).
   - Respects `max_pages` cap to avoid runaway scraping.
3. Keep deduplication by `listing_id` across pages (already in place via `seen_ids`).

### Sketch

```python
# config.py — add to SCRAPING block
"max_pages": 3,   # 3 × 120 = up to 360 listings per category

# scrapers/craigslist.py — replace single call with loop
max_pages = self.config.get("max_pages", 3)
for page_num in range(max_pages):
    offset = page_num * 120
    url = self._build_url(cat, query, offset=offset)
    page_listings = self._scrape_page(context, url)
    new = [l for l in page_listings if l.listing_id not in seen_ids]
    if not new:
        break   # no more results
    for l in new:
        seen_ids.add(l.listing_id)
        all_listings.append(l)

# _build_url — add offset param
def _build_url(self, category: str, query: str = "", offset: int = 0) -> str:
    ...
    if offset:
        params["s"] = offset
```

---

## Impact

| Before | After |
|--------|-------|
| Max 120 listings / run | Up to `max_pages × 120` listings |
| 1 HTTP request / category | Up to `max_pages` requests / category |
| Run time ~same | Slightly longer per extra page (~10–20s each) |

---

## Acceptance Criteria

- [ ] `max_pages = 1` reproduces current behaviour exactly
- [ ] `max_pages = 3` returns up to 360 listings for a broad query (e.g. no query string)
- [ ] Pagination stops early when a page returns no new results
- [ ] Deduplication across pages works (no duplicate `listing_id` in DB)
- [ ] Log line per page: `Craigslist [cto] page 2/3: 95 listings`
- [ ] `max_pages` is exposed in the pipeline run API params and dashboard UI

---

## Files to Change

- `config.py` — add `max_pages` to `SCRAPING`
- `scrapers/craigslist.py` — `_build_url()` + `scrape()` pagination loop
- `api/app.py` — pass `max_pages` from run params if exposed via UI
- `web/app/page.tsx` — optional UI control for max pages on the run panel

---

## Notes

- Craigslist does not require authentication for search pages — no extra rate-limit risk.
- Each extra page adds ~1 Playwright request (~5–10s). 3 pages adds ~10–30s to run time.
- Thread limit (`can't start new thread`) becomes more likely with more listings —
  resolve **TICKET-004** (reduce `_DETAIL_WORKERS`) before or alongside this ticket.
- Related: **TICKET-004** (thread limit crash)
