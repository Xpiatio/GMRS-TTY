from gmrs_tty.audio.silence_watchdog import SilenceWatchdog


class TestSilenceWatchdogCounting:
    def test_below_threshold_returns_false(self):
        watchdog = SilenceWatchdog(reset_after_chunks=3)
        assert watchdog.note_silence() is False
        assert watchdog.note_silence() is False

    def test_reaching_threshold_returns_true(self):
        watchdog = SilenceWatchdog(reset_after_chunks=3)
        watchdog.note_silence()
        watchdog.note_silence()
        assert watchdog.note_silence() is True

    def test_threshold_keeps_signalling_until_reset(self):
        watchdog = SilenceWatchdog(reset_after_chunks=2)
        watchdog.note_silence()
        assert watchdog.note_silence() is True
        # The worker is expected to reset() after acting; until it does, the
        # watchdog continues to report "reset due" so a missed call doesn't
        # silently swallow the signal.
        assert watchdog.note_silence() is True


class TestSilenceWatchdogReset:
    def test_note_speech_clears_counter(self):
        watchdog = SilenceWatchdog(reset_after_chunks=3)
        watchdog.note_silence()
        watchdog.note_silence()
        watchdog.note_speech()
        assert watchdog.note_silence() is False
        assert watchdog.note_silence() is False

    def test_reset_clears_counter(self):
        watchdog = SilenceWatchdog(reset_after_chunks=2)
        watchdog.note_silence()
        watchdog.note_silence()
        watchdog.reset()
        assert watchdog.note_silence() is False


class TestSilenceWatchdogCycles:
    def test_multiple_silence_cycles(self):
        watchdog = SilenceWatchdog(reset_after_chunks=2)

        watchdog.note_silence()
        assert watchdog.note_silence() is True
        watchdog.reset()

        watchdog.note_silence()
        assert watchdog.note_silence() is True
        watchdog.reset()

        assert watchdog.note_silence() is False

    def test_speech_in_the_middle_of_silence_resets_cycle(self):
        watchdog = SilenceWatchdog(reset_after_chunks=3)
        watchdog.note_silence()
        watchdog.note_silence()
        watchdog.note_speech()
        watchdog.note_silence()
        watchdog.note_silence()
        assert watchdog.note_silence() is True


class TestSilenceWatchdogConstruction:
    def test_accepts_float_threshold(self):
        watchdog = SilenceWatchdog(reset_after_chunks=2.0)
        watchdog.note_silence()
        assert watchdog.note_silence() is True
