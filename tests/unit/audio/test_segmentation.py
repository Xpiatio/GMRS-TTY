from gmrs_tty.audio.segmentation import pick_cut_index


class TestPickCutIndexBasic:
    def test_returns_argmin_in_window(self):
        peaks = [0.5, 0.3, 0.8, 0.1, 0.4]
        assert pick_cut_index(peaks, 0, 5) == 3

    def test_window_restricts_search(self):
        peaks = [0.0, 0.5, 0.3, 0.8, 0.1]
        # Outside the window, 0.0 and 0.1 are lower, but only [1,4) is searched.
        assert pick_cut_index(peaks, 1, 4) == 2

    def test_ties_pick_earliest(self):
        peaks = [0.2, 0.1, 0.5, 0.1, 0.1]
        assert pick_cut_index(peaks, 0, 5) == 1


class TestPickCutIndexEdges:
    def test_single_element_window(self):
        assert pick_cut_index([0.4, 0.2, 0.7], 1, 2) == 1

    def test_empty_window_returns_none(self):
        assert pick_cut_index([0.1, 0.2, 0.3], 2, 2) is None

    def test_inverted_window_returns_none(self):
        assert pick_cut_index([0.1, 0.2, 0.3], 3, 1) is None

    def test_empty_peaks_returns_none(self):
        assert pick_cut_index([], 0, 5) is None

    def test_start_clamped_to_zero(self):
        peaks = [0.1, 0.5, 0.3]
        assert pick_cut_index(peaks, -5, 2) == 0

    def test_end_clamped_to_length(self):
        peaks = [0.5, 0.1, 0.3]
        assert pick_cut_index(peaks, 0, 99) == 1


class TestPickCutIndexFullRange:
    def test_uniform_peaks_returns_start(self):
        peaks = [0.3, 0.3, 0.3, 0.3]
        assert pick_cut_index(peaks, 0, 4) == 0

    def test_strictly_decreasing(self):
        peaks = [0.9, 0.7, 0.5, 0.3, 0.1]
        assert pick_cut_index(peaks, 0, 5) == 4

    def test_strictly_increasing(self):
        peaks = [0.1, 0.3, 0.5, 0.7, 0.9]
        assert pick_cut_index(peaks, 0, 5) == 0
