# TICKET-005 — More Accurate CL Scraping: Full `.attrgroup` Extraction + Comp Model Matching

**Status:** Open — Ready to Implement
**Priority:** High
**Created:** 2026-03-31
**Components:** `scrapers/craigslist.py`, `utils/comps.py`, `utils/normalizer.py`

---

## Problem

Two related issues cause inaccurate scraping and broken local market comps:

### Issue A — Incomplete `.attrgroup` Parsing

Every CL listing detail page has two `.attrgroup` blocks on the right side, below the map:

**Block 1 — Vehicle identity (year make model):**
```
2007 kia sorento
```

**Block 2 — Structured specs:**
```
condition: excellent
cylinders: 6 cylinders
fuel: gas
odometer: 149,000
title status: clean
transmission: automatic
type: SUV
```

The current `_fetch_detail` only extracts **3 of 8 available fields** from `.attrgroup`:
- ✅ `odometer` — extracted
- ✅ `title status` — extracted
- ✅ `condition` — extracted
- ❌ `cylinders` — not extracted
- ❌ `fuel` — not extracted
- ❌ `transmission` — not extracted
- ❌ `type` (body type: SUV, sedan, truck, etc.) — not extracted
- ❌ **Year/make/model from Block 1** — not extracted

Missing the Block 1 identity header is the root cause of Issue B below.

---

### Issue B — Comp Pool Misses Same-Vehicle Listings

**Example observed in production:**

| Listing | Title | Comp Result |
|---------|-------|-------------|
| `7924681977` | "2007 kia sorento 83k" | Local comps: only 1 (itself) |
| `7922428211` | "2007 kia sorento v6 1owner" | Not found as a comp |

Both are 2007 Kia Sorentos. They should comp each other.

**Root cause:** The title parser extracts make/model from the listing card title text.
Titles like `"2007 kia sorento lx"` get stored as `model = "sorento lx"` while
`"2007 kia sorento v6 1owner"` gets stored as `model = "sorento v6 1owner"`.

The comps engine keys on `(make.lower(), model.lower())` — an exact string match.
`"sorento lx"` ≠ `"sorento"` ≠ `"sorento v6 1owner"` — all three miss each other.

The `.attrgroup` Block 1 header always contains the **clean, canonical year/make/model**
without trim noise — e.g. `"2007 kia sorento"`. Using this as the authoritative
make/model source would fix the mismatch entirely.

---

## Proposed Fix

### Part 1 — Extract all `.attrgroup` fields in `_fetch_detail`

Replace the current partial `.attrgroup` loop with a full parser:

```python
# scrapers/craigslist.py — _fetch_detail()

# ── .attrgroup parsing ──────────────────────────────────────────────────────
# Block 1: vehicle identity heading (span.heading inside first .attrgroup)
#   <p class="attrgroup"><span class="heading">2007 kia sorento</span></p>
# Block 2: key/value specs
#   <p class="attrgroup"><span>condition: excellent</span><span>cylinders: 6 ...</span>...
#
# Strategy: collect all .attrgroup elements, check first for heading span,
# then parse all remaining spans as "key: value" pairs.

attrgroups = page.locator(".attrgroup").all()
attrs: dict[str, str] = {}
cl_identity: str = ""   # raw "2007 kia sorento" string from heading

for group in attrgroups:
    # Check for heading span (vehicle identity block)
    heading = group.locator("span.heading")
    if heading.count():
        cl_identity = heading.first.inner_text().strip().lower()
        continue

    # Key/value spec block
    for span in group.locator("span").all():
        text = span.inner_text().strip()
        if ":" in text:
            key, _, val = text.partition(":")
            attrs[key.strip().lower()] = val.strip().lower()

# Apply parsed attributes
if attrs.get("odometer"):
    m = re.search(r"[\d,]+", attrs["odometer"])
    if m:
        odometer_from_attrs = int(m.group(0).replace(",", ""))

if attrs.get("title status"):
    listing.title_status = attrs["title status"]

if attrs.get("condition"):
    listing.condition = attrs["condition"]

if attrs.get("cylinders"):
    listing.cylinders = attrs["cylinders"]          # "6 cylinders"

if attrs.get("fuel"):
    listing.fuel = attrs["fuel"]                    # "gas"

if attrs.get("transmission"):
    listing.transmission = attrs["transmission"]    # "automatic"

if attrs.get("type"):
    listing.body_type = attrs["type"]               # "SUV", "pickup", "sedan"
```

Add the new fields to `RawListing`:
```python
@dataclass
class RawListing:
    ...
    cylinders: str = ""
    fuel: str = ""
    transmission: str = ""
    body_type: str = ""
```

---

### Part 2 — Use `.attrgroup` Block 1 as authoritative make/model

When `cl_identity` is available (e.g. `"2007 kia sorento"`), parse it as the
authoritative year/make/model — overriding title-derived values that contain trim noise.

