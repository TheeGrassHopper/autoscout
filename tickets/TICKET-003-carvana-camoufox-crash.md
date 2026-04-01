# TICKET-003 — Carvana Pricing Crashes on Railway (camoufox SIGSEGV)

**Status:** Open — Awaiting Decision
**Priority:** High
**Created:** 2026-03-31
**Component:** `pricing/carvana.py`

---

## Problem

`pricing/carvana.py` uses `camoufox` (stealth Firefox) to intercept the
`merch/search/api/v2/pricing` JSON response from Carvana's SRP.

On Railway (Linux, no GPU, no display server), camoufox crashes with:

```
glxtest: failed to open connection to X server
glxtest: process failed (SIGSEGV) — returning false
```

Firefox requires GPU/GLX or a virtual framebuffer (Xvfb) to initialise.
Railway containers have neither. The crash happens before any page loads,
so **every Carvana pricing call returns `(None, None)`** on Railway.

Works fine locally on macOS (has GPU + display).

---

## Root Cause

camoufox launches a real Firefox process. Firefox attempts GPU detection via
`glxtest` at startup. In Railway's headless Linux container without Xvfb or a
GPU driver, the `glxtest` subprocess SIGSEGVs, causing Firefox/camoufox to abort.

Vanilla Playwright Chromium does not have this issue (Chromium has `--no-sandbox`
and `--disable-gpu` flags). camoufox does not support equivalent bypass flags.

---

## Proposed Fix — Replace camoufox with Direct Carvana JSON API

Carvana's internal search API is reachable directly with a plain `httpx` GET.
No browser needed. The endpoint used by camoufox interception is:

```
GET https://apim.carvana.io/merch/search/api/v2/vehicles
    ?year-min=2019&year-max=2023&make=toyota&model=tacoma&miles-max=120000
    &page-size=20&page-number=1
```

Headers required: `User-Agent`, `Accept: application/json`.
Returns a JSON array of vehicles with `incentivizedPrice` and `kbbValue` fields —
exactly what we currently intercept via camoufox.

### Sketch

```python
# pricing/carvana.py — replace _fetch_from_carvana with:
import httpx

CARVANA_API = "https://apim.carvana.io/merch/search/api/v2/vehicles"

def _fetch_from_carvana_api(make, model, year, mileage, year_range=2, mileage_range=20_000):
    params = {
        "make": make.lower(),
        "model": model.lower().split()[0],
        "year-min": year - year_range,
        "year-max": year + year_range,
        "miles-max": mileage + mileage_range,
        "page-size": 20,
        "page-number": 1,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...",
        "Accept": "application/json",
        "Origin": "https://www.carvana.com",
        "Referer": "https://www.carvana.com/",
    }
    resp = httpx.get(CARVANA_API, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    vehicles = resp.json().get("vehicles") or resp.json().get("data", [])
    prices  = [v["incentivizedPrice"] for v in vehicles if v.get("incentivizedPrice")]
    kbb_vals = [v["kbbValue"] for v in vehicles if v.get("kbbValue")]
    return (
        int(statistics.median(prices))   if prices   else None,
        int(statistics.median(kbb_vals)) if kbb_vals else None,
    )
```

**Advantages over camoufox:**
- No browser, no GPU, no Xvfb — runs fine on Railway
- ~10–50x faster per call (HTTP vs browser automation)
- Same data fields (`incentivizedPrice`, `kbbValue`)
- Less likely to hit rate limits than browser sessions

**Risk:** Carvana may add auth headers or rotate the internal API endpoint.
Current endpoint has been stable since 2023. Fallback: revert to camoufox locally.

---

## Acceptance Criteria

- [ ] `get_carvana_price()` returns a non-None value on Railway for a known vehicle (e.g. 2021 Toyota Tacoma)
- [ ] No camoufox/Firefox import on Railway (gate behind try/except or env flag)
- [ ] 7-day cache still applies (same cache key logic)
- [ ] Logs show `Carvana API: $28,500 (3 comps)` not `Carvana: failed`
- [ ] If API returns 4xx/5xx, falls back gracefully to `(None, None)` with a WARNING log
- [ ] Works both locally (direct API) and on Railway (direct API)

---

## Files to Change

- `pricing/carvana.py` — replace `_fetch_from_carvana` (camoufox) with `_fetch_from_carvana_api` (httpx)
- `requirements.txt` — add `httpx` if not already present (check first)
- `config.py` — no changes needed

---

## Notes

- `httpx` may already be installed as a transitive dependency; check `requirements.txt` first.
- The Carvana internal API does not require an API key currently, but this may change.
  If it does, the camoufox approach can be reinstated locally while a paid Carvana
  data provider is evaluated for Railway.
- This is the highest-ROI fix of the four open issues — no cost, no Playwright,
  fixes Railway production pricing immediately.
- Related: **TICKET-002** (KBB Apify expired), **TICKET-004** (thread limit)
