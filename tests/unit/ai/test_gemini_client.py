"""Unit tests for gmrs_tty.ai.gemini_client."""
import json
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from gmrs_tty.ai.gemini_client import GeminiError, generate_journal


def _make_response(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode()
    mock = MagicMock()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.read.return_value = body
    return mock


_VALID_RESPONSE = {
    "candidates": [
        {
            "content": {
                "parts": [
                    {"text": json.dumps({
                        "title": "Morning Check-in",
                        "callsigns_locations": [{"callsign": "WSLZ233", "location": "Denver, CO"}],
                        "summary": "Operators exchanged radio checks.",
                    })}
                ]
            }
        }
    ]
}


class TestGenerateJournal:
    def test_returns_title_and_summary(self):
        with patch("urllib.request.urlopen", return_value=_make_response(_VALID_RESPONSE)):
            result = generate_journal("key", "transcript text", ["WSLZ233"], "2026-01-01 12:00:00")
        assert result["title"] == "Morning Check-in"
        assert "radio checks" in result["summary"]
        assert result["callsigns_locations"] == [{"callsign": "WSLZ233", "location": "Denver, CO"}]

    def test_raises_on_http_error(self):
        err = urllib.error.HTTPError(
            url="", code=403, msg="Forbidden", hdrs={}, fp=BytesIO(b"bad key")
        )
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(GeminiError, match="403"):
                generate_journal("bad_key", "t", [], "ts")

    def test_raises_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            with pytest.raises(GeminiError, match="timeout"):
                generate_journal("key", "t", [], "ts")

    def test_raises_when_response_missing_keys(self):
        bad_response = {
            "candidates": [
                {"content": {"parts": [{"text": json.dumps({"only_title": "x"})}]}}
            ]
        }
        with patch("urllib.request.urlopen", return_value=_make_response(bad_response)):
            with pytest.raises(GeminiError, match="missing required keys"):
                generate_journal("key", "t", [], "ts")

    def test_raises_when_callsigns_locations_not_a_list(self):
        bad_response = {
            "candidates": [{"content": {"parts": [{"text": json.dumps({
                "title": "x",
                "summary": "y",
                "callsigns_locations": None,
            })}]}}]
        }
        with patch("urllib.request.urlopen", return_value=_make_response(bad_response)):
            with pytest.raises(GeminiError, match="callsigns_locations must be an array"):
                generate_journal("key", "t", [], "ts")

    def test_raises_when_response_text_not_json(self):
        bad_response = {
            "candidates": [
                {"content": {"parts": [{"text": "not json at all"}]}}
            ]
        }
        with patch("urllib.request.urlopen", return_value=_make_response(bad_response)):
            with pytest.raises(GeminiError):
                generate_journal("key", "t", [], "ts")

    def test_raises_on_unexpected_response_shape(self):
        with patch("urllib.request.urlopen", return_value=_make_response({"unexpected": True})):
            with pytest.raises(GeminiError):
                generate_journal("key", "t", [], "ts")

    def test_empty_callsigns_formats_as_none_detected(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data)
            return _make_response(_VALID_RESPONSE)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            generate_journal("key", "t", [], "ts")

        prompt = captured["body"]["contents"][0]["parts"][0]["text"]
        assert "None detected" in prompt

    def test_callsigns_included_in_prompt(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data)
            return _make_response(_VALID_RESPONSE)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            generate_journal("key", "t", ["WSLZ233", "KA1ABC"], "ts")

        prompt = captured["body"]["contents"][0]["parts"][0]["text"]
        assert "WSLZ233" in prompt
        assert "KA1ABC" in prompt
