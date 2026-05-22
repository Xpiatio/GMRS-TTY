from __future__ import annotations


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
    def whisper_model(self) -> str:
        return self.get("whisper_model", "small.en")

    @property
    def vad_threshold(self) -> float:
        return float(self.get("vad_threshold", 0.5))

    @property
    def youtube_url(self) -> str:
        return self.get("youtube_url", "")

    # ---- TTS -------------------------------------------------------------

    @property
    def voice(self) -> str:
        return self.get("voice", "")

    @property
    def tts_length_scale(self) -> float:
        return float(self.get("tts_length_scale", 1.0))

    # ---- UI / display ----------------------------------------------------

    @property
    def dark_mode(self) -> bool:
        return bool(self.get("dark_mode", False))

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

    # ---- AI / journal ----------------------------------------------------

    @property
    def gemini_api_key(self) -> str:
        return (self.get("gemini_api_key") or "").strip()

    # ---- quick messages --------------------------------------------------

    @property
    def quick_messages(self) -> list:
        return self.get("quick_messages", [])
