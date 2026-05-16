from unittest.mock import patch

import pytest

from gmrs_tty.net import online


@pytest.fixture(autouse=True)
def fresh_probe():
    """Reset the module-level cache between tests so cached results from one
    test can't bleed into the next."""
    online.reset_cache()
    yield
    online.reset_cache()


class TestIsOnline:
    def test_returns_true_when_probe_succeeds(self):
        with patch.object(online, "_probe", return_value=True):
            assert online.is_online() is True

    def test_returns_false_when_probe_raises(self):
        def boom(_url, _timeout):
            raise OSError("name not resolved")
        with patch.object(online, "_probe", side_effect=boom):
            assert online.is_online() is False

    def test_returns_false_when_probe_returns_false(self):
        with patch.object(online, "_probe", return_value=False):
            assert online.is_online() is False

    def test_caches_result_within_ttl(self):
        with patch.object(online, "_probe", return_value=True) as probe:
            online.is_online()
            online.is_online()
            online.is_online()
            assert probe.call_count == 1

    def test_reprobes_after_ttl_expires(self):
        times = iter([1000.0, 1000.0, 1000.0 + online.PROBE_TTL_SECONDS + 1])
        with patch.object(online, "_probe", return_value=True) as probe, \
             patch.object(online.time, "monotonic", side_effect=lambda: next(times)):
            online.is_online()
            online.is_online()  # cached
            online.is_online()  # ttl expired → re-probe
            assert probe.call_count == 2

    def test_reset_cache_forces_reprobe(self):
        with patch.object(online, "_probe", return_value=True) as probe:
            online.is_online()
            online.reset_cache()
            online.is_online()
            assert probe.call_count == 2

    def test_invalidate_after_failure_clears_positive_cache(self):
        """When a downstream call to the API fails, the caller can mark the
        connection as suspect so the next is_online() re-probes instead of
        returning a stale True."""
        with patch.object(online, "_probe", return_value=True) as probe:
            online.is_online()
            online.invalidate()
            online.is_online()
            assert probe.call_count == 2
