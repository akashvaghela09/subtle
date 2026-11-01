"""`subtle doctor` checks, `subtle setup` auto-fixes, and the manual setup guide."""
from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass

from subtle.models import DEFAULT_MODEL, MODELS, hub_cache, is_cached, resolve

CUDA_PKGS = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9,<10"]


@dataclass
class Check:
    name: str
    ok: bool
    required: bool
    status: str
    fix: str = ""  # key into FIXES, empty when nothing to do


def _has_nvidia_gpu() -> str:
    if not shutil.which("nvidia-smi"):
        return ""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else ""
    except Exception:
        return ""


def run_checks(model: str = DEFAULT_MODEL) -> list[Check]:
    checks = []
    py = sys.version_info
    checks.append(Check("python", py >= (3, 9), True, f"{platform.python_version()} (needs >= 3.9)"))

    fw = importlib.util.find_spec("faster_whisper") is not None
    if fw:
        from importlib.metadata import version
        status = f"faster-whisper {version('faster-whisper')}"
    else:
        status = "not installed"
    checks.append(Check("whisper engine", fw, True, status, "" if fw else "engine"))

    if is_cached(model):
        checks.append(Check("model", True, True, f"'{model}' downloaded"))
    else:
        size = MODELS[model][1] if model in MODELS else "?"
        # not blocking: faster-whisper downloads it automatically on first run
        checks.append(Check("model", False, False, f"'{model}' not downloaded yet ({size}); "
                            "downloads automatically on first run", "model"))

    ff = shutil.which("ffmpeg")
    if ff:
        v = subprocess.run([ff, "-version"], capture_output=True, text=True).stdout.split("\n")[0]
        checks.append(Check("ffmpeg", True, False, " ".join(v.split()[:3])))
    else:
        checks.append(Check("ffmpeg", False, False,
                            "not found (recommended: most robust audio decoding, "
                            "and burning .ass captions into video)", "ffmpeg"))

    gpu = _has_nvidia_gpu()
    if not gpu:
        checks.append(Check("gpu", True, False, "no NVIDIA GPU, so CPU mode (works, just slower)"))
    else:
        from subtle.engine import cuda_usable
        if fw and cuda_usable():
            checks.append(Check("gpu", True, False, f"{gpu}, CUDA ready"))
        else:
            checks.append(Check("gpu", False, False,
                                f"{gpu} found, but CUDA libs are missing, so CPU mode", "cuda"))

    free = shutil.disk_usage(hub_cache() if hub_cache().exists() else "/").free / 1e9
    checks.append(Check("disk", free > 4, False, f"{free:.1f} GB free in model cache"))
    return checks


def checks_json(checks: list[Check]) -> dict:
    return {"ready": all(c.ok for c in checks if c.required),
            "checks": [asdict(c) for c in checks]}


# ---------------------------------------------------------------- setup actions

def _pip(*pkgs: str) -> list[str]:
    return [sys.executable, "-m", "pip", "install", "--upgrade", *pkgs]


def ffmpeg_cmd() -> list[str] | None:
    system = platform.system()
    if system == "Linux":
        for mgr, cmd in (("apt-get", ["sudo", "apt-get", "install", "-y", "ffmpeg"]),
                         ("dnf", ["sudo", "dnf", "install", "-y", "ffmpeg"]),
                         ("pacman", ["sudo", "pacman", "-S", "--noconfirm", "ffmpeg"])):
            if shutil.which(mgr):
                return cmd
    if system == "Darwin" and shutil.which("brew"):
        return ["brew", "install", "ffmpeg"]
    if system == "Windows" and shutil.which("winget"):
        return ["winget", "install", "-e", "--id", "Gyan.FFmpeg"]
    return None


def plan_fixes(checks: list[Check], model: str) -> list[tuple[str, str, list[str] | None]]:
    """Returns [(key, description, command or None for python-side action)]."""
    plan = []
    for c in checks:
        if c.fix == "engine":
            plan.append(("engine", "Install faster-whisper (~150 MB)", _pip("faster-whisper")))
        elif c.fix == "cuda":
            plan.append(("cuda", "Install NVIDIA CUDA libs for GPU speed (~1.2 GB)", _pip(*CUDA_PKGS)))
        elif c.fix == "ffmpeg":
            plan.append(("ffmpeg", "Install ffmpeg (system package, may ask for sudo password)",
                         ffmpeg_cmd()))
        elif c.fix == "model":
            size = MODELS[model][1] if model in MODELS else "?"
            plan.append(("model", f"Download Whisper model '{model}' ({size})", None))
    return plan


def download_model(model: str) -> None:
    from huggingface_hub import snapshot_download
    snapshot_download(resolve(model))


# ---------------------------------------------------------------- manual guide

GUIDE = """\
# subtle: manual setup guide

Use this if `subtle setup` cannot fix something automatically, for example
when you have no sudo, no internet, or an unusual OS.
Run `subtle doctor` after each step to confirm it worked.

## 1. Python >= 3.9 and subtle itself
  Linux (Debian/Ubuntu):  sudo apt install python3 pipx && pipx ensurepath
  macOS:                  brew install python pipx && pipx ensurepath
  Windows:                winget install Python.Python.3.12  then  py -m pip install --user pipx
  Then, from the subtle folder:   pipx install -e .

## 2. Whisper engine (faster-whisper)
  Installed automatically with subtle. If it's missing:
    pipx inject subtle faster-whisper

## 3. Whisper model
  Downloads automatically on the first `subtle run`. To fetch it ahead of time:
    subtle setup --only model
  Offline machine: copy ~/.cache/huggingface/hub/models--Systran--faster-whisper-base (or another model)
  from a machine that already has it into the same path.
  You can also point --model at any local folder that contains model.bin.

## 4. ffmpeg (optional, used to burn .ass captions into a video)
  Debian/Ubuntu: sudo apt install ffmpeg
  Fedora:        sudo dnf install ffmpeg
  Arch:          sudo pacman -S ffmpeg
  macOS:         brew install ffmpeg
  Windows:       winget install Gyan.FFmpeg      (or download from https://ffmpeg.org/download.html and add bin/ to PATH)

## 5. GPU acceleration (optional, NVIDIA only)
  Needs an NVIDIA driver (`nvidia-smi` must work), plus the CUDA 12 cuBLAS and cuDNN 9 libraries:
    pipx inject subtle nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
  subtle loads these automatically; you don't need to set LD_LIBRARY_PATH.
  If the GPU still fails, subtle falls back to CPU. To force CPU: subtle run file.wav --device cpu
  Low-VRAM cards (<4 GB): use --model small. Newer cards (RTX) may be faster with --compute float16.

## Troubleshooting
  "model.bin not found"     -> the download was interrupted. Delete the model folder in
                               ~/.cache/huggingface/hub and run again.
  "CUDA out of memory"      -> use --model small, or --device cpu
  Wrong language detected   -> pass --lang en (or hi, es, ...)
  Names spelled wrong       -> pass --prompt "Names: Ted Bundy, Zodiac, SFPD"
"""
