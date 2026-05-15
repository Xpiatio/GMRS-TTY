import numpy as np
from piper.config import SynthesisConfig
from PySide6.QtCore import QThread, Signal


class TTSSynthesisThread(QThread):
    """Renders Piper synthesis off the GUI thread and emits the assembled
    int16 PCM buffer (with PTT lead-in/tail silence already padded in).
    Only one instance runs at a time — espeak-ng's global state is not safe
    under concurrent synthesis."""
    ready = Signal(object, int)  # (np.ndarray int16 or None, sample_rate)
    error = Signal(str)

    def __init__(self, voice, text, lead_seconds, tail_seconds, length_scale=1.0, parent=None):
        super().__init__(parent)
        self.voice = voice
        self.text = text
        self.lead_seconds = lead_seconds
        self.tail_seconds = tail_seconds
        self.length_scale = length_scale

    def run(self):
        try:
            syn_config = SynthesisConfig(
                speaker_id=0 if self.voice.config.num_speakers > 1 else None,
                length_scale=self.length_scale,
            )
            sample_rate = self.voice.config.sample_rate

            chunks = []
            for chunk in self.voice.synthesize(self.text, syn_config=syn_config):
                arr = chunk.audio_int16_array
                if len(arr) > 0:
                    chunks.append(arr)

            if not chunks:
                self.ready.emit(None, sample_rate)
                return

            lead_samples = int(self.lead_seconds * sample_rate)
            tail_samples = int(self.tail_seconds * sample_rate)
            total = lead_samples + sum(len(c) for c in chunks) + tail_samples
            # np.zeros so lead and tail regions are already silence; no
            # extra concatenates to splice them in.
            audio = np.zeros(total, dtype=np.int16)
            pos = lead_samples
            for c in chunks:
                n = len(c)
                audio[pos:pos + n] = c
                pos += n
            self.ready.emit(audio, sample_rate)
        except Exception as e:
            self.error.emit(str(e))
