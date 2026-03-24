"""
utils/carvana_sell.py
Camoufox automation: Carvana "Sell My Car" flow to get a cash offer by VIN.
Uses camoufox (Firefox-based stealth browser) to bypass Cloudflare Bot Fight Mode.
"""

import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

SELL_URL = "https://www.carvana.com/sell-my-car"
DEFAULT_ZIP = "85288"
DEFAULT_EMAIL = "almortada88@gmail.com"

_COLOR_MAP = {
    "white": "White",
    "black": "Black",
    "silver": "Silver",
    "gray": "Gray", "grey": "Gray", "charcoal": "Gray",
    "red": "Red", "maroon": "Red", "burgundy": "Red",
    "blue": "Blue", "navy": "Blue",
    "green": "Green", "teal": "Green",
    "brown": "Brown", "bronze": "Brown",
    "beige": "Beige/Tan", "tan": "Beige/Tan", "champagne": "Beige/Tan",
    "gold": "Gold", "yellow": "Yellow", "orange": "Orange",
    "purple": "Purple",
}

# Carvana color option values (from their <select> element)
_CARVANA_COLORS = [
    "White", "Silver", "Gray", "Black", "Blue", "Red",
    "Brown", "Green", "Beige/Tan", "Gold", "Yellow", "Orange", "Purple",
]

_DRIVETRAIN_PATTERNS = [
    (r'\b4wd\b|\b4x4\b|four.wheel.drive', "4WD"),
    (r'\bawd\b|all.wheel.drive', "AWD"),
    (r'\brwd\b|rear.wheel.drive', "RWD"),
    (r'\bfwd\b|front.wheel.drive', "FWD"),
    (r'\b2wd\b', "FWD"),
]


def _detect_color(title: str, desc: str) -> Optional[str]:
    text = f"{title} {desc}".lower()
    for kw, val in _COLOR_MAP.items():
        if re.search(r'\b' + kw + r'\b', text):
            return val
    return None


def _detect_drivetrain(title: str, desc: str) -> Optional[str]:
    text = f"{title} {desc}".lower()
    for pattern, val in _DRIVETRAIN_PATTERNS:
        if re.search(pattern, text):
            return val
    return None


