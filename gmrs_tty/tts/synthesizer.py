import numpy as np
from piper.config import SynthesisConfig
from PySide6.QtCore import QThread, Signal


def make_vox_primer(
    sample_rate: int,
    ms: float,
    freq: int = 1000,
    level: float = 0.3,
    gap_ms: float = 80.0,
) -> "np.ndarray":
    """Build a VOX-priming burst: ``ms`` of a ``freq`` Hz sine at ``level`` of
    full scale, followed by ``gap_ms`` of silence. The tone keys a VOX radio;
    the gap lets it settle before speech so the first word isn't clipped.
    Returns int16 PCM at ``sample_rate``."""
    tone_n = int(ms / 1000.0 * sample_rate)
    gap_n = int(gap_ms / 1000.0 * sample_rate)
    t = np.arange(tone_n) / sample_rate
    tone = (level * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    return np.concatenate([tone, np.zeros(gap_n, dtype=np.int16)])


class TTSSynthesisThread(QThread):
    """Renders Piper synthesis off the GUI thread and emits the assembled
    int16 PCM buffer (with PTT lead-in/tail silence already padded in).
    Only one instance runs at a time — espeak-ng's global state is not safe
    under concurrent synthesis."""
    ready = Signal(object, int)  # (np.ndarray int16 or None, sample_rate)
    error = Signal(str)

    def __init__(self, voice, text, lead_seconds, tail_seconds, length_scale=1.0,
                 condition=False, vox_primer_ms=0.0, parent=None):
        super().__init__(parent)
        self.voice = voice
        self.text = text
        self.lead_seconds = lead_seconds
        self.tail_seconds = tail_seconds
        self.length_scale = length_scale
        # Band-limit/compress/normalize synthesized speech for the radio's
        # mic input. Voice-test playback goes to real speakers where
        # conditioning would just degrade the audio, so it stays off there.
        self.condition = bool(condition)
        self.vox_primer_ms = float(vox_primer_ms)

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

            speech = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
            if self.condition:
                # Conditioned before splicing so the lead/tail regions stay
                # exact zeros (the radio sees clean silence around the keying).
                from gmrs_tty.audio.tx_conditioning import condition_tx_audio
                speech = condition_tx_audio(speech, sample_rate)

            lead_samples = int(self.lead_seconds * sample_rate)
            tail_samples = int(self.tail_seconds * sample_rate)
            primer = (
                make_vox_primer(sample_rate, self.vox_primer_ms)
                if self.vox_primer_ms > 0 else None
            )
            primer_samples = len(primer) if primer is not None else 0
            total = lead_samples + primer_samples + len(speech) + tail_samples
            # np.zeros so lead and tail regions are already silence; no
            # extra concatenates to splice them in.
            audio = np.zeros(total, dtype=np.int16)
            if primer is not None:
                audio[lead_samples:lead_samples + primer_samples] = primer
            speech_start = lead_samples + primer_samples
            audio[speech_start:speech_start + len(speech)] = speech
            self.ready.emit(audio, sample_rate)
        except Exception as e:
            self.error.emit(str(e))