```python
# scrapers/craigslist.py — _fetch_detail(), after attrgroup parsing

if cl_identity:
    # cl_identity format: "YEAR MAKE MODEL" (no trim, always clean)
    parts = cl_identity.split()
    if len(parts) >= 3:
        year_m = re.match(r"\b(19|20)\d{2}\b", parts[0])
        if year_m:
            listing.year  = int(parts[0])
            listing.make  = parts[1].title()            # "Kia"
            listing.model = " ".join(parts[2:]).title() # "Sorento" (no trim)
            logger.debug(
                f"  Identity from attrgroup: {listing.year} {listing.make} {listing.model}"
            )
```

This ensures `model = "Sorento"` for all Sorento variants regardless of how the
seller titles their listing ("Sorento LX", "Sorento V6", "Sorento 4WD", etc.).

---

### Part 3 — Comp pool: match on base model (strip trim from stored model)

Even without Part 2, the comps engine should strip common trim suffixes before keying:

```python
# utils/comps.py — add helper

_TRIM_NOISE = re.compile(
    r"\b(lx|ex|se|le|xl|xlt|sr|sr5|trd|limited|sport|premium|base|plus|"
    r"pro|4wd|awd|fwd|rwd|v6|v8|4cyl|turbo|diesel|hybrid|1owner|"
    r"one owner|clean title|loaded|runs great)\b.*",
    re.IGNORECASE,
)

def _base_model(model: str) -> str:
    """Strip trim/descriptor noise from model string for comp matching."""
    return _TRIM_NOISE.sub("", model).strip().lower()

# In _preload() and get_market_price():
key = (l.make.lower(), _base_model(l.model))
```

---

### Part 4 — Store new fields in DB + expose in API

Add columns to the `listings` table:
```sql
ALTER TABLE listings ADD COLUMN cylinders TEXT;
ALTER TABLE listings ADD COLUMN fuel TEXT;
ALTER TABLE listings ADD COLUMN transmission TEXT;
ALTER TABLE listings ADD COLUMN body_type TEXT;
```

Expose in `Deal` interface (`web/lib/api.ts`) and show in the deal detail Overview tab.

---

## Acceptance Criteria

- [ ] `_fetch_detail` extracts all 7 structured fields from `.attrgroup` Block 2
- [ ] `cl_identity` (Block 1 heading) is parsed and used as authoritative make/model
- [ ] 2007 Kia Sorento listings comp against each other regardless of title trim text
- [ ] Log line per listing: `Identity from attrgroup: 2007 Kia Sorento`
- [ ] Log line: `Attrs: condition=excellent cylinders=6 fuel=gas transmission=automatic type=SUV`
- [ ] `cylinders`, `fuel`, `transmission`, `body_type` stored in DB + returned in API
- [ ] Listings without a Block 1 heading fall back gracefully (current title-parse behavior)
- [ ] Comp pool size increases — test listing should have ≥2 comps after fix
- [ ] No regression on existing fields (mileage, title status, VIN still correct)

---

## Files to Change

| File | Change |
|------|--------|
| `scrapers/craigslist.py` | Full `.attrgroup` parser, `cl_identity` make/model override, new `RawListing` fields |
| `utils/comps.py` | `_base_model()` trim stripper, apply to pool keys in `_preload()` and `get_market_price()` |
| `utils/db.py` | Add `cylinders`, `fuel`, `transmission`, `body_type` columns |
| `utils/normalizer.py` | Apply `_base_model()` stripping on ingest |
| `web/lib/api.ts` | Add 4 new fields to `Deal` interface |
| `web/app/deals/page.tsx` | Show fuel/transmission/body_type in Overview tab |

---

## Example: Before vs After

**Listing title:** `"2007 kia sorento lx v6 1owner clean"`

| Field | Before (title-parsed) | After (attrgroup) |
|-------|-----------------------|-------------------|
| `make` | `Kia` | `Kia` |
| `model` | `Sorento Lx V6 1Owner Clean` | `Sorento` |
| `comp key` | `(kia, sorento lx v6 1owner clean)` | `(kia, sorento)` |
| `cylinders` | — | `6 cylinders` |
| `fuel` | — | `gas` |
| `transmission` | — | `automatic` |
| `body_type` | — | `SUV` |
| `comp matches` | 0 (self only) | 3–10 (all Sorento listings) |

---

## Notes

- The `.attrgroup` Block 1 heading is not present on all listings — older or incomplete
  listings may omit it. Always fall back to title parsing when it's absent.
- Transmission data from `.attrgroup` is more reliable than description text mining —
  sellers often omit "automatic" in the title but always fill in the structured form.
- Body type (`type: SUV` / `type: pickup` / `type: sedan`) could be a future comp
  filter — only comp SUVs against SUVs. Deferred for now, store the data first.
- Related: **TICKET-001** (pagination — more listings = richer comp pool naturally)
