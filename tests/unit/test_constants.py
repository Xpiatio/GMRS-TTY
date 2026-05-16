"""normalize_service must coerce config.json input to a known service constant.
A typo or missing key has to fall back to GMRS — the licensed mode — so a
malformed config can't accidentally drop the user into a permissive
ID-less transmit path."""
from gmrs_tty.constants import (
    DEFAULT_SERVICE,
    SERVICE_FRS,
    SERVICE_GMRS,
    normalize_service,
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
