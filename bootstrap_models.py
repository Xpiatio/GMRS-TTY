#!/usr/bin/env python3
"""Pre-stage the offline models GMRS-TTY needs.

GMRS-TTY is designed for fully offline operation — the application itself never
attempts to fetch a model at runtime. Run this script once on a machine with
internet access; the resulting Models/ directory is portable and can be copied
to air-gapped target machines alongside the source tree.

Two model groups are downloaded:
- Whisper (STT) into Models/STT/<name>/
- ECAPA-TDNN (speaker ID) into Models/Speaker/ecapa-tdnn/

Usage:
    python bootstrap_models.py                          # both, defaults
    python bootstrap_models.py --model base.en          # smaller Whisper variant
    python bootstrap_models.py --skip-speaker           # skip speaker model
    python bootstrap_models.py --skip-whisper           # skip Whisper
    python bootstrap_models.py --speaker-model ecapa-voxceleb
"""
import argparse
import os
import sys

WHISPER_REPOS = {
    "tiny.en":   "Systran/faster-whisper-tiny.en",
    "base.en":   "Systran/faster-whisper-base.en",
    "small.en":  "Systran/faster-whisper-small.en",
    "medium.en": "Systran/faster-whisper-medium.en",
    "large-v3":  "Systran/faster-whisper-large-v3",
}

SPEAKER_REPOS = {
    "ecapa-voxceleb": ("speechbrain/spkrec-ecapa-voxceleb", "ecapa-tdnn"),
}


def _fetch_whisper(model: str, snapshot_download) -> None:
    target = os.path.join("Models", "STT", model)
    os.makedirs(target, exist_ok=True)
    repo_id = WHISPER_REPOS[model]
    print(f"Whisper: downloading {repo_id} -> {target}")
    snapshot_download(repo_id=repo_id, local_dir=target)
    print(f"Whisper: done. Loaded at runtime from {target}/")


def _fetch_speaker(model: str, snapshot_download) -> None:
    repo_id, subdir = SPEAKER_REPOS[model]
    target = os.path.join("Models", "Speaker", subdir)
    os.makedirs(target, exist_ok=True)
    print(f"Speaker: downloading {repo_id} -> {target}")
    snapshot_download(repo_id=repo_id, local_dir=target)
    print(f"Speaker: done. Loaded at runtime from {target}/")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--model",
        default="small.en",
        choices=sorted(WHISPER_REPOS),
        help="faster-whisper variant to fetch (default: small.en).",
    )
    parser.add_argument(
        "--speaker-model",
        default="ecapa-voxceleb",
        choices=sorted(SPEAKER_REPOS),
        help="speaker embedding model to fetch (default: ecapa-voxceleb).",
    )
    parser.add_argument(
        "--skip-whisper", action="store_true", help="Do not download a Whisper model."
    )
    parser.add_argument(
        "--skip-speaker", action="store_true", help="Do not download the speaker model."
    )
    args = parser.parse_args()

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print(
            "huggingface_hub is required. Install it with:\n"
            "    pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    if not args.skip_whisper:
        _fetch_whisper(args.model, snapshot_download)
    if not args.skip_speaker:
        _fetch_speaker(args.speaker_model, snapshot_download)
    return 0


if __name__ == "__main__":
    sys.exit(main())
