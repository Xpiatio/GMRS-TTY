"""normalize_service must coerce config.json input to a known service constant.
A typo or missing key has to fall back to GMRS — the licensed mode — so a
malformed config can't accidentally drop the user into a permissive
ID-less transmit path."""
import re

from gmrs_tty.constants import (
    DEFAULT_SERVICE,
    HALLUCINATIONS,
    SERVICE_FRS,
    SERVICE_GMRS,
    normalize_service,
    utc_now_iso,
    validate_voice_path,
)


class TestNormalizeService:
    def test_default_is_gmrs(self):
        assert DEFAULT_SERVICE == SERVICE_GMRS

    def test_recognizes_gmrs(self):
        assert normalize_service("GMRS") == SERVICE_GMRS
        assert normalize_service("gmrs") == SERVICE_GMRS
        assert normalize_service(" GMRS ") == SERVICE_GMRS

    def test_recognizes_frs(self):
        assert normalize_service("FRS") == SERVICE_FRS
        assert normalize_service("frs") == SERVICE_FRS

    def test_unknown_falls_back_to_gmrs(self):
        # ID-rule-enforced default protects users from accidental FRS-mode
        # operation when their config file is malformed.
        assert normalize_service("HAM") == SERVICE_GMRS
        assert normalize_service("typo") == SERVICE_GMRS

    def test_missing_or_blank_falls_back_to_gmrs(self):
        assert normalize_service(None) == SERVICE_GMRS
        assert normalize_service("") == SERVICE_GMRS
        assert normalize_service("   ") == SERVICE_GMRS


class TestUtcNowIso:
    _ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_format_is_iso8601_compact(self):
        ts = utc_now_iso()
        assert self._ISO_RE.match(ts), f"unexpected format: {ts!r}"

    def test_returns_string(self):
        assert isinstance(utc_now_iso(), str)


class TestValidateVoicePath:
    def test_empty_string_is_invalid(self):
        assert validate_voice_path("") is False

    def test_none_is_invalid(self):
        assert validate_voice_path(None) is False

    def test_nonexistent_path_is_invalid(self):
        assert validate_voice_path("/nonexistent/voice.onnx") is False

    def test_existing_file_is_valid(self, tmp_path):
        f = tmp_path / "voice.onnx"
        f.write_bytes(b"")
        assert validate_voice_path(str(f)) is True

    def test_directory_is_invalid(self, tmp_path):
        assert validate_voice_path(str(tmp_path)) is False


class TestHallucinations:
    def test_is_frozenset(self):
        assert isinstance(HALLUCINATIONS, frozenset)

    def test_common_false_positives_present(self):
        assert "you" in HALLUCINATIONS
        assert "thank you" in HALLUCINATIONS
        assert "." in HALLUCINATIONS
