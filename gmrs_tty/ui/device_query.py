import sounddevice as sd
from PySide6.QtCore import QThread, Signal

from gmrs_tty.audio.capture import enumerate_monitor_sources


class DeviceQueryThread(QThread):
    """Enumerates PortAudio devices and monitor sources off the GUI thread.

    sd.query_devices() can take hundreds of ms on ALSA/PulseAudio systems,
    which freezes the Configuration dialog (and starves the open STT
    InputStream) if run synchronously.
    """
    devices_ready = Signal(list)
    monitor_sources_ready = Signal(list)

    def run(self):
        try:
            devices = list(sd.query_devices())
        except Exception:
            devices = []
        self.devices_ready.emit(devices)
        self.monitor_sources_ready.emit(enumerate_monitor_sources())
