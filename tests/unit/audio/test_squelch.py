from gmrs_tty.audio.squelch import SquelchDetector


class TestSquelchDetectorOpening:
    def test_initial_state_closed(self):
        detector = SquelchDetector()
        assert detector.is_open is False

    def test_opens_after_hold_chunks(self):
        detector = SquelchDetector(open_threshold=0.05, open_hold_chunks=2)
        assert detector.update(0.10) is None
        assert detector.update(0.10) == 'opened'
        assert detector.is_open is True

    def test_single_spike_does_not_open(self):
        detector = SquelchDetector(open_threshold=0.05, open_hold_chunks=2)
        detector.update(0.10)
        detector.update(0.01)
        assert detector.update(0.10) is None
        assert detector.is_open is False

    def test_no_double_open_event(self):
        detector = SquelchDetector(open_threshold=0.05, open_hold_chunks=1)
        assert detector.update(0.10) == 'opened'
        assert detector.update(0.10) is None
        assert detector.update(0.10) is None


class TestSquelchDetectorClosing:
    def test_closes_after_hold_chunks(self):
        detector = SquelchDetector(
            open_threshold=0.05, open_hold_chunks=2, close_hold_chunks=3
        )
        detector.update(0.10)
        detector.update(0.10)
        assert detector.update(0.01) is None
        assert detector.update(0.01) is None
        assert detector.update(0.01) == 'closed'
        assert detector.is_open is False

    def test_brief_quiet_does_not_close(self):
        detector = SquelchDetector(
            open_threshold=0.05, open_hold_chunks=2, close_hold_chunks=3
        )
        detector.update(0.10)
        detector.update(0.10)
        detector.update(0.01)
        detector.update(0.10)
        detector.update(0.01)
        assert detector.is_open is True

    def test_no_double_close_event(self):
        detector = SquelchDetector(
            open_threshold=0.05, open_hold_chunks=1, close_hold_chunks=1
        )
        detector.update(0.10)
        assert detector.update(0.01) == 'closed'
        assert detector.update(0.01) is None


class TestSquelchDetectorReset:
    def test_reset_clears_open_state(self):
        detector = SquelchDetector(open_hold_chunks=2)
        detector.update(0.10)
        detector.update(0.10)
        assert detector.is_open is True
        detector.reset()
        assert detector.is_open is False

    def test_reset_clears_above_counter(self):
        detector = SquelchDetector(open_threshold=0.05, open_hold_chunks=3)
        detector.update(0.10)
        detector.update(0.10)
        detector.reset()
        assert detector.update(0.10) is None
        assert detector.update(0.10) is None
        assert detector.update(0.10) == 'opened'

    def test_reset_clears_below_counter(self):
        detector = SquelchDetector(
            open_threshold=0.05, open_hold_chunks=1, close_hold_chunks=3
        )
        detector.update(0.10)
        detector.update(0.01)
        detector.update(0.01)
        detector.reset()
        assert detector.update(0.10) == 'opened'


class TestSquelchDetectorCycles:
    def test_repeated_open_close_cycles(self):
        detector = SquelchDetector(
            open_threshold=0.05, open_hold_chunks=1, close_hold_chunks=1
        )
        assert detector.update(0.10) == 'opened'
        assert detector.update(0.01) == 'closed'
        assert detector.update(0.10) == 'opened'
        assert detector.update(0.01) == 'closed'

    def test_threshold_boundary_is_strict_above(self):
        detector = SquelchDetector(
            open_threshold=0.05, open_hold_chunks=1, close_hold_chunks=1
        )
        assert detector.update(0.05) is None
        assert detector.is_open is False
        assert detector.update(0.06) == 'opened'
