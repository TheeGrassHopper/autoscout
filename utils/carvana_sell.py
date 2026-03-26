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


async def _fill_build_page(page, color: str | None, drivetrain: str | None, result: dict,
                           transmission: str | None = None):
    """
    Fill the Carvana /build page which shows all vehicle-build questions at once:
      - Exterior color  (role=combobox custom dropdown — must click to open, then pick option)
      - Drivetrain      (tile buttons: 4WD / RWD / AWD / FWD)
      - Transmission    (tile buttons: Automatic / Manual)
      - Modifications   (tile buttons: No modifications / Modifications)
      - Features        (checkboxes — all optional, skip)
    Then clicks Continue.
    transmission: NHTSA-decoded label e.g. "Automatic, 6-Spd" (used as first candidate).
    """
    await page.wait_for_timeout(800)

    # ── Color: role=combobox, must click to open then pick ─────────────
    try:
        combobox = page.locator("[role='combobox']").first
        await combobox.wait_for(state="visible", timeout=5000)
        await combobox.click()
        await page.wait_for_timeout(600)
        # Pick color from the open dropdown list
        pick = color or "Silver"
        picked = False
        for c in [pick, "Silver", "White", "Black", "Gray", "Blue", "Red"]:
            try:
                opt = page.get_by_role("option", name=c).first
                await opt.wait_for(state="visible", timeout=2000)
                await opt.click()
                result["steps"].append(f"Color: {c}")
                picked = True
                break
            except Exception:
                # fallback: click visible text inside the open dropdown
                try:
                    opt = page.locator(f"[role='listbox'] >> text='{c}'").first
                    await opt.wait_for(state="visible", timeout=1500)
                    await opt.click()
                    result["steps"].append(f"Color: {c}")
                    picked = True
                    break
                except Exception:
                    continue
        if not picked:
            logger.warning("[CarvanaOffer] Could not pick color from combobox")
            # Close the dropdown by pressing Escape
            await page.keyboard.press("Escape")
    except Exception as e:
        logger.warning(f"[CarvanaOffer] Color combobox error: {e}")

    await page.wait_for_timeout(400)

    # ── Drivetrain tile ─────────────────────────────────────────────────
    dt = drivetrain or "4WD"
    for d in [dt, "4WD", "AWD", "FWD", "RWD"]:
        try:
            tile = page.locator(f"[data-testid='tile-{d}']").first
            await tile.wait_for(state="visible", timeout=2000)
            # Only click if not already active
            cls = await tile.get_attribute("class") or ""
            if "active" not in cls:
                await tile.click()
            result["steps"].append(f"Drivetrain: {d}")
            break
        except Exception:
            continue

    await page.wait_for_timeout(300)

    # ── Transmission tile ───────────────────────────────────────────────
    # NHTSA-decoded value is tried first (exact match), then fallbacks
    _trans_candidates = list(dict.fromkeys(filter(None, [
        transmission,
        "Automatic", "Automatic, 6-Spd", "Automatic, 8-Spd", "Automatic, 10-Spd",
    ])))
    for t in _trans_candidates:
        try:
            tile = page.get_by_role("button", name=t).first
            await tile.wait_for(state="visible", timeout=2000)
            cls = await tile.get_attribute("class") or ""
            if "active" not in cls:
                await tile.click()
            result["steps"].append(f"Transmission: {t}")
            break
        except Exception:
            continue

    await page.wait_for_timeout(300)

    # ── Modifications: No modifications ────────────────────────────────
    for opt in ["No modifications", "No Modifications"]:
        try:
            tile = page.get_by_role("button", name=opt).first
            await tile.wait_for(state="visible", timeout=3000)
            cls = await tile.get_attribute("class") or ""
            if "active" not in cls:
                await tile.click()
            result["steps"].append("No modifications")
            break
        except Exception:
            continue

    await page.wait_for_timeout(400)

    # ── Continue ────────────────────────────────────────────────────────
    try:
        btn = page.get_by_role("button", name="Continue").first
        await btn.wait_for(state="visible", timeout=5000)
        await btn.click()
        result["steps"].append("Build page submitted")
        logger.info("[CarvanaOffer] /build page filled and submitted")
    except Exception as e:
        logger.warning(f"[CarvanaOffer] Could not click Continue on /build: {e}")


