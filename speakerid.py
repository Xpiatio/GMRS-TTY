"""Speaker identification for GMRS-TTY.

Three pieces:
- SpeakerEmbedder: ECAPA-TDNN wrapper; embeds a 16 kHz mono utterance into a
  192-dim vector. Loads from Models/Speaker/ecapa-tdnn/ (pre-staged by
  bootstrap_models.py); never fetches at runtime.
- VoiceprintStore: per-contact embedding bank, persisted to voiceprints/{CALLSIGN}.npz
  with a sidecar .meta.json. Matches a query embedding against centroid prints.
- UnknownClusterer: session-scoped grouping of unmatched voices into
  "Voice A", "Voice B", etc., so unknown speakers stay followable until they ID.

All cosine similarities are computed on L2-normalized vectors so the threshold
constants below are directly comparable across embedders.
"""
import datetime
import json
import os
import threading
from dataclasses import dataclass
from typing import Optional

# Speaker ID never reaches the network at runtime — only bootstrap_models.py does.
# Setting this here (before speechbrain/huggingface_hub import) prevents the
# Hub from being touched even for a metadata revision check, so air-gapped
# targets see no warnings and zero socket activity from this module.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import numpy as np


SPEAKER_MODEL_DIR = os.path.join("Models", "Speaker", "ecapa-tdnn")
VOICEPRINTS_DIR = "voiceprints"
EMBED_DIM = 192
MIN_EMBED_DURATION_S = 1.5
MAX_SAMPLES_PER_CONTACT = 50
CLUSTER_THRESHOLD = 0.70


@dataclass
class RxUtterance:
    """A single VAD-bounded utterance passed from STTWorker to the UI."""
    text: str
    duration_seconds: float
    embedding: Optional[np.ndarray] = None


@dataclass
class SpeakerMatch:
    """Result of identifying the speaker of an RxUtterance."""
    label: str          # display label: callsign, "Voice A", or "?"
    score: float        # cosine similarity to the chosen centroid (or 0.0)
    kind: str           # "confident" | "tentative" | "cluster" | "unknown"
    callsign: Optional[str] = None  # set when kind in {"confident","tentative"}
    cluster_label: Optional[str] = None  # set when kind == "cluster"


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return v.astype(np.float32, copy=False)
    return (v / n).astype(np.float32, copy=False)


class SpeakerEmbedder:
    """ECAPA-TDNN wrapper. Loading is best-effort: if the model directory is
    missing or speechbrain/torch isn't installed, .load() returns False and the
    rest of the app falls back to running without speaker ID."""

    def __init__(self, model_dir: str = SPEAKER_MODEL_DIR):
        self.model_dir = model_dir
        self._classifier = None
        self._torch = None
        self._error: Optional[str] = None

    def available(self) -> bool:
        return os.path.isdir(self.model_dir) and os.path.exists(
            os.path.join(self.model_dir, "hyperparams.yaml")
        )

    def load(self) -> bool:
        if not self.available():
            self._error = (
                f"Speaker model not found at '{self.model_dir}'. "
                "Run 'python bootstrap_models.py --speaker-model ecapa-voxceleb' "
                "on an internet-connected machine, then copy Models/ here."
            )
            return False
        try:
            import torch
            from speechbrain.inference.speaker import EncoderClassifier
        except Exception as e:
            self._error = f"speechbrain/torch not installed: {e}"
            return False
        try:
            self._classifier = EncoderClassifier.from_hparams(
                source=self.model_dir,
                savedir=self.model_dir,
                run_opts={"device": "cpu"},
            )
            self._torch = torch
            return True
        except Exception as e:
            self._error = f"failed to load ECAPA model: {e}"
            return False

    @property
    def error(self) -> Optional[str]:
        return self._error

    def embed(self, audio: np.ndarray, sample_rate: int = 16000) -> Optional[np.ndarray]:
        if self._classifier is None or audio is None or len(audio) == 0:
            return None
        if sample_rate != 16000:
            return None
        try:
            torch = self._torch
            wav = torch.from_numpy(audio.astype(np.float32, copy=False)).unsqueeze(0)
            with torch.no_grad():
                emb = self._classifier.encode_batch(wav)
            v = emb.squeeze().cpu().numpy().astype(np.float32)
            return _l2_normalize(v)
        except Exception as e:
            self._error = f"embed failed: {e}"
            return None