async def run_carvana_offer(
    vin: str,
    mileage: int,
    title: str = "",
    description: str = "",
    zip_code: str = DEFAULT_ZIP,
    email: str = DEFAULT_EMAIL,
) -> dict:
    """
    Runs the Carvana sell flow using camoufox and returns:
      {"offer": "$X,XXX" | None, "status": "completed"|"error", "error": str|None, "steps": [...]}
    """
    from camoufox.async_api import AsyncCamoufox

    color = _detect_color(title, description)
    drivetrain = _detect_drivetrain(title, description)
    logger.info(f"[CarvanaOffer] VIN={vin} miles={mileage} color={color} drivetrain={drivetrain}")

    result: dict = {"offer": None, "status": "running", "error": None, "steps": []}

    async with AsyncCamoufox(headless=True, geoip=False) as browser:
        page = await browser.new_page()

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

        async def _safe_click_btn(pattern: str, timeout: int = 5000) -> bool:
            try:
                loc = page.get_by_role("button", name=re.compile(pattern, re.I)).first
                await loc.wait_for(state="visible", timeout=timeout)
                await loc.scroll_into_view_if_needed()
                await loc.click()
                return True
            except Exception:
                return False

        async def _advance() -> bool:
            return await _safe_click_btn(r"^continue$|^next$|get my offer|see.+offer", timeout=5000)

        try:
            # ── Step 1: Navigate to sell page ──────────────────────────────
            await page.goto(SELL_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            body = await page.inner_text("body")
            if "security verification" in body.lower() or "cloudflare" in body.lower():
                raise Exception("Cloudflare blocked initial page load. Try again later.")

            result["steps"].append("Loaded sell-my-car page")

            # ── Step 2: Click VIN tab and enter VIN ─────────────────────────
            # Try to click "Enter VIN" tab
            for tab_text in ["VIN", "Enter VIN", "By VIN"]:
                try:
                    loc = page.get_by_text(tab_text, exact=True).first
                    await loc.wait_for(state="visible", timeout=3000)
                    await loc.click()
                    break
                except Exception:
                    continue

            await page.wait_for_timeout(500)

            # Fill VIN field
            for selector in ["#vin", "[name='vin']", "input[placeholder*='VIN' i]", "input[placeholder*='vin' i]"]:
                try:
                    await page.fill(selector, vin, timeout=5000)
                    result["steps"].append(f"VIN entered: {vin}")
                    break
                except Exception:
                    continue

            await page.wait_for_timeout(500)

            # Click submit button
            for btn_pattern in [r"get your offer", r"get offer", r"^submit$", r"^search$"]:
                if await _safe_click_btn(btn_pattern, timeout=5000):
                    break

            result["steps"].append("Submitted VIN")

            # Wait for page to transition
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            await page.wait_for_timeout(3000)

            body = await page.inner_text("body")
            if "security verification" in body.lower() or "cloudflare" in body.lower():
                raise Exception("Cloudflare blocked after VIN submit. Try again later.")

            result["steps"].append(f"Vehicle page loaded: {page.url.split('?')[0].split('/')[-1]}")

            # ── Step 3: Confirm vehicle if prompted ─────────────────────────
            try:
                await _safe_click_btn(r"^continue$", timeout=6000)
                result["steps"].append("Confirmed vehicle")
                await page.wait_for_timeout(2000)
            except Exception:
                pass

            # ── Step 4: Answer questions in a loop ──────────────────────────
            answered: set = set()

            for attempt in range(30):
                await page.wait_for_timeout(1000)
                body = await page.inner_text("body")
                low = body.lower()
                url = page.url

                if "security verification" in low or "cloudflare" in low:
                    raise Exception("Cloudflare blocked mid-flow.")

                # Check for offer
                offer_match = re.search(r'\$\s*[\d,]{4,}', body)
                if offer_match and ("offer" in low or "we'll pay" in low or "carvana will" in low or "/offer" in url):
                    result["offer"] = offer_match.group(0).replace(" ", "")
                    result["steps"].append(f"Offer: {result['offer']}")
                    result["status"] = "completed"
                    break

                did_answer = False

                # Color — dropdown or buttons
                if ("color" in low or "exterior" in low) and "color" not in answered:
                    # Try dropdown first
                    try:
                        select = page.locator("select").first
                        await select.wait_for(state="visible", timeout=3000)
                        pick = color or "Silver"
                        # Try exact match, then fallback colors
                        for c in [pick, "Silver", "White", "Black", "Gray", "Blue", "Red"]:
                            try:
                                await select.select_option(label=c, timeout=2000)
                                answered.add("color")
                                result["steps"].append(f"Color (dropdown): {c}")
                                did_answer = True
                                break
                            except Exception:
                                continue
                    except Exception:
                        pass

                    # Try buttons if dropdown didn't work
                    if "color" not in answered:
                        pick = color or "Silver"
                        for c in [pick, "Silver", "White", "Black", "Gray", "Blue", "Red"]:
                            if await _safe_click_text(c, exact=True, timeout=3000):
                                answered.add("color")
                                result["steps"].append(f"Color (button): {c}")
                                did_answer = True
                                break

                # Drivetrain — buttons (FWD, AWD, RWD, 4WD)
                elif "drivetrain" in low and "drivetrain" not in answered:
                    dt = drivetrain or "FWD"
                    for d in [dt, "FWD", "AWD", "4WD", "RWD", "Front Wheel Drive", "All Wheel Drive"]:
                        if await _safe_click_text(d, exact=True, timeout=3000):
                            answered.add("drivetrain")
                            result["steps"].append(f"Drivetrain: {d}")
                            did_answer = True
                            break

                # Modifications — click "No modifications"
                elif "modification" in low and "modification" not in answered:
                    for opt in ["No modifications", "No Modifications", "No"]:
                        if await _safe_click_text(opt, exact=False, timeout=4000):
                            answered.add("modification")
                            result["steps"].append("No modifications")
                            did_answer = True
                            break

                # Condition
                elif "condition" in low and "condition" not in answered:
                    for opt in ["Just Okay", "Good", "Fair"]:
                        if await _safe_click_text(opt, timeout=4000):
                            answered.add("condition")
                            result["steps"].append(f"Condition: {opt}")
                            did_answer = True
                            break

                # Mileage / Odometer
                elif ("miles" in low or "mileage" in low or "odometer" in low) and "miles" not in answered:
                    try:
                        for role in ["spinbutton", "textbox"]:
                            try:
                                inp = page.get_by_role(role).first
                                await inp.wait_for(state="visible", timeout=4000)
                                await inp.triple_click()
                                await inp.fill(str(mileage))
                                answered.add("miles")
                                result["steps"].append(f"Miles: {mileage}")
                                did_answer = True
                                break
                            except Exception:
                                continue
                    except Exception:
                        pass

                # Accidents
                elif "accident" in low and "accident" not in answered:
                    for opt in ["No Accidents", "No accidents", "No"]:
                        if await _safe_click_text(opt, exact=False, timeout=4000):
                            answered.add("accident")
                            result["steps"].append("No accidents")
                            did_answer = True
                            break

                # Smoked
                elif "smoked" in low and "smoked" not in answered:
                    for opt in ["Not Smoked In", "No"]:
                        if await _safe_click_text(opt, exact=False, timeout=4000):
                            answered.add("smoked")
                            result["steps"].append("Not smoked in")
                            did_answer = True
                            break

                # Tires
                elif "tires" in low and "tires" not in answered:
                    for opt in ["None", "0"]:
                        if await _safe_click_text(opt, exact=True, timeout=4000):
                            answered.add("tires")
                            result["steps"].append("No tires replaced")
                            did_answer = True
                            break

                # Keys
                elif "keys" in low and "key" not in answered:
                    for opt in ["1 Key", "1"]:
                        if await _safe_click_text(opt, exact=True, timeout=4000):
                            answered.add("key")
                            result["steps"].append("1 key")
                            did_answer = True
                            break

                # Location / ZIP
                elif ("located" in low or ("zip" in low and "location" not in answered)):
                    try:
                        z = page.get_by_placeholder(re.compile(r"zip|postal", re.I)).first
                        await z.wait_for(state="visible", timeout=4000)
                        await z.triple_click()
                        await z.fill(zip_code)
                        answered.add("location")
                        result["steps"].append(f"ZIP: {zip_code}")
                        did_answer = True
                    except Exception:
                        pass

                # Loan / Lease
                elif ("loan" in low or "lease" in low) and "loan" not in answered:
                    for opt in ["Neither", "No loan", "No"]:
                        if await _safe_click_text(opt, exact=True, timeout=4000):
                            answered.add("loan")
                            result["steps"].append("No loan/lease")
                            did_answer = True
                            break

                # Trade vs Sell
                elif "trade" in low and "sell_trade" not in answered:
                    for opt in ["Sell", "Just Sell"]:
                        if await _safe_click_text(opt, exact=True, timeout=4000):
                            answered.add("sell_trade")
                            result["steps"].append("Sell")
                            did_answer = True
                            break

                # Email
                elif "email" in low and "email" not in answered:
                    try:
                        em = page.get_by_placeholder(re.compile(r"email", re.I)).first
                        await em.wait_for(state="visible", timeout=4000)
                        await em.fill(email)
                        answered.add("email")
                        result["steps"].append(f"Email: {email}")
                        did_answer = True
                    except Exception:
                        pass

                # Always try to advance
                await _advance()

                if not did_answer and attempt >= 5:
                    logger.debug(f"[CarvanaOffer] No answer on attempt {attempt}, URL: {url}")

            # Final offer check
            if result["status"] != "completed":
                body = await page.inner_text("body")
                m = re.search(r'\$\s*[\d,]{4,}', body)
                if m and ("offer" in body.lower() or "we'll pay" in body.lower()):
                    result["offer"] = m.group(0).replace(" ", "")
                    result["status"] = "completed"
                else:
                    result["status"] = "error"
                    result["error"] = "Could not retrieve offer — Carvana may have changed their flow."

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error(f"[CarvanaOffer] Error: {e}", exc_info=True)

    logger.info(f"[CarvanaOffer] Done: status={result['status']} offer={result['offer']}")
    return result
