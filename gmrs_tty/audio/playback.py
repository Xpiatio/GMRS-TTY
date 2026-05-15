import sounddevice as sd
from PySide6.QtCore import QThread, Signal


class AudioPlayerThread(QThread):
    finished = Signal()
    error = Signal(str)

    def __init__(self, audio_data, sample_rate, device=None):
        super().__init__()
        self.audio_data = audio_data
        self.sample_rate = sample_rate
        self.device = device if device not in (None, -1) else None

    def run(self):
        try:
            sd.play(self.audio_data, samplerate=self.sample_rate, device=self.device)
            sd.wait()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit()
