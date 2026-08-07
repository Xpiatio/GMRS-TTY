"""Staged-model discovery for the Models/STT directory.

Single source of truth for "which Whisper models are actually on disk".
faster-whisper treats a missing local path as a Hugging Face repo id and
tries to download it, so every model list the app offers the operator has
to be filtered through here — GMRS-TTY never downloads models at runtime.

Pure path logic (isdir only): no model is loaded and torch is never
imported, so this is safe to call from the GUI thread.
"""
from __future__ import annotations

import os

MODELS_STT_DIR = os.path.join("Models", "STT")
# GPU final-pass models are staged in Hugging Face transformers format
# beside the CT2 directory, under the same name plus this suffix.
HF_SUFFIX = "-hf"


def ct2_model_path(name: str, models_dir: str = MODELS_STT_DIR) -> str:
    """Directory holding the CT2 (faster-whisper) build of ``name``."""
    return os.path.join(models_dir, name)


def hf_model_path(name: str, models_dir: str = MODELS_STT_DIR) -> str:
    """Directory holding the HF transformers (GPU) build of ``name``."""
    return os.path.join(models_dir, name + HF_SUFFIX)


def model_path(name: str, backend: str = "cpu", models_dir: str = MODELS_STT_DIR) -> str:
    """Model directory for one backend — 'gpu' means the HF-format build."""
    if backend == "gpu":
        return hf_model_path(name, models_dir)
    return ct2_model_path(name, models_dir)


def is_staged(name: str, *, include_hf: bool = False,
              models_dir: str = MODELS_STT_DIR) -> bool:
    """True when ``name`` is present on disk.

    ``include_hf`` also accepts an HF-only staging, which is usable solely by
    the GPU final pass — callers that can only run CT2 must leave it False.
    """
    if os.path.isdir(ct2_model_path(name, models_dir)):
        return True
    return include_hf and os.path.isdir(hf_model_path(name, models_dir))


def staged_models(candidates, *, include_hf: bool = False,
                  models_dir: str = MODELS_STT_DIR) -> list[str]:
    """The subset of ``candidates`` staged on disk, sorted for stable UI order."""
    return sorted(
        name for name in candidates
        if is_staged(name, include_hf=include_hf, models_dir=models_dir)
    )
