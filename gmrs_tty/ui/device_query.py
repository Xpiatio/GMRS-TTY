import sounddevice as sd
from PySide6.QtCore import QThread, Signal


class DeviceQueryThread(QThread):
    """Enumerates PortAudio devices off the GUI thread. sd.query_devices()
    can take hundreds of ms on ALSA/PulseAudio systems, which freezes the
    Configuration dialog (and starves the open STT InputStream) if run
    synchronously."""
    devices_ready = Signal(list)

    def run(self):
        try:
            devices = list(sd.query_devices())
        except Exception:
            devices = []
        self.devices_ready.emit(devices)
