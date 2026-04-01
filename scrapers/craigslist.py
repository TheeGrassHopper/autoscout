"""
scrapers/craigslist.py
Scrapes Craigslist vehicle listings using Playwright (headless Chromium).

Craigslist migrated to a fully JS-rendered SPA in 2024 — the old RSS feeds
now return empty HTML shells. Playwright renders the page fully before
we extract listings.

Selectors confirmed against live phoenix.craigslist.org (2025):
  [data-pid]           — each listing card
  .label               — listing title
  .price / .priceinfo  — asking price
  .meta                — mileage + location + date text
  .result-location     — neighborhood
  .result-posted-date  — listing age
"""

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

_DETAIL_WORKERS = 5  # concurrent detail page fetches

logger = logging.getLogger(__name__)

# VIN pattern: 17 chars, no I/O/Q, must contain both letters and digits
_VIN_RE = re.compile(r'\b([A-HJ-NPR-Z0-9]{17})\b')

# Phone pattern: US numbers in common formats
# Matches: (480) 555-1234  480-555-1234  480.555.1234  4805551234  +1 480 555 1234
_PHONE_RE = re.compile(
    r'(?<!\d)'
    r'(?:\+?1[\s\-.]?)?'
    r'(?:\(?\d{3}\)?[\s\-.]?)'
    r'\d{3}[\s\-.]?\d{4}'
    r'(?!\d)'
)

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')


def _extract_phone(text: str) -> str:
    """Extract the first US phone number from free text. Returns digits-only string or ''."""
    if not text:
        return ""
    for m in _PHONE_RE.finditer(text):
        digits = re.sub(r'\D', '', m.group(0))
        # Strip leading country code 1 if present, giving 10-digit number
        if len(digits) == 11 and digits.startswith('1'):
            digits = digits[1:]
        if len(digits) == 10:
            return digits
    return ""


def _format_phone(digits: str) -> str:
    """Format 10-digit string as (XXX) XXX-XXXX."""
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return digits


def _extract_email(text: str) -> str:
    """Extract the first email address from free text, or ''."""
    if not text:
        return ""
    m = _EMAIL_RE.search(text)
    return m.group(0).lower() if m else ""


def _extract_mileage_from_description(text: str) -> Optional[int]:
    """
    Mine the listing description for mileage mentions.
    Handles: "125k miles", "125,000 miles", "125K mi", "odometer: 125,000",
             "at 125k", "with 125000 miles", "125k on it", etc.
    Returns the most prominent mileage found, or None.
    """
    if not text:
        return None

    candidates = []

    # Pattern: number followed by k/K then miles/mi (e.g. "125k miles", "45K mi")
    for m in re.finditer(r'\b(\d{1,3})[kK]\s*(?:miles?|mi)?\b', text):
        val = int(m.group(1)) * 1000
        if 1_000 <= val <= 400_000:
            candidates.append(val)

    # Pattern: number with comma separator (e.g. "125,000 miles", "45,000 mi")
    for m in re.finditer(r'\b(\d{1,3}),(\d{3})\s*(?:miles?|mi)\b', text, re.IGNORECASE):
        val = int(m.group(1)) * 1000 + int(m.group(2))
        if 1_000 <= val <= 400_000:
            candidates.append(val)

    # Pattern: plain number near "mile" context (e.g. "has 85000 miles")
    for m in re.finditer(r'\b(\d{4,6})\s*(?:miles?|mi)\b', text, re.IGNORECASE):
        val = int(m.group(1))
        if 1_000 <= val <= 400_000:
            candidates.append(val)

    if not candidates:
        return None

    # Return the most commonly mentioned value, or median if all differ
    from statistics import median
    return int(median(candidates))