async def _fill_conditionux_page(page, result: dict):
    """
    Fill the Carvana /conditionux page which shows all 9 vehicle-condition questions at once.
    We click the best (no-damage / like-new) option for each required question, then Continue.
    """
    await page.wait_for_timeout(800)

    # Helper: click the first matching visible element from a list of candidate labels.
    # Carvana uses both <button> elements and styled <div>/<span> tiles — try both.
    async def _click_one(candidates: list[str]) -> str | None:
        for label in candidates:
            # 1st try: role=button (for tile buttons with ARIA role)
            try:
                btn = page.get_by_role("button", name=re.compile(re.escape(label), re.I)).first
                await btn.wait_for(state="visible", timeout=1500)
                await btn.scroll_into_view_if_needed()
                cls = await btn.get_attribute("class") or ""
                if "active" not in cls:
                    await btn.click()
                return label
            except Exception:
                pass
            # 2nd try: get_by_text for div/span/label tiles (no ARIA button role)
            try:
                el = page.get_by_text(re.compile(r"^\s*" + re.escape(label) + r"\s*$", re.I)).first
                await el.wait_for(state="visible", timeout=1500)
                await el.scroll_into_view_if_needed()
                await el.click()
                return label
            except Exception:
                continue
        return None

    # 1. Exterior damage
    label = await _click_one(["No exterior damage"])
    if label:
        result["steps"].append("No exterior damage")

    await page.wait_for_timeout(200)

    # 2. Windshield
    label = await _click_one(["No windshield damage"])
    if label:
        result["steps"].append("No windshield damage")

    await page.wait_for_timeout(200)

    # 3. Moonroof / sunroof
    label = await _click_one(["No moonroof", "Works great"])
    if label:
        result["steps"].append(f"Moonroof: {label}")

    await page.wait_for_timeout(200)

    # 4. Interior damage
    label = await _click_one(["No interior damage", "No damage"])
    if label:
        result["steps"].append(f"Interior: {label}")

    await page.wait_for_timeout(200)

    # 5. Technology system issues
    label = await _click_one(["No technology system issues", "No tech issues"])
    if label:
        result["steps"].append(f"Tech: {label}")

    await page.wait_for_timeout(200)

    # 6. Engine issues
    label = await _click_one(["No engine issues", "No issues"])
    if label:
        result["steps"].append(f"Engine: {label}")

    await page.wait_for_timeout(200)

    # 7. Mechanical or electrical issues
    label = await _click_one(["No mechanical or electrical issues"])
    if label:
        result["steps"].append(f"Mechanical/electrical: {label}")

    await page.wait_for_timeout(200)

    # 8. Drivable
    label = await _click_one(["Drivable"])
    if label:
        result["steps"].append("Drivable")

    await page.wait_for_timeout(200)

    # 9. Overall condition summary (always last on the page)
    label = await _click_one(["Like new", "Pretty great"])
    if label:
        result["steps"].append(f"Condition: {label}")

    await page.wait_for_timeout(400)

    # Continue
    try:
        btn = page.get_by_role("button", name=re.compile(r"^continue$", re.I)).first
        await btn.wait_for(state="visible", timeout=5000)
        await btn.click()
        result["steps"].append("Conditionux page submitted")
        logger.info("[CarvanaOffer] /conditionux page filled and submitted")
    except Exception as e:
        logger.warning(f"[CarvanaOffer] Could not click Continue on /conditionux: {e}")


