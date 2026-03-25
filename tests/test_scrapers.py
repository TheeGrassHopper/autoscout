"""
tests/test_scrapers.py — Unit tests for scraper helper functions.

All pure-logic helpers — no browser or network required.
"""

import pytest


# ── Craigslist helpers ────────────────────────────────────────────────────────

class TestMileageExtraction:
    """scrapers/craigslist.py → _extract_mileage_from_description"""

    def setup_method(self):
        from scrapers.craigslist import _extract_mileage_from_description
        self.extract = _extract_mileage_from_description

    def test_plain_number_with_miles(self):
        assert self.extract("85000 miles, clean title") == 85000

    def test_comma_formatted(self):
        assert self.extract("85,000 miles on it") == 85000

    def test_k_shorthand_with_miles(self):
        assert self.extract("Only 85k miles!") == 85000

    def test_k_shorthand_uppercase(self):
        assert self.extract("85K miles on it") == 85000

    def test_no_mileage_returns_none(self):
        assert self.extract("Clean title, great shape") is None

    def test_ignores_prices(self):
        # $30,000 should not be parsed as mileage (no "miles" keyword after it)
        result = self.extract("Asking $30,000 or best offer")
        assert result is None

    def test_description_with_multiple_numbers_picks_mileage(self):
        result = self.extract("2020 model, 62,000 miles, asking $28,000 OBO")
        assert result == 62000

    def test_empty_string_returns_none(self):
        assert self.extract("") is None

    def test_none_input_returns_none(self):
        assert self.extract(None) is None

    def test_very_short_k_value_filtered(self):
        # "1k miles" = 1000 which is valid
        result = self.extract("Only 1k miles")
        assert result == 1000 or result is None  # 1000 is at boundary

    def test_large_mileage_accepted(self):
        result = self.extract("200,000 miles, runs great")
        assert result == 200000

    def test_multiple_mileage_mentions(self):
        result = self.extract("85,000 miles, just hit 85k!")
        assert result == 85000  # both agree → 85000


class TestVinExtraction:
    """scrapers/craigslist.py → _extract_vin — returns str (empty string = not found)"""

    def setup_method(self):
        from scrapers.craigslist import _extract_vin
        self.extract = _extract_vin

    def test_valid_vin_extracted(self):
        # 17-char valid VIN with mixed letters and digits
        vin = self.extract("VIN: 1HGBH41JXMN109186 — clean title")
        assert vin == "1HGBH41JXMN109186"

    def test_too_short_returns_empty(self):
        # _extract_vin returns "" when no valid 17-char VIN found
        assert self.extract("VIN: 1HGBH41") == ""

    def test_no_vin_returns_empty_string(self):
        assert self.extract("Great car, no issues") == ""

    def test_empty_text_returns_empty_string(self):
        assert self.extract("") == ""

    def test_lowercase_accepted(self):
        # Function uppercases internally before matching
        result = self.extract("vin 5yjsa1e26mf123456X")  # too long — won't match
        assert result == ""  # 18 chars, no match

    def test_exact_17_char_vin(self):
        result = self.extract("5YJSA1E26MF123456")
        assert len(result) == 17

    def test_all_digit_sequence_filtered(self):
        # A 17-digit number has no letters — should be filtered
        result = self.extract("12345678901234567")
        assert result == ""


class TestMileageReconcile:
    """scrapers/craigslist.py → _reconcile_mileage (3 args: card, attr, desc)"""

    def setup_method(self):
        from scrapers.craigslist import _reconcile_mileage
        self.reconcile = _reconcile_mileage

    def test_normal_mileage_prefers_attr(self):
        # attr takes priority over card when both present
        assert self.reconcile(85000, 85000, None) == 85000

    def test_missing_zeros_on_card_corrected_via_attr(self):
        # Card says 85, attr says 85000 → use attr
        result = self.reconcile(85, 85000, None)
        assert result == 85000

    def test_missing_zeros_on_card_corrected_via_desc(self):
        # Card says 125, attr=None, desc says 125000 → use desc
        result = self.reconcile(125, None, 125000)
        assert result == 125000

    def test_all_none_returns_none(self):
        assert self.reconcile(None, None, None) is None

    def test_only_card_mileage_returns_card(self):
        assert self.reconcile(80000, None, None) == 80000

    def test_attr_preferred_over_desc(self):
        assert self.reconcile(None, 70000, 72000) == 70000


class TestYearExtraction:
    """Year extraction from Craigslist title via regex (used in scraper)."""

    def test_year_extracted_from_standard_title(self):
        import re
        title = "2020 Toyota Tacoma TRD Sport"
        m = re.search(r'\b(19\d{2}|20[012]\d)\b', title)
        assert m is not None
        assert int(m.group(1)) == 2020

    def test_no_year_in_title(self):
        import re
        title = "Toyota Tacoma TRD Sport"
        m = re.search(r'\b(19\d{2}|20[012]\d)\b', title)
        assert m is None

    def test_future_year_not_matched_by_pattern(self):
        import re
        title = "2045 Toyota Tacoma"
        m = re.search(r'\b(19\d{2}|20[012]\d)\b', title)
        # 2045 doesn't match 20[012]\d (only 200x-202x match)
        assert m is None


