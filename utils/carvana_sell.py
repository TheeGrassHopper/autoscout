"""
utils/carvana_sell.py
Playwright automation: Carvana "Sell My Car" flow to get a cash offer by VIN.

Fills in all form steps based on listing data.
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
    "blue": "Blue", "navy": "Blue", "cobalt": "Blue",
    "green": "Green", "teal": "Green",
    "brown": "Brown", "bronze": "Brown",
    "beige": "Beige/Tan", "tan": "Beige/Tan", "champagne": "Beige/Tan", "sand": "Beige/Tan",
    "gold": "Gold", "yellow": "Yellow",
    "orange": "Orange",
    "purple": "Purple", "violet": "Purple",
}

_DRIVETRAIN_PATTERNS = [
    (r'\b4wd\b|\b4x4\b|four.wheel.drive', "4 Wheel Drive"),
    (r'\bawd\b|all.wheel.drive', "All Wheel Drive"),
    (r'\brwd\b|rear.wheel.drive', "Rear Wheel Drive"),
    (r'\bfwd\b|front.wheel.drive', "Front Wheel Drive"),
    (r'\b2wd\b', "2 Wheel Drive"),
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
    title: str,
    description: str,
    zip_code: str = DEFAULT_ZIP,
    email: str = DEFAULT_EMAIL,
) -> dict:
    """
    Runs the Carvana sell flow and returns:
      {"offer": "$X,XXX" | None, "status": "completed"|"error", "error": str|None, "steps": [...]}
    """
    from playwright.async_api import async_playwright, TimeoutError as PwTimeout

    color = _detect_color(title, description)
    drivetrain = _detect_drivetrain(title, description)

    logger.info(f"[CarvanaOffer] VIN={vin} miles={mileage} color={color} drivetrain={drivetrain}")

    result: dict = {"offer": None, "status": "running", "error": None, "steps": []}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()

        async def _click_text(text: str, exact=False, timeout=8000):
            loc = page.get_by_text(text, exact=exact).first
            await loc.wait_for(state="visible", timeout=timeout)
            await loc.scroll_into_view_if_needed()
            await loc.click()

        async def _click_btn(pattern: str, timeout=8000):
            loc = page.get_by_role("button", name=re.compile(pattern, re.I)).first
            await loc.wait_for(state="visible", timeout=timeout)
            await loc.scroll_into_view_if_needed()
            await loc.click()

        async def _try_click(*texts, exact=False, timeout=5000) -> bool:
            for t in texts:
                try:
                    await _click_text(t, exact=exact, timeout=timeout)
                    return True
                except Exception:
                    continue
            return False

        async def _advance():
            """Try to advance to next page."""
            for pattern in [r"continue$", r"next$", r"get my offer", r"see.+offer", r"submit"]:
                try:
                    await _click_btn(pattern, timeout=4000)
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(1500)
                    return True
                except Exception:
                    continue
            return False

        try:
            # ── 1. Load sell page ──────────────────────────────────────────
            await page.goto(SELL_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            result["steps"].append("Loaded Carvana sell page")

            # ── 2. Switch to VIN tab ───────────────────────────────────────
            await _try_click("VIN", "Enter VIN", "By VIN", exact=True, timeout=6000)
            result["steps"].append("Selected VIN tab")
            await page.wait_for_timeout(600)

            # ── 3. Enter VIN ───────────────────────────────────────────────
            vin_input = (
                page.get_by_placeholder(re.compile(r"vin", re.I)).first
                or page.locator("input[name*='vin' i]").first
            )
            await vin_input.wait_for(state="visible", timeout=6000)
            await vin_input.fill(vin)
            result["steps"].append(f"Entered VIN: {vin}")

            # ── 4. Enter ZIP if visible ────────────────────────────────────
            try:
                zip_input = page.get_by_placeholder(re.compile(r"zip", re.I)).first
                await zip_input.wait_for(state="visible", timeout=3000)
                await zip_input.fill(zip_code)
                result["steps"].append(f"Entered ZIP: {zip_code}")
            except Exception:
                pass  # ZIP field may appear later

            # ── 5. Submit VIN ──────────────────────────────────────────────
            await _click_btn(r"get.+offer|check.+value", timeout=6000)
            result["steps"].append("Clicked Get Your Offer")
            await page.wait_for_load_state("networkidle", timeout=25000)
            await page.wait_for_timeout(2500)

            # ── 6. Vehicle confirmation — click Continue ───────────────────
            try:
                await _click_btn(r"^continue$", timeout=8000)
                result["steps"].append("Confirmed vehicle, clicked Continue")
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)
            except Exception:
                logger.debug("No vehicle confirmation Continue button")

            # ── 7. Question loop (up to 25 pages) ─────────────────────────
            answered: set[str] = set()

            for attempt in range(25):
                await page.wait_for_timeout(800)
                body_text = await page.inner_text("body")
                low = body_text.lower()

                # ── Check if offer is already on the page ──────────────────
                offer_match = re.search(r'\$\s*[\d,]{4,}', body_text)
                if offer_match and "offer" in low:
                    result["offer"] = offer_match.group(0).replace(" ", "")
                    result["steps"].append(f"Got offer: {result['offer']}")
                    result["status"] = "completed"
                    break

                did_answer = False

                # Color
                if "color" in low and "color" not in answered:
                    pick = color or "Silver"
                    for c in [pick, "Silver", "White", "Black", "Gray", "Blue", "Red"]:
                        if await _try_click(c, exact=True, timeout=3000):
                            answered.add("color")
                            result["steps"].append(f"Color: {c}")
                            did_answer = True
                            break

                # Drivetrain
                elif "drivetrain" in low and "drivetrain" not in answered:
                    dt = drivetrain or "Front Wheel Drive"
                    for d in [dt, "Front Wheel Drive", "All Wheel Drive", "4 Wheel Drive", "Rear Wheel Drive"]:
                        if await _try_click(d, exact=True, timeout=3000):
                            answered.add("drivetrain")
                            result["steps"].append(f"Drivetrain: {d}")
                            did_answer = True
                            break

                # Modifications
                elif "modification" in low and "modification" not in answered:
                    if await _try_click("No", "No Modifications", exact=False, timeout=4000):
                        answered.add("modification")
                        result["steps"].append("No modifications")
                        did_answer = True

                # Condition
                elif "condition" in low and "condition" not in answered:
                    if await _try_click("Just Okay", timeout=4000):
                        answered.add("condition")
                        result["steps"].append("Condition: Just Okay")
                        did_answer = True

                # Mileage input
                elif ("miles" in low or "mileage" in low or "odometer" in low) and "miles" not in answered:
                    try:
                        mi_input = page.get_by_role("spinbutton").first
                        if not await mi_input.count():
                            mi_input = page.get_by_role("textbox").first
                        await mi_input.wait_for(state="visible", timeout=4000)
                        await mi_input.triple_click()
                        await mi_input.fill(str(mileage))
                        answered.add("miles")
                        result["steps"].append(f"Mileage: {mileage}")
                        did_answer = True
                    except Exception:
                        pass

                # Accident
                elif "accident" in low and "accident" not in answered:
                    if await _try_click("No Accidents", "No", exact=False, timeout=4000):
                        answered.add("accident")
                        result["steps"].append("No accidents")
                        did_answer = True

                # Smoked
                elif "smoked" in low and "smoked" not in answered:
                    if await _try_click("Not Smoked In", "No", exact=False, timeout=4000):
                        answered.add("smoked")
                        result["steps"].append("Not smoked in")
                        did_answer = True

                # Tires
                elif "tires" in low and "tires" not in answered:
                    if await _try_click("None", "0", exact=True, timeout=4000):
                        answered.add("tires")
                        result["steps"].append("No tires replaced")
                        did_answer = True

                # Keys
                elif "keys" in low and "key" not in answered:
                    if await _try_click("1 Key", "1", exact=True, timeout=4000):
                        answered.add("key")
                        result["steps"].append("1 key")
                        did_answer = True

                # ZIP / Location
                elif ("located" in low or "zip" in low) and "location" not in answered:
                    try:
                        z = page.get_by_placeholder(re.compile(r"zip|postal", re.I)).first
                        await z.wait_for(state="visible", timeout=4000)
                        await z.triple_click()
                        await z.fill(zip_code)
                        answered.add("location")
                        result["steps"].append(f"Location: {zip_code}")
                        did_answer = True
                    except Exception:
                        pass

                # Loan / Lease
                elif ("loan" in low or "lease" in low) and "loan" not in answered:
                    if await _try_click("Neither", exact=True, timeout=4000):
                        answered.add("loan")
                        result["steps"].append("No loan or lease")
                        did_answer = True

                # Sell or Trade
                elif "trade" in low and "sell_trade" not in answered:
                    if await _try_click("Sell", exact=True, timeout=4000):
                        answered.add("sell_trade")
                        result["steps"].append("Selling (not trading)")
                        did_answer = True

                # Email
                elif "email" in low and "email" not in answered:
                    try:
                        em = page.get_by_placeholder(re.compile(r"email", re.I)).first
                        if not await em.count():
                            em = page.get_by_role("textbox", name=re.compile(r"email", re.I)).first
                        await em.wait_for(state="visible", timeout=4000)
                        await em.fill(email)
                        answered.add("email")
                        result["steps"].append(f"Email: {email}")
                        did_answer = True
                    except Exception:
                        pass

                # Advance to next page
                advanced = await _advance()
                if not advanced and not did_answer:
                    logger.warning(f"[CarvanaOffer] Stuck on attempt {attempt} — page content snippet: {body_text[:200]}")
                    if attempt >= 3:
                        break

            # Final offer check if loop didn't catch it
            if result["status"] != "completed":
                body_text = await page.inner_text("body")
                offer_match = re.search(r'\$\s*[\d,]{4,}', body_text)
                if offer_match:
                    result["offer"] = offer_match.group(0).replace(" ", "")
                    result["status"] = "completed"
                    result["steps"].append(f"Final offer found: {result['offer']}")
                else:
                    result["status"] = "error"
                    result["error"] = "Could not retrieve offer — Carvana may have changed their flow or blocked automation."

        except PwTimeout as e:
            result["status"] = "error"
            result["error"] = f"Timed out: {e}"
            logger.error(f"[CarvanaOffer] Timeout: {e}")
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error(f"[CarvanaOffer] Error: {e}", exc_info=True)
        finally:
            await browser.close()

    logger.info(f"[CarvanaOffer] Done: status={result['status']} offer={result['offer']}")
    return result