async def run_carvana_offer(
    vin: str,
    mileage: int,
    title: str = "",
    description: str = "",
    zip_code: str = DEFAULT_ZIP,
    email: str = DEFAULT_EMAIL,
    max_retries: int = 3,
) -> dict:
    """
    Runs the Carvana sell flow using camoufox and returns:
      {"offer": "$X,XXX" | None, "status": "completed"|"error", "error": str|None, "steps": [...]}
    Retries up to max_retries times on Cloudflare blocks (common on datacenter IPs).
    """
    from camoufox.async_api import AsyncCamoufox
    from utils.vin_decode import decode_vin

    # Decode VIN via NHTSA for authoritative drivetrain/transmission
    vin_data = decode_vin(vin)
    color = _detect_color(title, description)
    # Prefer NHTSA drivetrain over regex-from-title
    drivetrain = vin_data.get("drive_type") or _detect_drivetrain(title, description)
    transmission = vin_data.get("transmission")
    logger.info(
        f"[CarvanaOffer] VIN={vin} miles={mileage} color={color} "
        f"drivetrain={drivetrain} transmission={transmission} "
        f"(NHTSA: {vin_data.get('year')} {vin_data.get('make')} {vin_data.get('model')})"
    )

    result: dict = {"offer": None, "status": "running", "error": None, "steps": []}

    async with AsyncCamoufox(headless=True, geoip=False) as browser:
        page = await browser.new_page()

        # ── Intercept Carvana's internal offer API response ─────────────
        # Carvana posts to an internal endpoint that returns the cash offer.
        # Capturing it here is more reliable than parsing the final HTML.
        _intercepted_offer: list[str] = []  # mutable so closure can write

        async def _on_response(response):
            try:
                url = response.url
                # Carvana's offer API paths observed: /offer, /appraisal, /instant-offer
                if any(kw in url for kw in ["/offer", "/appraisal", "/instant-offer", "/getoffer"]):
                    if response.status == 200:
                        try:
                            data = await response.json()
                        except Exception:
                            return
                        # Look for a dollar amount in the JSON
                        text = str(data)
                        m = re.search(r'\b(\d{4,6})\b', text)
                        if m:
                            val = int(m.group(1))
                            if 500 <= val <= 200000:
                                _intercepted_offer.append(f"${val:,}")
                                logger.info(f"[CarvanaOffer] Intercepted offer via API: ${val:,} from {url}")
            except Exception:
                pass

        page.on("response", _on_response)

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
            # The VIN input (#vin) is visible by default on Carvana's sell page.
            # Only click the VIN tab if the input is currently hidden (i.e. the
            # License Plate tab is active instead). Clicking an already-active tab
            # toggles it off and hides the input.
            try:
                vin_already_visible = await page.locator("#vin").first.is_visible()
            except Exception:
                vin_already_visible = False

            if not vin_already_visible:
                for tab_text in ["VIN", "Enter VIN", "By VIN"]:
                    try:
                        # Use [role='tab'] to avoid matching the hidden label element
                        loc = page.locator("[role='tab']").get_by_text(tab_text).first
                        await loc.wait_for(state="visible", timeout=3000)
                        await loc.click()
                        break
                    except Exception:
                        continue
                # Wait for VIN input to appear after tab switch
                try:
                    await page.locator("#vin").first.wait_for(state="visible", timeout=5000)
                except Exception:
                    await page.wait_for_timeout(1000)

            # Fill VIN field
            vin_filled = False
            for selector in ["#vin", "input[label='VIN' i]", "input[type='text']:visible"]:
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
                # Last resort: JavaScript direct set + React synthetic event
                try:
                    await page.evaluate(f"""
                        const inp = document.querySelector('#vin');
                        if (inp) {{
                            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value').set;
                            nativeInputValueSetter.call(inp, '{vin}');
                            inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        }}
                    """)
                    await page.wait_for_timeout(300)
                    val = await page.locator("#vin").first.input_value()
                    if val.strip().upper() == vin.strip().upper():
                        result["steps"].append(f"VIN entered (JS): {vin}")
                        vin_filled = True
                    else:
                        logger.warning(f"[CarvanaOffer] JS VIN set failed, value={val!r}")
                except Exception as e:
                    logger.warning(f"[CarvanaOffer] JS VIN fallback error: {e}")

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

            # ── Step 4: /build page — all vehicle-build questions on one page ──
            # Carvana shows color (combobox), drivetrain tiles, transmission tiles,
            # optional features (checkboxes), and modifications on a single /build page.
            if "/build" in page.url:
                await _fill_build_page(page, color, drivetrain, result, transmission=transmission)
                await page.wait_for_timeout(2000)

            # ── Step 5: Answer subsequent questions in a loop ────────────────
            answered: set = set()

            for attempt in range(30):
                await page.wait_for_timeout(1000)
                body = await page.inner_text("body")
                low = body.lower()
                url = page.url

                if "security verification" in low or "cloudflare" in low:
                    raise Exception("Cloudflare blocked mid-flow.")

                # Check intercepted API offer first (most reliable)
                if _intercepted_offer:
                    result["offer"] = _intercepted_offer[-1]
                    result["steps"].append(f"Offer (API): {result['offer']}")
                    result["status"] = "completed"
                    break

                # Fallback: check page body for offer text
                offer_match = re.search(r'\$\s*[\d,]{4,}', body)
                if offer_match and ("offer" in low or "we'll pay" in low or "carvana will" in low or "/offer" in url):
                    result["offer"] = offer_match.group(0).replace(" ", "")
                    result["steps"].append(f"Offer: {result['offer']}")
                    result["status"] = "completed"
                    break

                # If we land back on /build (e.g. validation failed), retry
                if "/build" in url and "build" not in answered:
                    await _fill_build_page(page, color, drivetrain, result, transmission=transmission)
                    answered.add("build")
                    await page.wait_for_timeout(1500)
                    continue

                # /conditionux — single page with all 9 condition questions
                if "conditionux" in url and "conditionux" not in answered:
                    await _fill_conditionux_page(page, result)
                    answered.add("conditionux")
                    await page.wait_for_timeout(2000)
                    continue

                did_answer = False

                # Condition (old single-question page — keep as fallback)
                if "condition" in low and "condition" not in answered and "conditionux" in answered:
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

                if not did_answer and attempt >= 3:
                    logger.debug(
                        f"[CarvanaOffer] no-answer attempt={attempt} url={url.split('?')[0][-60:]}"
                    )

            # Final offer check
            if result["status"] != "completed":
                # Try intercepted API offer one more time
                if _intercepted_offer:
                    result["offer"] = _intercepted_offer[-1]
                    result["status"] = "completed"
                else:
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

    # Retry on Cloudflare block — datacenter IPs (Railway) get blocked intermittently
    if (result["status"] == "error"
            and "cloudflare" in (result.get("error") or "").lower()
            and max_retries > 1):
        wait = (4 - max_retries) * 8 + 8  # 8s → 16s → 24s
        logger.info(f"[CarvanaOffer] Cloudflare block — retrying in {wait}s ({max_retries-1} attempts left)")
        await asyncio.sleep(wait)
        return await run_carvana_offer(
            vin, mileage, title, description, zip_code, email,
            max_retries=max_retries - 1,
        )

    return result
