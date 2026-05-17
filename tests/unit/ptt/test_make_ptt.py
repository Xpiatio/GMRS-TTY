from gmrs_tty.ptt import ManualPTT, VoxPTT, make_ptt


class TestMakePttModeSelection:
    def test_default_mode_is_manual(self):
        assert isinstance(make_ptt({}), ManualPTT)

    def test_explicit_manual(self):
        assert isinstance(make_ptt({"ptt_mode": "manual"}), ManualPTT)

    def test_vox_mode(self):
        assert isinstance(make_ptt({"ptt_mode": "vox"}), VoxPTT)

    def test_unknown_mode_falls_through_to_manual(self):
        # Defensive: an unknown / future mode value shouldn't crash; it falls back.
        assert isinstance(make_ptt({"ptt_mode": "morse-code-bluetooth-magic"}), ManualPTT)


class TestUsbFtdiFallback:
    def test_missing_port_falls_back_to_manual(self, capsys):
        result = make_ptt({"ptt_mode": "usb_ftdi", "ptt_serial_port": ""})
        assert isinstance(result, ManualPTT)
        # Operators need to see *why* their configured PTT mode didn't engage.
        assert "no serial port configured" in capsys.readouterr().out

    def test_whitespace_only_port_falls_back_to_manual(self, capsys):
        result = make_ptt({"ptt_mode": "usb_ftdi", "ptt_serial_port": "   "})
        assert isinstance(result, ManualPTT)
        assert "no serial port configured" in capsys.readouterr().out

    def test_unopenable_port_falls_back_to_manual(self, capsys):
        # A path that definitely won't exist as a serial device. The Serial
        # constructor will raise; make_ptt catches and degrades to Manual.
        result = make_ptt(
            {"ptt_mode": "usb_ftdi", "ptt_serial_port": "/dev/this_serial_port_does_not_exist_12345"}
        )
        assert isinstance(result, ManualPTT)
        assert "failed to open serial port" in capsys.readouterr().out


class TestVoxTailSilence:
    # Pin the per-mode padding contract so callers (TX pipeline) keep getting
    # the right amount of silence. VOX needs trailing silence; serial needs both.
    def test_manual_has_no_padding(self):
        ptt = ManualPTT()
        assert ptt.lead_in_seconds == 0.0
        assert ptt.tail_seconds == 0.0

    def test_vox_has_tail_silence(self):
        ptt = VoxPTT()
        assert ptt.lead_in_seconds == 0.0
        assert ptt.tail_seconds == 0.15