def _reconcile_mileage(
    card_mileage: Optional[int],
    attr_mileage: Optional[int],
    desc_mileage: Optional[int],
) -> Optional[int]:
    """
    Reconcile potentially conflicting mileage values from three sources.

    Common seller mistake: entering "125" meaning 125,000 miles. Craigslist
    shows this as "125 mi" on the card. The attribute table and description
    usually have the correct value.

    Logic:
    1. If attr or desc mileage looks like card_mileage × ~1000, the card is
       missing three zeros — use the larger value.
    2. Otherwise prefer attr_mileage, then desc_mileage, then card_mileage.
    """
    best = attr_mileage or desc_mileage or card_mileage
    if not best:
        return card_mileage

    # Detect "missing zeros" pattern:
    # card says 125, attr/desc says 125,000 → ratio ~1000
    if card_mileage and card_mileage < 1_000:
        for source in (attr_mileage, desc_mileage):
            if source and 500 <= source <= 400_000:
                ratio = source / card_mileage
                if 800 <= ratio <= 1200:   # clearly the card dropped the trailing zeros
                    return source

    # If card mileage is suspiciously low for the context, prefer attr/desc
    if card_mileage and card_mileage < 500:
        if attr_mileage and attr_mileage > card_mileage * 10:
            return attr_mileage
        if desc_mileage and desc_mileage > card_mileage * 10:
            return desc_mileage

    # Normal case: trust attr over desc over card
    return attr_mileage or desc_mileage or card_mileage


def _extract_contact_from_reply(page, description: str) -> tuple[str, str]:
    """
    CL gates contact info behind a 'Reply' button — clicking it reveals the
    .cl-reply-flap panel containing the seller's name, phone, and/or email.

    DOM confirmed on live listings (2025):
      #replylink            — the "Reply" anchor that opens the flap
      .cl-reply-flap        — the panel that slides into view after click
      [href^='tel:']        — call / text phone links inside the flap
      [href^='mailto:']     — email link inside the flap

    Returns (phone_digits, email) — either may be empty string.
    """
    phone = ""
    email = ""
    try:
        # Click the reply button to reveal .cl-reply-flap
        reply_btn = page.locator("#replylink, .reply-button-link, button[data-href*='reply']").first
        if not reply_btn.count():
            logger.debug("Contact: no reply button found on %s", page.url)
            raise ValueError("no reply button found")

        reply_btn.click(timeout=5_000)
        logger.debug("Contact: clicked reply button on %s", page.url)

        # Wait for the flap panel to become visible
        flap = page.locator(".cl-reply-flap")
        flap.first.wait_for(state="visible", timeout=6_000)
        logger.debug("Contact: .cl-reply-flap visible on %s", page.url)

        # Extract phone from tel: links inside the flap (call or text)
        tel_links = flap.locator("[href^='tel:']").all()
        for tel in tel_links:
            href = tel.get_attribute("href") or ""
            p = _extract_phone(href.replace("tel:", ""))
            if p:
                phone = p
                break

        # Extract email from mailto: link inside the flap
        mailto_el = flap.locator("[href^='mailto:']").first
        if mailto_el.count():
            href = mailto_el.get_attribute("href") or ""
            email = _extract_email(href.replace("mailto:", ""))

        # Mine full flap text as a fallback for phone
        if not phone:
            flap_text = flap.first.inner_text()
            phone = _extract_phone(flap_text)
        if not email:
            flap_text = flap.first.inner_text()
            email = _extract_email(flap_text)

        logger.debug("Contact result: phone=%s email=%s on %s", phone or "none", email or "none", page.url)

    except Exception as exc:
        logger.debug("Contact extraction failed on %s: %s", page.url, exc)

    # Fall back to description text mining
    if not phone:
        phone = _extract_phone(description)
    if not email:
        email = _extract_email(description)

    return phone, email


def _extract_vin(text: str) -> str:
    """Extract a valid-looking VIN from free text. Returns first match or empty string."""
    if not text:
        return ""
    for m in _VIN_RE.finditer(text.upper()):
        candidate = m.group(1)
        # Must have at least one letter and one digit (filters out all-digit sequences)
        if re.search(r'[A-HJ-NPR-Z]', candidate) and re.search(r'[0-9]', candidate):
            return candidate
    return ""


# ── Data Model ────────────────────────────────────────────────────────────────

@dataclass
class RawListing:
    source: str = "craigslist"
    listing_id: str = ""
    url: str = ""
    title: str = ""
    price: Optional[int] = None
    location: str = ""
    posted_date: str = ""
    description: str = ""
    image_urls: list = field(default_factory=list)
    year: Optional[int] = None
    make: str = ""
    model: str = ""
    mileage: Optional[int] = None
    transmission: str = ""
    condition: str = ""
    title_status: str = ""
    color: str = ""
    vin: str = ""
    seller_phone: str = ""
    seller_email: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ── Scraper ───────────────────────────────────────────────────────────────────