class VoiceprintStore:
    """Per-callsign embedding bank backed by voiceprints/{CALLSIGN}.npz files.

    Each file holds an embeddings array of shape (N, EMBED_DIM) and a parallel
    ids array of shape (N,) — ids are monotonic per-callsign so we can unenroll
    a specific sample (used by the auto-enroll undo ring). A sidecar
    .meta.json records last-enrolled / source for the Contacts dialog."""

    def __init__(self, directory: str = VOICEPRINTS_DIR):
        self.dir = directory
        os.makedirs(self.dir, exist_ok=True)
        self._embeddings: dict[str, np.ndarray] = {}
        self._ids: dict[str, np.ndarray] = {}
        self._next_id: dict[str, int] = {}
        self._centroids: dict[str, np.ndarray] = {}
        self._meta: dict = {}
        self._lock = threading.Lock()
        self._load_all()

    def _meta_path(self) -> str:
        return os.path.join(self.dir, ".meta.json")

    def _file_path(self, callsign: str) -> str:
        return os.path.join(self.dir, f"{callsign.upper()}.npz")

    def _load_all(self):
        try:
            with open(self._meta_path()) as f:
                self._meta = json.load(f)
        except FileNotFoundError:
            self._meta = {}
        except Exception as e:
            print(f"voiceprints: meta load failed: {e}")
            self._meta = {}

        try:
            entries = os.listdir(self.dir)
        except FileNotFoundError:
            return
        for name in entries:
            if not name.endswith(".npz") or name.startswith("."):
                continue
            callsign = name[: -len(".npz")].upper()
            try:
                data = np.load(self._file_path(callsign))
                emb = data["embeddings"].astype(np.float32)
                ids = data["ids"].astype(np.int64)
                if emb.ndim != 2 or emb.shape[1] != EMBED_DIM or len(emb) != len(ids):
                    print(f"voiceprints: {name} shape mismatch, skipping")
                    continue
                self._embeddings[callsign] = emb
                self._ids[callsign] = ids
                self._next_id[callsign] = int(ids.max()) + 1 if len(ids) else 1
                self._recompute_centroid(callsign)
            except Exception as e:
                print(f"voiceprints: failed to load {name}: {e}")

    def _recompute_centroid(self, callsign: str):
        emb = self._embeddings.get(callsign)
        if emb is None or len(emb) == 0:
            self._centroids.pop(callsign, None)
            return
        self._centroids[callsign] = _l2_normalize(emb.mean(axis=0))

    def _save_callsign(self, callsign: str):
        np.savez(
            self._file_path(callsign),
            embeddings=self._embeddings[callsign],
            ids=self._ids[callsign],
        )

    def _save_meta(self):
        try:
            with open(self._meta_path(), "w") as f:
                json.dump(self._meta, f, indent=2)
        except Exception as e:
            print(f"voiceprints: meta save failed: {e}")

    def enroll(self, callsign: str, embedding: np.ndarray, source: str = "auto") -> int:
        cs = callsign.upper()
        v = _l2_normalize(embedding.astype(np.float32)).reshape(1, EMBED_DIM)
        with self._lock:
            if cs not in self._embeddings:
                self._embeddings[cs] = np.zeros((0, EMBED_DIM), dtype=np.float32)
                self._ids[cs] = np.zeros((0,), dtype=np.int64)
                self._next_id[cs] = 1
            emb_id = self._next_id[cs]
            self._next_id[cs] += 1
            self._embeddings[cs] = np.concatenate([self._embeddings[cs], v])
            self._ids[cs] = np.concatenate(
                [self._ids[cs], np.array([emb_id], dtype=np.int64)]
            )
            if len(self._embeddings[cs]) > MAX_SAMPLES_PER_CONTACT:
                excess = len(self._embeddings[cs]) - MAX_SAMPLES_PER_CONTACT
                self._embeddings[cs] = self._embeddings[cs][excess:]
                self._ids[cs] = self._ids[cs][excess:]
            self._recompute_centroid(cs)
            self._meta[cs] = {
                "n_samples": int(len(self._embeddings[cs])),
                "last_enrolled": datetime.datetime.now().isoformat(timespec="seconds"),
                "source": source,
            }
            self._save_callsign(cs)
            self._save_meta()
        return emb_id

    def unenroll(self, callsign: str, emb_id: int) -> bool:
        cs = callsign.upper()
        with self._lock:
            if cs not in self._ids:
                return False
            mask = self._ids[cs] != emb_id
            if mask.all():
                return False
            self._embeddings[cs] = self._embeddings[cs][mask]
            self._ids[cs] = self._ids[cs][mask]
            self._recompute_centroid(cs)
            if cs in self._meta:
                self._meta[cs]["n_samples"] = int(len(self._embeddings[cs]))
            self._save_callsign(cs)
            self._save_meta()
            return True

    def reset_contact(self, callsign: str):
        cs = callsign.upper()
        with self._lock:
            self._embeddings.pop(cs, None)
            self._ids.pop(cs, None)
            self._next_id.pop(cs, None)
            self._centroids.pop(cs, None)
            self._meta.pop(cs, None)
            path = self._file_path(cs)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
            self._save_meta()

    def best_match(self, embedding: np.ndarray) -> Optional[tuple[str, float]]:
        if embedding is None:
            return None
        q = _l2_normalize(embedding.astype(np.float32))
        best_cs = None
        best_score = -1.0
        with self._lock:
            for cs, centroid in self._centroids.items():
                score = float(np.dot(q, centroid))
                if score > best_score:
                    best_score = score
                    best_cs = cs
        if best_cs is None:
            return None
        return best_cs, best_score

    def sample_count(self, callsign: str) -> int:
        return int(len(self._embeddings.get(callsign.upper(), [])))

    def meta(self, callsign: str) -> dict:
        return dict(self._meta.get(callsign.upper(), {}))

    def known_callsigns(self) -> list[str]:
        return sorted(self._embeddings.keys())


