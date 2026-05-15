import os

# Common Whisper hallucinations on silence/noise — drop these.
HALLUCINATIONS = frozenset({
    "you", "thank you", "thanks", "thanks for watching",
    "thank you for watching", "thanks for watching!", "bye", ".",
    "okay", "ok", "yeah", "mm", "hmm",
})


class WhisperTranscriber:
    """Offline STT via faster-whisper (CTranslate2, int8 CPU).

    Loads a Whisper model from a local directory (no network) and exposes
    a single transcribe() entry point. Drops common Whisper hallucinations
    on silence so the chat doesn't fill up with stray 'you' / 'thank you'
    lines between transmissions.
    """

    def __init__(self, model):
        self.model = model

    @classmethod
    def load(cls, model_path):
        from faster_whisper import WhisperModel

        # Leave at least one core free for the Qt event loop. faster-whisper's
        # default cpu_threads=0 means "use all cores", which saturates the CPU
        # during inference and starves the GUI — opening menus or even simple
        # dialogs visibly stalls while a transcription is running.
        cpu_threads = max(1, (os.cpu_count() or 2) - 1)
        return cls(
            WhisperModel(
                model_path,
                device="cpu",
                compute_type="int8",
                cpu_threads=cpu_threads,
            )
        )

    def transcribe(self, audio):
        """Return transcribed text, or None when the output is empty or
        matches a known Whisper-on-silence hallucination."""
        segments, _ = self.model.transcribe(
            audio, language="en", beam_size=1, vad_filter=False
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        normalized = text.lower().strip(".,!?;: ")
        if not text or normalized in HALLUCINATIONS:
            return None
        return text
