"""AppConfig typed accessors for the STT quality-pack keys."""
from gmrs_tty.config import AppConfig


class TestGainMode:
    def test_default_is_agc(self):
        assert AppConfig().stt_gain_mode == "agc"

    def test_valid_values_pass_through(self):
        for mode in ("agc", "rms", "off"):
            assert AppConfig({"stt_gain_mode": mode}).stt_gain_mode == mode

    def test_normalizes_case_and_whitespace(self):
        assert AppConfig({"stt_gain_mode": "  RMS "}).stt_gain_mode == "rms"

    def test_unknown_value_falls_back_to_agc(self):
        assert AppConfig({"stt_gain_mode": "loud"}).stt_gain_mode == "agc"


class TestNoiseProfile:
    def test_default_off(self):
        assert AppConfig().stt_noise_profile is False

    def test_truthy(self):
        assert AppConfig({"stt_noise_profile": True}).stt_noise_profile is True


class TestDebugCapture:
    def test_defaults(self):
        cfg = AppConfig()
        assert cfg.stt_debug_capture is False
        assert cfg.stt_debug_dir == "debug/stt"

    def test_custom_dir(self):
        assert AppConfig({"stt_debug_dir": "/tmp/x"}).stt_debug_dir == "/tmp/x"


class TestVocabulary:
    def test_saved_phrases_default_empty(self):
        assert AppConfig().saved_phrases == []

    def test_saved_phrases_returns_copy(self):
        cfg = AppConfig({"saved_phrases": ["Kent County ARES"]})
        phrases = cfg.saved_phrases
        phrases.append("mutated")
        assert cfg.saved_phrases == ["Kent County ARES"]

    def test_max_callsigns_default(self):
        assert AppConfig().stt_vocab_max_callsigns == 15

    def test_max_callsigns_coerces_int(self):
        assert AppConfig({"stt_vocab_max_callsigns": "7"}).stt_vocab_max_callsigns == 7
