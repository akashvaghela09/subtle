"""Whisper model aliases and local-cache lookup (no heavy imports)."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "turbo"

# alias -> (huggingface repo, download size, note)
MODELS: dict[str, tuple[str, str, str]] = {
    "turbo":    ("deepdml/faster-whisper-large-v3-turbo-ct2", "1.6 GB", "best speed/accuracy, multilingual (default)"),
    "large-v3": ("Systran/faster-whisper-large-v3", "3.1 GB", "highest accuracy, slowest"),
    "medium":   ("Systran/faster-whisper-medium", "1.5 GB", "multilingual, slower than turbo"),
    "small":    ("Systran/faster-whisper-small", "480 MB", "multilingual, fast"),
    "small.en": ("Systran/faster-whisper-small.en", "480 MB", "English only, fast"),
    "base.en":  ("Systran/faster-whisper-base.en", "145 MB", "English only, very fast, rough"),
    "tiny":     ("Systran/faster-whisper-tiny", "75 MB", "multilingual, quick tests only"),
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
