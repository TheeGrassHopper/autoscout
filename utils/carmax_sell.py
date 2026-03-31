"""
utils/carmax_sell.py
Camoufox automation: CarMax "Sell My Car" flow to get a cash offer by VIN.
Uses camoufox (Firefox-based stealth browser) to bypass bot detection.
"""

import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

SELL_URL = "https://www.carmax.com/sell-my-car"
DEFAULT_ZIP = "85288"
DEFAULT_EMAIL = "almortada88@gmail.com"


def _parse_offer_range(text: str) -> tuple[Optional[str], Optional[int], Optional[int]]:
    # Match patterns like "$6,101 to $10,947" or "$6,101–$10,947" or "$6,101 - $10,947"
    m = re.search(
        r'\$([\d,]+)\s*(?:to|–|-)\s*\$([\d,]+)',
        text,
        re.I,
    )
    if m:
        low = int(m.group(1).replace(",", ""))
        high = int(m.group(2).replace(",", ""))
        offer_str = f"${low:,}–${high:,}"
        return offer_str, low, high
    # Single value fallback
    m2 = re.search(r'\$([\d,]{4,})', text)
    if m2:
        val = int(m2.group(1).replace(",", ""))
        if 500 <= val <= 300000:
            return f"${val:,}", val, val
    return None, None, None


