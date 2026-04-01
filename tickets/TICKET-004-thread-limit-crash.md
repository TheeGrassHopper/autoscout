# TICKET-004 — Thread Limit Crash: "can't start new thread"

**Status:** Open — Ready to Implement
**Priority:** High
**Created:** 2026-03-31
**Component:** `scrapers/craigslist.py`

---

## Problem

When scraping a large result set, the pipeline crashes mid-run with:

```
RuntimeError: can't start new thread
```

This happens inside the `ThreadPoolExecutor` that fetches detail pages concurrently.
Each worker launches its own `sync_playwright()` → `chromium.launch()` instance,
which spawns multiple OS threads per browser (renderer, IO, network threads).

With `_DETAIL_WORKERS = 5` and ~120+ listings, the total thread count can exceed
the OS limit (typically 1024 on Railway's Linux containers), causing the crash.

The crash kills the entire pipeline run — no listings are scored or saved.

---

## Root Cause

```python
# scrapers/craigslist.py line 28
_DETAIL_WORKERS = 5  # concurrent detail page fetches

# line 325 — each worker is a full browser instance
with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as pool:
    ...
```

Each `sync_playwright()` + `chromium.launch()` call spawns ~15–20 OS threads
(browser main thread, renderer, GPU, IO, watchdog, etc.).

`5 workers × ~20 threads/worker = ~100 threads` just for detail workers.
Combined with the main scrape browser + FastAPI/uvicorn threads + Railway baseline,
this can exceed the container's thread limit.

With **TICKET-001** (pagination) implemented, the listing count could triple,
making this crash near-certain on every multi-page run.

---

## Fix

### Immediate (one-line) — Reduce `_DETAIL_WORKERS`

```python
# scrapers/craigslist.py — change line 28
_DETAIL_WORKERS = 2  # was 5 — reduces thread pressure on Railway
```

`2 workers × ~20 threads = ~40 threads` for detail fetching.
Slower (roughly 2.5× longer for detail phase) but stable.

### Better — Make it configurable via `config.py`

```python
# config.py — add to SCRAPING block
"detail_workers": 2,   # concurrent Playwright workers for detail pages

# scrapers/craigslist.py
_DETAIL_WORKERS = config.get("detail_workers", 2)
```

This allows tuning per environment — `2` on Railway, `4` locally.

### Best — Reuse a single browser for all detail pages (sequential within context)

Instead of spawning N browsers, open one browser and fetch detail pages
sequentially in a single context. Eliminates the multi-browser thread explosion
entirely. Slower than parallel but uses a fixed, low thread count.

```python
# sketch — sequential detail fetch in shared browser context
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent=ua)
    for listing in all_listings:
        if listing.url:
            self._fetch_detail(ctx, listing)
    ctx.close()
    browser.close()
```

Trade-off: loses parallelism (slower) but Railway-safe and much simpler.

---

## Recommended Approach

1. **Right now:** Drop `_DETAIL_WORKERS` from `5` → `2` (one-line fix, immediate stability)
2. **With TICKET-001 (pagination):** Move to single shared browser (sequential detail fetch)
   to keep thread count flat regardless of listing volume

---

## Acceptance Criteria

- [ ] Pipeline completes a full run without `RuntimeError: can't start new thread`
- [ ] Works at 120 listings (current) and 360 listings (post TICKET-001)
- [ ] `detail_workers` is configurable via `config.py` SCRAPING block
- [ ] Log line shows worker count: `Fetching 120 detail pages (2 workers)…`
- [ ] Run time regression is documented (expected ~2× slower detail phase)

---

## Files to Change

- `scrapers/craigslist.py` — change `_DETAIL_WORKERS = 5` → `2` (immediate fix)
- `config.py` — add `detail_workers` to `SCRAPING` block (configurable fix)
- `scrapers/craigslist.py` — optionally refactor to single shared browser (best fix)

---

## Notes

- This is the only ticket that is **purely a code fix** with no external dependency or decision needed.
- The immediate one-line fix (`_DETAIL_WORKERS = 2`) can be deployed in minutes.
- Detail page fetching is the slower phase of the scraper (~3–5s per listing).
  At `_DETAIL_WORKERS = 2` with 120 listings: ~180–300s (3–5 min) vs ~60–120s at 5 workers.
  Acceptable given runs are background tasks.
- If Railway thread limit is confirmed higher than 1024, `_DETAIL_WORKERS = 3` is a middle ground.
- Related: **TICKET-001** (pagination — more listings = more workers = more crashes)
