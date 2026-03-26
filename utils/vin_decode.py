"""
utils/vin_decode.py
Free VIN decoding via NHTSA vPIC API — no key required.
Returns authoritative vehicle specs: make, model, year, trim, drivetrain, transmission.
"""

import json
import logging
import os
import re
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_DIR = "output/.vin_cache"
_NHTSA_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"

_DRIVE_TYPE_MAP = {
    "4-wheel drive": "4WD",
    "4wd": "4WD",
    "4x4": "4WD",
    "all-wheel drive": "AWD",
    "awd": "AWD",
    "front-wheel drive": "FWD",
    "fwd": "FWD",
    "rear-wheel drive": "RWD",
    "rwd": "RWD",
    "2wd": "FWD",
}


def _cache_path(vin: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"{vin.upper()}.json")


def decode_vin(vin: str) -> dict:
    """
    Decode a VIN using NHTSA vPIC.
    Returns a dict with keys:
      make, model, year, trim, body_class,
      drive_type (e.g. "4WD"), transmission_style, transmission_speeds
    All values are strings or None.
    """
    cache = _cache_path(vin)
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)

    try:
        url = _NHTSA_URL.format(vin=vin.strip().upper())
        req = urllib.request.Request(url, headers={"User-Agent": "AutoScout/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        raw: dict = data.get("Results", [{}])[0]

        drive_raw = (raw.get("DriveType") or "").strip()
        drive_type = _DRIVE_TYPE_MAP.get(drive_raw.lower()) or _parse_drive_type(drive_raw)

        speeds = (raw.get("TransmissionSpeeds") or "").strip()
        trans_style = (raw.get("TransmissionStyle") or "").strip()
        transmission = _build_transmission(trans_style, speeds)

        result = {
            "make": (raw.get("Make") or "").strip().title() or None,
            "model": (raw.get("Model") or "").strip().title() or None,
            "year": (raw.get("ModelYear") or "").strip() or None,
            "trim": (raw.get("Trim") or "").strip() or None,
            "body_class": (raw.get("BodyClass") or "").strip() or None,
            "drive_type": drive_type,
            "transmission": transmission,
            "transmission_style": trans_style or None,
            "transmission_speeds": speeds or None,
        }

        with open(cache, "w") as f:
            json.dump(result, f)

        logger.info(f"[VinDecode] {vin}: {result['year']} {result['make']} {result['model']} "
                    f"trim={result['trim']} drive={result['drive_type']} trans={result['transmission']}")
        return result

    except Exception as e:
        logger.warning(f"[VinDecode] Failed for VIN {vin}: {e}")
        return {
            "make": None, "model": None, "year": None, "trim": None,
            "body_class": None, "drive_type": None, "transmission": None,
            "transmission_style": None, "transmission_speeds": None,
        }


def _parse_drive_type(raw: str) -> Optional[str]:
    """Fallback regex parse of a raw DriveType string."""
    if not raw:
        return None
    low = raw.lower()
    if re.search(r'\b4[wx]d\b|four.wheel', low):
        return "4WD"
    if re.search(r'\bawd\b|all.wheel', low):
        return "AWD"
    if re.search(r'\bfwd\b|front.wheel', low):
        return "FWD"
    if re.search(r'\brwd\b|rear.wheel', low):
        return "RWD"
    return None


def _build_transmission(style: str, speeds: str) -> Optional[str]:
    """Build Carvana-style transmission label e.g. 'Automatic, 6-Spd'."""
    if not style:
        return None
    low = style.lower()
    if "automatic" in low:
        base = "Automatic"
    elif "manual" in low or "mt" in low:
        base = "Manual"
    elif "cvt" in low:
        base = "CVT"
    else:
        base = style.title()

    if speeds and speeds.isdigit():
        return f"{base}, {speeds}-Spd"
    return base
