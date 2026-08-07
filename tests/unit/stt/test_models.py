"""Staged-model discovery — the single gate that keeps faster-whisper from
treating an unstaged name as a Hugging Face repo id and downloading it."""
from gmrs_tty.stt import models


def _stage(tmp_path, *names):
    root = tmp_path / "Models" / "STT"
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / name).mkdir(parents=True, exist_ok=True)
    return str(root)


class TestPaths:
    def test_ct2_and_hf_paths_differ_by_suffix(self, tmp_path):
        root = _stage(tmp_path)
        assert models.ct2_model_path("large-v3", root).endswith("large-v3")
        assert models.hf_model_path("large-v3", root).endswith("large-v3-hf")

    def test_model_path_picks_backend_directory(self, tmp_path):
        root = _stage(tmp_path)
        assert models.model_path("large-v3", "cpu", root) == \
            models.ct2_model_path("large-v3", root)
        assert models.model_path("large-v3", "gpu", root) == \
            models.hf_model_path("large-v3", root)

    def test_unknown_backend_falls_back_to_ct2(self, tmp_path):
        root = _stage(tmp_path)
        assert models.model_path("large-v3", "wat", root) == \
            models.ct2_model_path("large-v3", root)


class TestIsStaged:
    def test_ct2_directory_counts(self, tmp_path):
        root = _stage(tmp_path, "small.en")
        assert models.is_staged("small.en", models_dir=root)

    def test_missing_is_not_staged(self, tmp_path):
        root = _stage(tmp_path)
        assert not models.is_staged("small.en", models_dir=root)

    def test_hf_only_needs_include_hf(self, tmp_path):
        root = _stage(tmp_path, "large-v3-turbo-hf")
        assert not models.is_staged("large-v3-turbo", models_dir=root)
        assert models.is_staged("large-v3-turbo", include_hf=True, models_dir=root)

    def test_a_file_is_not_a_staged_model(self, tmp_path):
        root = _stage(tmp_path)
        (tmp_path / "Models" / "STT" / "small.en").write_text("not a directory")
        assert not models.is_staged("small.en", models_dir=root)


class TestStagedModels:
    def test_filters_and_sorts(self, tmp_path):
        root = _stage(tmp_path, "small.en", "base.en")
        assert models.staged_models(
            {"small.en", "base.en", "large-v3"}, models_dir=root
        ) == ["base.en", "small.en"]

    def test_empty_when_nothing_staged(self, tmp_path):
        root = _stage(tmp_path)
        assert models.staged_models({"small.en"}, models_dir=root) == []

    def test_include_hf_widens_the_list(self, tmp_path):
        root = _stage(tmp_path, "large-v3-turbo-hf")
        candidates = {"large-v3-turbo"}
        assert models.staged_models(candidates, models_dir=root) == []
        assert models.staged_models(
            candidates, include_hf=True, models_dir=root
        ) == ["large-v3-turbo"]
