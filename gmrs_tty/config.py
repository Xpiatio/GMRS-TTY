from __future__ import annotations

from gmrs_tty.constants import CONFIG_FILE, GAIN_MODES
from gmrs_tty.persistence.json_store import save_json


class AppConfig(dict):
    """Typed wrapper around the JSON config dict.

    Subclasses dict so it remains a drop-in for all existing code that passes
    config as a plain dict (ConfigDialog, make_ptt, json_store, etc.).
    Properties provide typed access with centralised defaults so magic strings
    and inline defaults don't repeat at every call site.
    """

    # ---- station identity ------------------------------------------------

    @property
    def callsign(self) -> str:
        return self.get("callsign", "N0CALL")

    @property
    def name(self) -> str:
        return self.get("name", "")

    @property
    def location(self) -> str:
        return self.get("location", "")

    # ---- audio / STT -----------------------------------------------------

    @property
    def input_device(self):
        return self.get("input_device", -1)

    @property
    def output_device(self):
        return self.get("output_device", -1)

    @property
    def monitor_enabled(self) -> bool:
        return bool(self.get("monitor_enabled", False))

    @property
    def monitor_passthrough(self) -> bool:
        return bool(self.get("monitor_passthrough", False))

    @property
    def whisper_model(self) -> str:
        return self.get("whisper_model", "small.en")

    @property
    def vad_threshold(self) -> float:
        return float(self.get("vad_threshold", 0.5))

    @property
    def system_monitor_sink(self) -> str:
        return (self.get("system_monitor_sink") or "").strip()

    @property
    def stt_gain_mode(self) -> str:
        """Gain stage applied after bandpass/denoise, before transcription:
        'agc' (dynamic attack/release AGC), 'rms' (one-shot RMS normalize),
        or 'off' (no gain)."""
        val = str(self.get("stt_gain_mode", "agc")).strip().lower()
        return val if val in GAIN_MODES else "agc"

    @property
    def stt_noise_profile(self) -> bool:
        """Feed squelch-closed noise-floor audio to the denoise stage as a
        stationary noise estimate instead of letting it self-estimate from
        the speech-bearing segment."""
        return bool(self.get("stt_noise_profile", False))

    @property
    def stt_debug_capture(self) -> bool:
        return bool(self.get("stt_debug_capture", False))

    @property
    def stt_debug_dir(self) -> str:
        return self.get("stt_debug_dir", "debug/stt")

    @property
    def saved_phrases(self) -> list:
        # Curated radio vocabulary lives in gmrs_tty/stt/vocab.py and is
        # assembled at Listen start. saved_phrases holds only the operator's
        # custom additions.
        return list(self.get("saved_phrases", []))

    @property
    def stt_vocab_max_callsigns(self) -> int:
        """Max number of contact callsigns to include in Whisper initial_prompt.
        Callsigns are ~6 tokens each; smaller limit leaves room for procedure
        vocabulary and custom phrases within the ~223-token budget."""
        return int(self.get("stt_vocab_max_callsigns", 15))

    # ---- TTS -------------------------------------------------------------

    @property
    def voice(self) -> str:
        return self.get("voice", "")

    @property
    def tts_length_scale(self) -> float:
        return float(self.get("tts_length_scale", 1.0))

    @property
    def tx_conditioning(self) -> bool:
        """Band-limit, compress, and level-normalize synthesized speech before
        it drives the radio's mic input."""
        return bool(self.get("tx_conditioning", False))

    @property
    def vox_primer_enabled(self) -> bool:
        """Prepend a short tone to synthesized TX audio so a VOX-keyed radio
        is fully keyed before the message starts."""
        return bool(self.get("vox_primer_enabled", False))

    @property
    def vox_primer_ms(self) -> int:
        """Duration of the VOX primer tone in milliseconds."""
        return int(self.get("vox_primer_ms", 300))

    @property
    def vox_primer_word_enabled(self) -> bool:
        """Speak a configurable priming word (e.g. "transmit") after the VOX
        primer tone and before the message, so a VOX-keyed radio is keyed on a
        clear spoken keyword.  Different radios may need different words."""
        return bool(self.get("vox_primer_word_enabled", False))

    @property
    def vox_primer_word(self) -> str:
        """The spoken VOX priming word."""
        return str(self.get("vox_primer_word", "transmit"))

    @property
    def tx_max_duration_seconds(self) -> int:
        """Hard cap on how long PTT may remain keyed for any single transmission."""
        return int(self.get("tx_max_duration_seconds", 60))

    @property
    def tx_synthesis_timeout_seconds(self) -> int:
        """Max time to wait for TTS synthesis before aborting without keying PTT."""
        return int(self.get("tx_synthesis_timeout_seconds", 30))

    # ---- UI / display ----------------------------------------------------

    @property
    def dark_mode(self) -> bool:
        return bool(self.get("dark_mode", False))

    @property
    def touch_mode(self) -> bool:
        return bool(self.get("touch_mode", False))

    @property
    def time_format(self) -> str:
        return self.get("time_format", "24h")

    @property
    def filter_profanity(self) -> bool:
        return bool(self.get("filter_profanity", True))

    @property
    def fuzzy_callsign(self) -> bool:
        return bool(self.get("fuzzy_callsign", False))

    # ---- radio / service -------------------------------------------------

    @property
    def radio_service(self) -> str:
        return self.get("radio_service", "")

    @property
    def listen_only(self) -> bool:
        return bool(self.get("listen_only", False))

    # ---- PTT -------------------------------------------------------------

    @property
    def ptt_mode(self) -> str:
        return self.get("ptt_mode", "manual")

    @property
    def ptt_serial_port(self) -> str:
        return (self.get("ptt_serial_port") or "").strip()

    @property
    def ptt_serial_line(self) -> str:
        return self.get("ptt_serial_line", "RTS")

    # ---- attendance ------------------------------------------------------

    @property
    def attendance_enabled(self) -> bool:
        return bool((self.get("attendance") or {}).get("enabled", False))

    @attendance_enabled.setter
    def attendance_enabled(self, value: bool) -> None:
        self["attendance"] = {"enabled": value}

    # ---- AI / journal ----------------------------------------------------

    @property
    def gemini_api_key(self) -> str:
        return (self.get("gemini_api_key") or "").strip()

    # ---- quick messages --------------------------------------------------

    @property
    def quick_messages(self) -> list:
        return self.get("quick_messages", [])

    # ---- persistence ---------------------------------------------------------

    def save(self) -> None:
        """Persist this config to disk."""
        save_json(CONFIG_FILE, self)