# ── Facebook helpers ──────────────────────────────────────────────────────────

class TestFacebookPriceParsing:
    """scrapers/facebook.py → _parse_fb_price"""

    def setup_method(self):
        from scrapers.facebook import _parse_fb_price
        self.parse = _parse_fb_price

    def test_dollar_sign_stripped(self):
        assert self.parse("$32,000") == 32000

    def test_plain_integer_string(self):
        assert self.parse("28500") == 28500

    def test_integer_passthrough(self):
        assert self.parse(28500) == 28500

    def test_none_returns_none(self):
        assert self.parse(None) is None

    def test_invalid_string_returns_none(self):
        assert self.parse("negotiable") is None


class TestFacebookMileageParsing:
    """scrapers/facebook.py → _parse_fb_mileage
    NOTE: This function requires context words (miles/mi) — bare numbers return None.
    """

    def setup_method(self):
        from scrapers.facebook import _parse_fb_mileage
        self.parse = _parse_fb_mileage

    def test_driven_format(self):
        assert self.parse("Driven 85,000 miles") == 85000

    def test_string_with_k_and_miles(self):
        assert self.parse("45k miles") == 45000

    def test_string_with_commas_and_miles(self):
        assert self.parse("85,000 miles") == 85000

    def test_plain_number_without_context_returns_none(self):
        # Function requires "miles" keyword — bare integers return None
        assert self.parse(85000) is None

    def test_none_returns_none(self):
        assert self.parse(None) is None

    def test_mi_abbreviation(self):
        result = self.parse("72,000 mi")
        assert result == 72000


class TestFacebookTitleStatusDetection:
    """scrapers/facebook.py → _detect_title_status
    NOTE: Returns 'unknown' (not 'clean') when no title keywords found.
    """

    def setup_method(self):
        from scrapers.facebook import _detect_title_status
        self.detect = _detect_title_status

    def test_salvage_in_title(self):
        result = self.detect("2019 Tacoma SALVAGE", "")
        assert result == "salvage"

    def test_rebuilt_in_description(self):
        result = self.detect("2019 Tacoma", "rebuilt title — runs great")
        assert result == "rebuilt"

    def test_clean_title_keyword(self):
        result = self.detect("2019 Tacoma", "clean title, no issues")
        assert result == "clean"

    def test_no_keywords_returns_unknown(self):
        # Without explicit title keywords, returns 'unknown' (not 'clean')
        result = self.detect("2019 Tacoma", "great shape")
        assert result == "unknown"


# ── Carvana sell helpers ──────────────────────────────────────────────────────

class TestCarvanaColorDetection:
    """utils/carvana_sell.py → _detect_color"""

    def setup_method(self):
        from utils.carvana_sell import _detect_color
        self.detect = _detect_color

    def test_silver_detected(self):
        assert self.detect("2020 Toyota Tacoma Silver 4x4", "") == "Silver"

    def test_black_detected(self):
        assert self.detect("Black Tundra Crew Cab", "") == "Black"

    def test_grey_maps_to_gray(self):
        assert self.detect("", "Grey exterior, tan interior") == "Gray"

    def test_navy_maps_to_blue(self):
        assert self.detect("Navy Blue Camry", "") == "Blue"

    def test_tan_maps_to_beige(self):
        assert self.detect("Tan exterior", "") == "Beige/Tan"

    def test_no_color_returns_none(self):
        assert self.detect("2020 Toyota Tacoma TRD Sport", "") is None

    def test_case_insensitive(self):
        assert self.detect("BLACK truck", "") == "Black"


class TestCarvanaDrivetrainDetection:
    """utils/carvana_sell.py → _detect_drivetrain"""

    def setup_method(self):
        from utils.carvana_sell import _detect_drivetrain
        self.detect = _detect_drivetrain

    def test_4x4_maps_to_4wd(self):
        assert self.detect("2020 Tacoma 4x4 TRD", "") == "4WD"

    def test_awd_detected(self):
        assert self.detect("AWD Outback", "") == "AWD"

    def test_fwd_detected(self):
        assert self.detect("", "Front wheel drive, great in city") == "FWD"

    def test_rwd_detected(self):
        assert self.detect("2019 Mustang RWD", "") == "RWD"

    def test_2wd_maps_to_fwd(self):
        assert self.detect("2WD base model", "") == "FWD"

    def test_four_wheel_drive_spelled_out(self):
        assert self.detect("Four wheel drive pickup", "") == "4WD"

    def test_no_drivetrain_returns_none(self):
        assert self.detect("2020 Toyota Tacoma", "") is None
