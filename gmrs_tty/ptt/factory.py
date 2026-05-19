from gmrs_tty.ptt.manual import ManualPTT
from gmrs_tty.ptt.serial_ptt import SerialPTT
from gmrs_tty.ptt.vox import VoxPTT

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
            print("PTT: USB FTDI selected but no serial port configured; falling back to manual.")
            return ManualPTT()
        try:
            return SerialPTT(port, line)
        except Exception as e:
            print(f"PTT: failed to open serial port {port}: {e}; falling back to manual.")
            return ManualPTT()
    return _SIMPLE_MODES.get(mode, ManualPTT)()
