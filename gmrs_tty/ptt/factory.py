import logging

from gmrs_tty.ptt.manual import ManualPTT
from gmrs_tty.ptt.serial_ptt import SerialPTT
from gmrs_tty.ptt.vox import VoxPTT

_log = logging.getLogger(__name__)

# Modes whose constructors take no arguments. New simple modes register here
# without touching make_ptt's logic.
_SIMPLE_MODES = {
    "vox": VoxPTT,
    "manual": ManualPTT,
}


def make_ptt(config):
    mode = config.get("ptt_mode", "manual")
    if mode == "usb_ftdi":
        port = (config.get("ptt_serial_port") or "").strip()
        line = config.get("ptt_serial_line", "RTS")
        if not port:
            _log.warning("PTT: USB FTDI selected but no serial port configured; falling back to manual.")
            return ManualPTT()
        try:
            return SerialPTT(port, line)
        except Exception as e:
            _log.error("PTT: failed to open serial port %s: %s; falling back to manual.", port, e)
            return ManualPTT()
    return _SIMPLE_MODES.get(mode, ManualPTT)()
