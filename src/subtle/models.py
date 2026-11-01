"""Whisper model aliases and local-cache lookup (no heavy imports)."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "small.en"

# alias -> (huggingface repo, download size, note), smallest/fastest first
MODELS: dict[str, tuple[str, str, str]] = {
    "tiny":     ("Systran/faster-whisper-tiny", "75 MB", "multilingual, fastest, quick tests only"),
    "base":     ("Systran/faster-whisper-base", "145 MB", "multilingual, very fast, decent: 4.4% WER on pilot VO"),
    "base.en":  ("Systran/faster-whisper-base.en", "145 MB", "English only, very fast, a bit better than base for English"),
    "small":    ("Systran/faster-whisper-small", "480 MB", "multilingual, fast, good"),
    "small.en": ("Systran/faster-whisper-small.en", "480 MB", "English only, fast, good: 2.2% WER on pilot VO"),
    "medium":   ("Systran/faster-whisper-medium", "1.5 GB", "multilingual, slow, very good"),
    "turbo":    ("deepdml/faster-whisper-large-v3-turbo-ct2", "1.6 GB", "multilingual, most accurate fast model: 0.7% WER, ~3x slower than small.en"),
    "large-v3": ("Systran/faster-whisper-large-v3", "3.1 GB", "multilingual, highest accuracy, slowest"),
}


def resolve(name: str) -> str:
    """Alias -> HF repo id. Local paths and unknown repo ids pass through."""
    return MODELS[name][0] if name in MODELS else name


def hub_cache() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    home = os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")
    return Path(home) / "hub"


def is_cached(name: str) -> bool:
    repo = resolve(name)
    if Path(repo).is_dir():
        return (Path(repo) / "model.bin").exists()
    snaps = hub_cache() / f"models--{repo.replace('/', '--')}" / "snapshots"
    return any(snaps.glob("*/model.bin"))