async def run_carmax_offer(
    vin: str,
    mileage: int,
    trim: str | None = None,
    zip_code: str = DEFAULT_ZIP,
    email: str = DEFAULT_EMAIL,
    max_retries: int = 2,
) -> dict:
    from camoufox.async_api import AsyncCamoufox

    logger.info(
        f"[CarMaxOffer] VIN={vin} miles={mileage} trim={trim} zip={zip_code}"
    )

    result: dict = {
        "offer": None,
        "offer_low": None,
        "offer_high": None,
        "status": "running",
        "error": None,
        "steps": [],
    }

    async with AsyncCamoufox(headless=True, geoip=False) as browser:
        page = await browser.new_page()

        # ── Intercept CarMax's internal offer API response ──────────────
        _intercepted: list[tuple[str, int, int]] = []

        async def _on_response(response):
            try:
                url = response.url
                if any(kw in url for kw in ["/offer", "/appraisal", "/instant", "/value"]):
                    if response.status == 200:
                        try:
                            data = await response.json()
                        except Exception:
                            return
                        text = str(data)
                        offer_str, low, high = _parse_offer_range(text)
                        if offer_str and low and high:
                            _intercepted.append((offer_str, low, high))
                            logger.info(
                                f"[CarMaxOffer] Intercepted offer via API: {offer_str} from {url}"
                            )
            except Exception:
                pass

        page.on("response", _on_response)

        async def _safe_click_btn(pattern: str, timeout: int = 5000) -> bool:
            try:
                loc = page.get_by_role("button", name=re.compile(pattern, re.I)).first
                await loc.wait_for(state="visible", timeout=timeout)
                await loc.scroll_into_view_if_needed()
                await loc.click()
                return True
            except Exception:
                return False

        async def _safe_click_text(text: str, exact: bool = False, timeout: int = 5000) -> bool:
            try:
                if exact:
                    loc = page.get_by_text(text, exact=True).first
                else:
                    loc = page.get_by_text(re.compile(re.escape(text), re.I)).first
                await loc.wait_for(state="visible", timeout=timeout)
                await loc.scroll_into_view_if_needed()
                await loc.click()
                return True
            except Exception:
                return False

        async def _safe_fill(selector: str, value: str, timeout: int = 5000) -> bool:
            try:
                inp = page.locator(selector).first
                await inp.wait_for(state="visible", timeout=timeout)
                await inp.click()
                await page.wait_for_timeout(150)
                await inp.fill(value)
                return True
            except Exception:
                return False

        async def _js_fill(selector: str, value: str) -> bool:
            try:
                await page.evaluate(f"""
                    const inp = document.querySelector('{selector}');
                    if (inp) {{
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        setter.call(inp, '{value}');
                        inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                """)
                return True
            except Exception:
                return False

        try:
            # ── Step 1: Navigate to sell page ──────────────────────────────
            await page.goto(SELL_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            body = await page.inner_text("body")
            low_body = body.lower()
            if any(kw in low_body for kw in ["captcha", "verify you", "robot", "cloudflare"]):
                raise Exception("Bot detection on initial page load. Try again later.")

            result["steps"].append("Loaded sell-my-car page")

            # ── Step 2: Enter VIN ─────────────────────────────────────────
            vin_filled = False
            for selector in [
                "input[placeholder*='VIN' i]",
                "input[name*='vin' i]",
                "input[id*='vin' i]",
                "input[type='text']:visible",
            ]:
                try:
                    inp = page.locator(selector).first
                    await inp.wait_for(state="visible", timeout=3000)
                    await inp.click()
                    await page.wait_for_timeout(150)
                    await inp.fill(vin)
                    val = await inp.input_value()
                    if val.strip().upper() == vin.strip().upper():
                        result["steps"].append(f"VIN entered: {vin}")
                        vin_filled = True
                        break
                except Exception:
                    continue

            if not vin_filled:
                # JS fallback — try common selectors
                for sel in ["input[name='vin']", "input[id='vin']", "input[type='text']"]:
                    if await _js_fill(sel, vin):
                        await page.wait_for_timeout(300)
                        result["steps"].append(f"VIN entered (JS): {vin}")
                        vin_filled = True
                        break

            await page.wait_for_timeout(500)

            # ── Step 3: Enter ZIP code ─────────────────────────────────────
            zip_filled = False
            for selector in [
                "input[placeholder*='ZIP' i]",
                "input[placeholder*='zip code' i]",
                "input[name*='zip' i]",
                "input[id*='zip' i]",
            ]:
                if await _safe_fill(selector, zip_code, timeout=3000):
                    result["steps"].append(f"ZIP entered: {zip_code}")
                    zip_filled = True
                    break

            if not zip_filled:
                await _js_fill("input[placeholder*='zip' i]", zip_code)
                result["steps"].append(f"ZIP entered (JS): {zip_code}")

            await page.wait_for_timeout(500)

            # ── Step 4: Click "Get My Offer" ───────────────────────────────
            clicked_offer = False
            for pattern in [r"get my offer", r"get offer", r"get.+offer", r"^submit$"]:
                if await _safe_click_btn(pattern, timeout=5000):
                    clicked_offer = True
                    break

            if not clicked_offer:
                # Try link/anchor fallback
                try:
                    loc = page.get_by_role("link", name=re.compile(r"get.+offer", re.I)).first
                    await loc.wait_for(state="visible", timeout=3000)
                    await loc.click()
                    clicked_offer = True
                except Exception:
                    pass

            result["steps"].append("Submitted VIN form")

            # Wait for next page
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)

            body = await page.inner_text("body")
            if any(kw in body.lower() for kw in ["captcha", "verify you", "robot", "cloudflare"]):
                raise Exception("Bot detection after VIN submit. Try again later.")

            result["steps"].append(f"Page after VIN: {page.url.split('?')[0].split('/')[-1]}")

            # ── Step 5: Style/Trim selection ───────────────────────────────
            await page.wait_for_timeout(2000)

            # Look for a trim/style dropdown or list of options
            try:
                # Try <select> element first
                sel_loc = page.locator("select").first
                await sel_loc.wait_for(state="visible", timeout=5000)
                options = await sel_loc.locator("option").all_text_contents()
                logger.info(f"[CarMaxOffer] Trim options available: {options}")

                picked_trim = None
                if trim:
                    for opt in options:
                        if trim.lower() in opt.lower() or opt.lower() in trim.lower():
                            picked_trim = opt
                            break

                if not picked_trim and options:
                    # Skip blank/placeholder options
                    for opt in options:
                        if opt.strip() and opt.strip().lower() not in ["select", "choose", "--"]:
                            picked_trim = opt
                            break

                if picked_trim:
                    await sel_loc.select_option(label=picked_trim)
                    result["steps"].append(f"Trim selected: {picked_trim}")
                    await page.wait_for_timeout(1000)

            except Exception:
                # Fallback: try tile/button trim selection
                if trim:
                    for pattern in [trim, trim.upper(), trim.lower()]:
                        try:
                            loc = page.get_by_role("button", name=re.compile(re.escape(pattern), re.I)).first
                            await loc.wait_for(state="visible", timeout=3000)
                            await loc.click()
                            result["steps"].append(f"Trim selected (button): {pattern}")
                            break
                        except Exception:
                            continue

            await page.wait_for_timeout(1000)

            # ── Step 6: "Show standard features" if present ────────────────
            try:
                loc = page.get_by_role("button", name=re.compile(r"show standard features", re.I)).first
                await loc.wait_for(state="visible", timeout=3000)
                await loc.click()
                result["steps"].append("Expanded standard features")
                await page.wait_for_timeout(1000)
            except Exception:
                pass

            # ── Step 7: Navigate to miles/condition step ───────────────────
            try:
                for pattern in [r"miles and condition", r"mileage", r"condition"]:
                    loc = page.get_by_role("button", name=re.compile(pattern, re.I)).first
                    try:
                        await loc.wait_for(state="visible", timeout=3000)
                        await loc.click()
                        result["steps"].append("Navigated to miles/condition step")
                        await page.wait_for_timeout(1500)
                        break
                    except Exception:
                        continue
            except Exception:
                pass

            # ── Step 8: Condition = "Good" ─────────────────────────────────
            await page.wait_for_timeout(1000)
            condition_set = False
            for opt in ["Good", "good"]:
                if await _safe_click_btn(re.escape(opt), timeout=4000):
                    result["steps"].append(f"Condition: {opt}")
                    condition_set = True
                    break
                if await _safe_click_text(opt, exact=True, timeout=4000):
                    result["steps"].append(f"Condition: {opt}")
                    condition_set = True
                    break

            await page.wait_for_timeout(500)

            # ── Step 9: Enter mileage ──────────────────────────────────────
            miles_filled = False
            for role in ["spinbutton", "textbox"]:
                try:
                    inp = page.get_by_role(role).first
                    await inp.wait_for(state="visible", timeout=4000)
                    await inp.triple_click()
                    await inp.fill(str(mileage))
                    result["steps"].append(f"Miles: {mileage}")
                    miles_filled = True
                    break
                except Exception:
                    continue

            if not miles_filled:
                for sel in [
                    "input[placeholder*='miles' i]",
                    "input[placeholder*='mileage' i]",
                    "input[name*='miles' i]",
                    "input[type='number']",
                ]:
                    if await _safe_fill(sel, str(mileage), timeout=3000):
                        result["steps"].append(f"Miles (selector): {mileage}")
                        miles_filled = True
                        break

            await page.wait_for_timeout(500)

            # ── Step 10: Additional Info — "No" for damage/issues ──────────
            for opt in ["No", "None"]:
                try:
                    loc = page.get_by_role("button", name=re.compile(r"^No$", re.I)).first
                    await loc.wait_for(state="visible", timeout=3000)
                    await loc.click()
                    result["steps"].append("Additional info: No")
                    break
                except Exception:
                    if await _safe_click_text(opt, exact=True, timeout=3000):
                        result["steps"].append(f"Additional info: {opt}")
                        break

            await page.wait_for_timeout(500)

            # ── Step 11: Number of keys = "2 or more" ─────────────────────
            for opt in ["2 or more", "2 Or More", "2+"]:
                if await _safe_click_btn(re.escape(opt), timeout=4000):
                    result["steps"].append(f"Keys: {opt}")
                    break
                if await _safe_click_text(opt, exact=True, timeout=3000):
                    result["steps"].append(f"Keys: {opt}")
                    break

            await page.wait_for_timeout(500)

            # ── Step 12: Selling or trading? = "Not sure" ─────────────────
            for opt in ["Not sure", "Not Sure", "Not sure yet"]:
                if await _safe_click_btn(re.escape(opt), timeout=4000):
                    result["steps"].append(f"Selling/trading: {opt}")
                    break
                if await _safe_click_text(opt, exact=True, timeout=3000):
                    result["steps"].append(f"Selling/trading: {opt}")
                    break

            await page.wait_for_timeout(500)

            # ── Step 13: Offer delivery — enter email ──────────────────────
            email_filled = False
            for selector in [
                "input[type='email']",
                "input[placeholder*='email' i]",
                "input[name*='email' i]",
            ]:
                if await _safe_fill(selector, email, timeout=4000):
                    result["steps"].append(f"Email: {email}")
                    email_filled = True
                    break

            if not email_filled:
                try:
                    inp = page.get_by_placeholder(re.compile(r"email", re.I)).first
                    await inp.wait_for(state="visible", timeout=4000)
                    await inp.fill(email)
                    result["steps"].append(f"Email (placeholder): {email}")
                except Exception:
                    pass

            await page.wait_for_timeout(500)

            # ── Step 14: Final "Get Offer" / "See My Offer" button ─────────
            submitted = False
            for pattern in [r"see my offer", r"get offer", r"see offer", r"view offer", r"get.+offer"]:
                if await _safe_click_btn(pattern, timeout=5000):
                    result["steps"].append("Clicked final offer button")
                    submitted = True
                    break

            if not submitted:
                for pattern in [r"continue", r"next", r"submit"]:
                    if await _safe_click_btn(pattern, timeout=4000):
                        result["steps"].append("Clicked continue/submit")
                        break

            # Wait for offer page
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            await page.wait_for_timeout(3000)

            # ── Step 15: Extract offer ─────────────────────────────────────
            # Check intercepted API offer first
            if _intercepted:
                offer_str, low, high = _intercepted[-1]
                result["offer"] = offer_str
                result["offer_low"] = low
                result["offer_high"] = high
                result["steps"].append(f"Offer (API): {offer_str}")
                result["status"] = "completed"
            else:
                body = await page.inner_text("body")
                html = await page.content()

                # Try aria-label with range first (most specific)
                aria_m = re.search(
                    r'aria-label="[^"]*\$([\d,]+)\s*(?:to|–|-)\s*\$([\d,]+)[^"]*"',
                    html,
                    re.I,
                )
                if aria_m:
                    low = int(aria_m.group(1).replace(",", ""))
                    high = int(aria_m.group(2).replace(",", ""))
                    offer_str = f"${low:,}–${high:,}"
                    result["offer"] = offer_str
                    result["offer_low"] = low
                    result["offer_high"] = high
                    result["steps"].append(f"Offer (aria-label): {offer_str}")
                    result["status"] = "completed"
                else:
                    offer_str, low, high = _parse_offer_range(body)
                    if offer_str and ("offer" in body.lower() or "value" in body.lower()):
                        result["offer"] = offer_str
                        result["offer_low"] = low
                        result["offer_high"] = high
                        result["steps"].append(f"Offer: {offer_str}")
                        result["status"] = "completed"

            # Fallback: loop and poll for offer if not found yet
            if result["status"] != "completed":
                for attempt in range(15):
                    await page.wait_for_timeout(1500)
                    body = await page.inner_text("body")
                    html = await page.content()
                    low_body = body.lower()

                    if any(kw in low_body for kw in ["captcha", "verify you", "robot"]):
                        raise Exception("Bot detection mid-flow.")

                    if _intercepted:
                        offer_str, low, high = _intercepted[-1]
                        result["offer"] = offer_str
                        result["offer_low"] = low
                        result["offer_high"] = high
                        result["steps"].append(f"Offer (API late): {offer_str}")
                        result["status"] = "completed"
                        break

                    aria_m = re.search(
                        r'aria-label="[^"]*\$([\d,]+)\s*(?:to|–|-)\s*\$([\d,]+)[^"]*"',
                        html,
                        re.I,
                    )
                    if aria_m:
                        low = int(aria_m.group(1).replace(",", ""))
                        high = int(aria_m.group(2).replace(",", ""))
                        offer_str = f"${low:,}–${high:,}"
                        result["offer"] = offer_str
                        result["offer_low"] = low
                        result["offer_high"] = high
                        result["steps"].append(f"Offer (aria-label late): {offer_str}")
                        result["status"] = "completed"
                        break

                    offer_str, low, high = _parse_offer_range(body)
                    if offer_str and ("offer" in low_body or "value" in low_body):
                        result["offer"] = offer_str
                        result["offer_low"] = low
                        result["offer_high"] = high
                        result["steps"].append(f"Offer (late): {offer_str}")
                        result["status"] = "completed"
                        break

                    logger.debug(
                        f"[CarMaxOffer] no offer yet attempt={attempt} url={page.url.split('?')[0][-60:]}"
                    )

            if result["status"] != "completed":
                result["status"] = "error"
                result["error"] = "Could not retrieve offer — CarMax may have changed their flow."

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error(f"[CarMaxOffer] Error: {e}", exc_info=True)

    logger.info(
        f"[CarMaxOffer] Done: status={result['status']} offer={result['offer']}"
    )

    # Retry on bot-detection block
    block_keywords = ["captcha", "verify", "robot", "bot detection", "cloudflare"]
    if (
        result["status"] == "error"
        and any(kw in (result.get("error") or "").lower() for kw in block_keywords)
        and max_retries > 1
    ):
        wait = (3 - max_retries) * 10 + 10  # 10s → 20s
        logger.info(
            f"[CarMaxOffer] Bot block — retrying in {wait}s ({max_retries - 1} attempts left)"
        )
        await asyncio.sleep(wait)
        return await run_carmax_offer(
            vin, mileage, trim, zip_code, email,
            max_retries=max_retries - 1,
        )

    return result
