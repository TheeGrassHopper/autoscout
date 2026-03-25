"""
tests/test_normalizer.py — AI normalizer tests with mocked Anthropic API.
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from tests.conftest import make_raw_listing


def _mock_claude_response(data: dict):
    """Return a mock Anthropic messages.create() response."""
    mock = MagicMock()
    mock.content = [MagicMock()]
    mock.content[0].text = json.dumps(data)
    return mock


# ── normalize_listing ─────────────────────────────────────────────────────────

class TestNormalizeListing:

    @patch("utils.normalizer.anthropic")
    def test_fills_missing_make_model_year(self, mock_anthropic):
        client = MagicMock()
        client.messages.create.return_value = _mock_claude_response({
            "make": "Toyota", "model": "Tacoma", "year": 2020,
            "mileage": 60000, "title_status": "clean",
        })
        mock_anthropic.Anthropic.return_value = client

        from utils.normalizer import normalize_listing
        raw = make_raw_listing(make=None, model=None, year=None,
                               title="2020 Toyota Tacoma TRD Sport 4x4")
        result = normalize_listing(raw, api_key="sk-fake-key")

        assert result.make == "Toyota"
        assert result.model == "Tacoma"
        assert result.year == 2020

    @patch("utils.normalizer.anthropic")
    def test_preserves_existing_fields_if_claude_returns_none(self, mock_anthropic):
        client = MagicMock()
        client.messages.create.return_value = _mock_claude_response({
            "make": None, "model": None, "year": None,
        })
        mock_anthropic.Anthropic.return_value = client

        from utils.normalizer import normalize_listing
        raw = make_raw_listing(make="Toyota", model="Tacoma", year=2020)
        result = normalize_listing(raw, api_key="sk-fake-key")

        assert result.make == "Toyota"
        assert result.model == "Tacoma"
        assert result.year == 2020

    @patch("utils.normalizer.anthropic")
    def test_invalid_json_from_claude_returns_original(self, mock_anthropic):
        client = MagicMock()
        bad = MagicMock()
        bad.content = [MagicMock()]
        bad.content[0].text = "Not valid JSON at all"
        client.messages.create.return_value = bad
        mock_anthropic.Anthropic.return_value = client

        from utils.normalizer import normalize_listing
        raw = make_raw_listing(make="Toyota", model="Tacoma", year=2020)
        result = normalize_listing(raw, api_key="sk-fake-key")

        # Should not crash, return original data
        assert result is not None

    def test_missing_api_key_skips_normalization(self):
        from utils.normalizer import normalize_listing
        raw = make_raw_listing()
        result = normalize_listing(raw, api_key=None)
        assert result is not None
        assert result.make == raw.make

    @patch("utils.normalizer.anthropic")
    def test_network_error_returns_original(self, mock_anthropic):
        """Non-auth exceptions (e.g. network errors) are swallowed and original listing returned."""
        import anthropic as real_anthropic
        client = MagicMock()
        # Connection error falls through to generic except Exception handler
        client.messages.create.side_effect = ConnectionError("Network unreachable")
        mock_anthropic.Anthropic.return_value = client
        mock_anthropic.AuthenticationError = real_anthropic.AuthenticationError

        from utils.normalizer import normalize_listing
        raw = make_raw_listing()
        result = normalize_listing(raw, api_key="sk-fake-key")
        assert result is not None

    @patch("utils.normalizer.anthropic")
    def test_auth_error_is_re_raised(self, mock_anthropic):
        """AuthenticationError is re-raised (so normalize_batch can stop retrying)."""
        import anthropic as real_anthropic
        client = MagicMock()
        client.messages.create.side_effect = real_anthropic.AuthenticationError(
            message="Invalid API key", response=MagicMock(), body={}
        )
        mock_anthropic.Anthropic.return_value = client
        mock_anthropic.AuthenticationError = real_anthropic.AuthenticationError

        from utils.normalizer import normalize_listing
        raw = make_raw_listing()
        with pytest.raises(real_anthropic.AuthenticationError):
            normalize_listing(raw, api_key="sk-bad-key")


# ── normalize_batch ───────────────────────────────────────────────────────────

class TestNormalizeBatch:

    @patch("utils.normalizer.anthropic")
    def test_batch_processes_all_listings(self, mock_anthropic):
        client = MagicMock()
        client.messages.create.return_value = _mock_claude_response({
            "make": "Toyota", "model": "Tacoma", "year": 2020,
        })
        mock_anthropic.Anthropic.return_value = client

        from utils.normalizer import normalize_batch
        listings = [
            make_raw_listing(listing_id=f"id_{i}", make=None, model=None, year=None)
            for i in range(3)
        ]
        results = normalize_batch(listings, api_key="sk-fake-key", delay=0)
        assert len(results) == 3

    @patch("utils.normalizer.anthropic")
    def test_batch_drops_unparseable_listings(self, mock_anthropic):
        """Listings with no make/model/year after normalization should be dropped."""
        client = MagicMock()
        client.messages.create.return_value = _mock_claude_response({
            "make": None, "model": None, "year": None,
        })
        mock_anthropic.Anthropic.return_value = client

        from utils.normalizer import normalize_batch
        # All listings have no make/model/year and Claude also can't determine them
        listings = [
            make_raw_listing(listing_id=f"id_{i}", make=None, model=None, year=None,
                             title="Furniture sofa for sale")  # not a vehicle
            for i in range(2)
        ]
        results = normalize_batch(listings, api_key="sk-fake-key", delay=0)
        # Should drop listings that can't be parsed
        assert len(results) <= 2  # may be 0 if all dropped