class UnknownClusterer:
    """In-memory clustering of unknown utterances within a single Listen session.
    Resets when STT is stopped or .reset() is called explicitly."""

    THRESHOLD = CLUSTER_THRESHOLD

    def __init__(self):
        self._labels: list[str] = []
        self._centroids: list[np.ndarray] = []
        self._samples: list[list[np.ndarray]] = []
        self._next_idx = 0

    def reset(self):
        self._labels.clear()
        self._centroids.clear()
        self._samples.clear()
        self._next_idx = 0

    def _next_label(self) -> str:
        idx = self._next_idx
        self._next_idx += 1
        if idx < 26:
            return f"Voice {chr(ord('A') + idx)}"
        first = chr(ord('A') + (idx // 26) - 1)
        second = chr(ord('A') + (idx % 26))
        return f"Voice {first}{second}"

    def assign(self, embedding: np.ndarray) -> tuple[str, float]:
        q = _l2_normalize(embedding.astype(np.float32))
        best_i = -1
        best_score = -1.0
        for i, c in enumerate(self._centroids):
            s = float(np.dot(q, c))
            if s > best_score:
                best_score = s
                best_i = i
        if best_i >= 0 and best_score >= self.THRESHOLD:
            self._samples[best_i].append(q)
            self._centroids[best_i] = _l2_normalize(
                np.mean(np.stack(self._samples[best_i]), axis=0)
            )
            return self._labels[best_i], best_score
        label = self._next_label()
        self._labels.append(label)
        self._centroids.append(q)
        self._samples.append([q])
        return label, 1.0

    def pop_cluster(self, label: str) -> Optional[list[np.ndarray]]:
        try:
            i = self._labels.index(label)
        except ValueError:
            return None
        samples = self._samples.pop(i)
        self._labels.pop(i)
        self._centroids.pop(i)
        return samples

    def samples_for(self, label: str) -> Optional[list[np.ndarray]]:
        """Read-only access to a cluster's samples; does not remove it."""
        try:
            i = self._labels.index(label)
        except ValueError:
            return None
        return list(self._samples[i])

    def labels(self) -> list[str]:
        return list(self._labels)