class CraigslistScraper:
    BASE = "https://{city}.craigslist.org"
    CATEGORIES = ["cto"]   # by-owner only

    def __init__(self, city: str, config: dict, vehicle_types: list = None):
        self.city = city.lower()
        self.config = config
        self.base = self.BASE.format(city=self.city)

    def scrape(self, query: str = "") -> list[RawListing]:
        all_listings: list[RawListing] = []
        seen_ids: set = set()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            for cat in self.CATEGORIES:
                url = self._build_url(cat, query)
                logger.info(f"Scraping Craigslist [{cat}]: {url}")
                try:
                    listings = self._scrape_page(context, url)
                    for l in listings:
                        if l.listing_id not in seen_ids:
                            seen_ids.add(l.listing_id)
                            all_listings.append(l)
                    logger.info(f"  {cat}: {len(listings)} listings found")
                except Exception as e:
                    logger.error(f"Craigslist [{cat}] failed: {e}")

            browser.close()

        # Fetch detail pages concurrently — Playwright sync API is greenlet-bound
        # and cannot share a browser across threads. Each worker launches its own
        # playwright + browser instance.
        logger.info(f"Fetching {len(all_listings)} detail pages ({_DETAIL_WORKERS} workers)...")
        ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

        def _detail_worker(listing: RawListing):
            with sync_playwright() as pw:
                b = pw.chromium.launch(headless=True)
                ctx = b.new_context(user_agent=ua)
                try:
                    self._fetch_detail(ctx, listing)
                except Exception as e:
                    logger.debug(f"Detail fetch failed for {listing.listing_id}: {e}")
                finally:
                    ctx.close()
                    b.close()

        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as pool:
            futures = {
                pool.submit(_detail_worker, lst): lst
                for lst in all_listings
                if lst.url
            }
            for fut in as_completed(futures):
                exc = fut.exception()
                if exc:
                    lst = futures[fut]
                    logger.debug(f"Worker exception for {lst.listing_id}: {exc}")

        logger.info(f"Craigslist raw total: {len(all_listings)}")
        filtered = self._filter(all_listings)
        logger.info(f"Craigslist after filters: {len(filtered)}")
        return filtered

    def _scrape_page(self, context, url: str) -> list[RawListing]:
        page = context.new_page()
        results = []
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_selector("[data-pid]", timeout=15_000)
            except PWTimeout:
                logger.warning(f"No listings rendered at {url}")
                return []

            cards = page.locator("[data-pid]")
            total = cards.count()
            logger.info(f"  {total} cards on page")

            for i in range(total):
                try:
                    listing = self._parse_card(cards.nth(i))
                    if listing:
                        results.append(listing)
                except Exception as e:
                    logger.debug(f"Card {i} parse error: {e}")
        finally:
            page.close()
        return results

    def _parse_card(self, card) -> Optional[RawListing]:
        pid = card.get_attribute("data-pid") or ""
        if not pid:
            return None

        link = card.locator("a.main").first
        url = link.get_attribute("href") if link.count() else ""
        if not url:
            return None

        title = ""
        label = card.locator(".label")
        if label.count():
            title = label.first.inner_text().strip()

        price = None
        price_el = card.locator(".price, .priceinfo")
        if price_el.count():
            price = self._parse_price(price_el.first.inner_text())

        mileage, location, posted_date = None, "", ""
        meta = card.locator(".meta")
        if meta.count():
            meta_text = meta.first.inner_text()
            mi = re.search(r"([\d,]+)\s*(k)?\s*mi\b", meta_text, re.IGNORECASE)
            if mi:
                val = int(mi.group(1).replace(",", ""))
                if mi.group(2):
                    val *= 1000
                mileage = val

        # Posted date — dedicated span inside .meta
        date_el = card.locator(".result-posted-date")
        if date_el.count():
            posted_date = date_el.first.inner_text().strip()

        loc_el = card.locator(".result-location")
        if loc_el.count():
            location = loc_el.first.inner_text().strip()

        images = [
            img.get_attribute("src")
            for img in card.locator("img").all()
            if img.get_attribute("src") and "craigslist.org" in (img.get_attribute("src") or "")
        ]

        listing = RawListing(
            listing_id=pid, url=url, title=title, price=price,
            mileage=mileage, location=location, posted_date=posted_date,
            image_urls=images[:6],
        )
        self._parse_title_fields(listing, title)
        self._parse_title_status(listing)
        return listing

    def _build_url(self, category: str, query: str = "") -> str:
        params: dict = {"hasPic": "1"}
        if query:
            params["query"] = query
        if self.config.get("min_price"):
            params["min_price"] = self.config["min_price"]
        if self.config.get("max_price"):
            params["max_price"] = self.config["max_price"]
        if self.config.get("min_year"):
            params["min_auto_year"] = self.config["min_year"]
        if self.config.get("max_year"):
            params["max_auto_year"] = self.config["max_year"]
        if self.config.get("max_mileage"):
            params["auto_miles_max"] = self.config["max_mileage"]
        if self.config.get("search_radius_miles"):
            params["search_distance"] = self.config["search_radius_miles"]
        if self.config.get("zip_code"):
            params["postal"] = self.config["zip_code"]
        # Always filter for clean title only (auto_title_status=1 = clean title)
        params["auto_title_status"] = "1"
        return f"{self.base}/search/{category}?{urlencode(params)}"

    def _filter(self, listings: list[RawListing]) -> list[RawListing]:
        out = []
        for l in listings:
            if not l.price:
                continue
            if l.price < self.config.get("min_price", 0):
                continue
            if l.price > self.config.get("max_price", 999_999):
                continue
            if l.year:
                if l.year < self.config.get("min_year", 1900):
                    continue
                if l.year > self.config.get("max_year", 2100):
                    continue
            if l.mileage and l.mileage > self.config.get("max_mileage", 999_999):
                continue
            if self.config.get("exclude_salvage") and l.title_status == "salvage":
                continue
            out.append(l)
        return out

    def _fetch_detail(self, context, listing: RawListing):
        """Visit the individual listing page to extract full description, mileage, and VIN."""
        page = context.new_page()
        try:
            page.goto(listing.url, wait_until="domcontentloaded", timeout=20_000)

            # Full description
            desc_el = page.locator("#postingbody, .posting-description, section.postingbody")
            if desc_el.count():
                listing.description = desc_el.first.inner_text().strip()[:1200]

            # Attribute table — odometer, title status, condition
            # CL renders attrs as label/value pairs inside .attrgroup spans.
            # Format varies: "title status: clean" (single span) or label span
            # followed by value span. We handle both.
            odometer_from_attrs: Optional[int] = None
            title_status_from_attrs: str = ""
            attr_spans = page.locator(".attrgroup span, p.attrgroup span").all()
            for i, row in enumerate(attr_spans):
                text = row.inner_text().strip()
                lower = text.lower()
                if "odometer" in lower or "mileage" in lower:
                    m = re.search(r"([\d,]+)", text)
                    if m:
                        odometer_from_attrs = int(m.group(1).replace(",", ""))
                elif "title status" in lower:
                    # Value may be in same span ("title status: clean")
                    # or in the next sibling span
                    inline_val = re.sub(r"title status\s*:?\s*", "", lower).strip()
                    if inline_val:
                        title_status_from_attrs = inline_val
                    elif i + 1 < len(attr_spans):
                        next_text = attr_spans[i + 1].inner_text().strip().lower()
                        if next_text and ":" not in next_text:
                            title_status_from_attrs = next_text
                elif "condition" in lower:
                    listing.condition = re.sub(r"condition\s*:?\s*", "", lower).strip()

            # Apply attr-parsed title status — authoritative, don't overwrite with text mining
            if title_status_from_attrs:
                listing.title_status = title_status_from_attrs
                logger.debug(f"  Title status from attrs: {title_status_from_attrs} — {listing.title[:40]}")

            # ── Mileage correction ────────────────────────────────────────────
            # Sellers sometimes type "125" meaning 125k miles. We reconcile:
            # 1. Prefer the structured odometer attribute (most reliable)
            # 2. Fall back to description text mining
            # 3. Apply sanity check: if card mileage looks like it's missing zeros
            #    (e.g., card says 125 but attrs/description say 125,000), correct it.

            candidate = odometer_from_attrs or listing.mileage

            # Also mine description for mileage mentions as a cross-check
            desc_mileage = _extract_mileage_from_description(listing.description)

            corrected = _reconcile_mileage(listing.mileage, candidate, desc_mileage)
            if corrected and corrected != listing.mileage:
                logger.debug(
                    f"  Mileage corrected: {listing.mileage} → {corrected:,} "
                    f"(attr={odometer_from_attrs}, desc={desc_mileage}) — {listing.title[:40]}"
                )
                listing.mileage = corrected

            # Re-run title status detection now that we have full description
            self._parse_title_status(listing)

            # Extract VIN from description
            vin = _extract_vin(listing.description)
            if vin:
                listing.vin = vin
                logger.debug(f"  VIN found: {vin} — {listing.title[:40]}")

            # Extract phone + email — click Reply button to reveal contact info,
            # then fall back to description text mining.
            if not listing.seller_phone and not listing.seller_email:
                listing.seller_phone, listing.seller_email = _extract_contact_from_reply(
                    page, listing.description
                )
            if listing.seller_phone:
                logger.debug(f"  Phone found: {_format_phone(listing.seller_phone)} — {listing.title[:40]}")
            if listing.seller_email:
                logger.debug(f"  Email found: {listing.seller_email} — {listing.title[:40]}")

            # Extract full-resolution images from the detail page gallery
            full_images = []
            for img in page.locator("img.swipe-slide-img, .swipe-wrap img, #bigpic img").all():
                src = img.get_attribute("src") or img.get_attribute("data-src") or ""
                if src and "craigslist.org" in src:
                    # Upsize: replace _300 / _600 thumbnails with _1200
                    src = re.sub(r"_\d+\.jpg$", "_1200.jpg", src)
                    if src not in full_images:
                        full_images.append(src)
            if full_images:
                listing.image_urls = full_images[:20]
                logger.debug(f"  {len(full_images)} full-res images — {listing.title[:40]}")

        finally:
            page.close()

    def _parse_price(self, text: str) -> Optional[int]:
        m = re.search(r"\$\s*([\d,]+)", text)
        return int(m.group(1).replace(",", "")) if m else None

    def _parse_title_status(self, listing: RawListing):
        """Detect title status from the listing title and description.

        Only used as a fallback — if title_status was already set from the
        structured attribute table, that value is kept and text mining is skipped.
        """
        # Don't overwrite a structured value from the attr table with text mining
        if listing.title_status and listing.title_status not in ("unknown", ""):
            return

        text = f"{listing.title} {listing.description}".lower()
        if re.search(r"\bsalvage\b", text):
            listing.title_status = "salvage"
        elif re.search(r"\brebuilt\b", text):
            listing.title_status = "rebuilt"
        elif re.search(r"\bclean\s*title\b|\bclean title\b", text):
            listing.title_status = "clean"
        elif re.search(r"\blien\b", text):
            listing.title_status = "lien"
        elif re.search(r"\bmissing\s*title\b|no\s*title\b", text):
            listing.title_status = "missing"
        else:
            listing.title_status = "unknown"

    def _parse_title_fields(self, listing: RawListing, title: str):
        if not title:
            return
        m = re.search(r"\b(20[0-2]\d|19[89]\d)\b", title)
        if m:
            listing.year = int(m.group(1))

        MAKES = [
            "Chevrolet", "Volkswagen", "Mercedes-Benz", "Mercedes",
            "Toyota", "Nissan", "Subaru", "Hyundai", "Mazda", "Honda",
            "Mitsubishi", "Chrysler", "Cadillac", "Infiniti", "Lincoln",
            "Dodge", "Chevy", "Buick", "Acura", "Lexus", "Tesla",
            "Jeep", "Ford", "GMC", "RAM", "Ram", "BMW", "Audi",
            "Volvo", "Kia", "VW",
        ]
        for make in MAKES:
            if re.search(rf"\b{re.escape(make)}\b", title, re.IGNORECASE):
                listing.make = make.title()
                pos = title.lower().find(make.lower())
                after = title[pos + len(make):].strip()
                m2 = re.match(r"([\w-]+(?:\s+[\w-]+)?)", after)
                if m2:
                    listing.model = m2.group(1).strip()
                break
