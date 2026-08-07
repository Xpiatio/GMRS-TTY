"""STTWorker.update_phrases must refresh the cached transcriber's prompt so
live contact/phrase changes reach Whisper without a worker restart."""
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from gmrs_tty.stt.worker import ModelCache, STTWorker


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_worker(qapp):
    return STTWorker()


class TestUpdatePhrases:
    def test_transcriber_prompt_updated_when_cache_set(self, qapp):
        w = _make_worker(qapp)
        fast = MagicMock()
        w._model_cache = ModelCache(
            whisper=fast, vad_model=MagicMock(), model_name="small.en",
        )
        w.update_phrases(["KE8AAA"])
        fast.update_prompt.assert_called_once_with(["KE8AAA"])
        assert w.saved_phrases == ["KE8AAA"]

    def test_no_cache_stores_phrases_without_raising(self, qapp):
        w = _make_worker(qapp)
        w.update_phrases(["KD9ZZZ"])
        assert w.saved_phrases == ["KD9ZZZ"]
