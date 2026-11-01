"""Transcription via faster-whisper, with GPU auto-detect and CPU fallback."""
from __future__ import annotations

import ctypes
import glob
import os
from typing import Callable, Optional

from subtle.models import resolve


def preload_cuda_libs() -> bool:
    """Load pip-installed NVIDIA libs (nvidia-cublas-cu12 / nvidia-cudnn-cu12) so
    CTranslate2 can find them without LD_LIBRARY_PATH. Returns True if any loaded."""
    try:
        import nvidia  # namespace package from the nvidia-* wheels
    except ImportError:
        return False
    libs = []
    for root in list(getattr(nvidia, "__path__", [])):
        for sub in ("cublas", "cudnn", "cuda_nvrtc"):
            libs += sorted(glob.glob(os.path.join(root, sub, "lib", "lib*.so*")))
    pending, loaded = libs, 0
    # libs depend on each other; retry passes until nothing new loads
    while pending:
        failed = []
        for p in pending:
            try:
                ctypes.CDLL(p, mode=ctypes.RTLD_GLOBAL)
                loaded += 1
            except OSError:
                failed.append(p)
        if len(failed) == len(pending):
            break
        pending = failed
    return loaded > 0


def cuda_device_count() -> int:
    try:
        preload_cuda_libs()
        import ctranslate2
        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


def cuda_usable() -> bool:
    """A GPU is visible AND the cuBLAS/cuDNN libs CTranslate2 needs can load."""
    if cuda_device_count() == 0:
        return False
    for lib in ("libcublas.so.12", "libcudnn_ops.so.9"):
        try:
            ctypes.CDLL(lib)
        except OSError:
            return False
    return True


SAMPLE_RATE = 16000


def load_audio(path: str):
    """Decode any audio/video to 16 kHz mono float32. Uses ffmpeg when present
    (most robust), otherwise faster-whisper's bundled PyAV decoder."""
    import shutil
    import subprocess

    import numpy as np
    if shutil.which("ffmpeg"):
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-vn", "-ac", "1",
             "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"], capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg could not decode {path}: {proc.stderr.decode()[-300:]}")
        return np.frombuffer(proc.stdout, np.float32)
    from faster_whisper import decode_audio
    return decode_audio(path, sampling_rate=SAMPLE_RATE)


class Cancelled(Exception):
    """Raised by a callback to stop a transcription early."""


class Transcriber:
    def __init__(self, model: str, device: str = "auto", compute: Optional[str] = None,
                 warn: Callable[[str], None] = print):
        self.model_name, self.compute, self.warn = model, compute, warn
        if device == "auto":
            device = "cuda" if cuda_usable() else "cpu"
        self._load(device)

    def _load(self, device: str):
        from faster_whisper import WhisperModel
        compute = self.compute or ("int8_float16" if device == "cuda" else "int8")
        self.device = device
        self.model = WhisperModel(resolve(self.model_name), device=device, compute_type=compute,
                                  cpu_threads=os.cpu_count() or 4)

    def transcribe(self, path: str, language: Optional[str] = None, prompt: Optional[str] = None,
                   beam: int = 5, vad: bool = True,
                   on_progress: Optional[Callable[[float, float], None]] = None,
                   on_segment: Optional[Callable[[dict], None]] = None) -> dict:
        """on_segment gets each finished segment; raise Cancelled from it to stop early."""
        audio = load_audio(path)
        try:
            return self._run(audio, language, prompt, beam, vad, on_progress, on_segment)
        except RuntimeError as e:
            if self.device != "cuda":
                raise
            self.warn(f"GPU failed ({str(e).splitlines()[0]}); retrying on CPU. "
                      "Run `subtle doctor` to fix GPU setup.")
            self._load("cpu")
            return self._run(audio, language, prompt, beam, vad, on_progress, on_segment)

    def _run(self, path, language, prompt, beam, vad, on_progress, on_segment) -> dict:
        seg_iter, info = self.model.transcribe(
            path, language=language, initial_prompt=prompt, beam_size=beam,
            vad_filter=vad, word_timestamps=True, condition_on_previous_text=False,
        )
        segments = []
        for s in seg_iter:
            words: list[dict] = []
            for w in s.words or []:
                if not w.word.strip():
                    continue
                # Whisper splits tokens like "4" ",000" or "9" ".42"; a piece without a
                # leading space continues the previous word.
                if words and not w.word.startswith(" "):
                    words[-1]["word"] += w.word.strip()
                    words[-1]["end"] = round(w.end, 3)
                    words[-1]["prob"] = round(min(words[-1]["prob"], w.probability), 3)
                    continue
                words.append({"start": round(w.start, 3), "end": round(w.end, 3),
                              "word": w.word.strip(), "prob": round(w.probability, 3)})
            segments.append({"start": round(s.start, 3), "end": round(s.end, 3),
                             "text": s.text.strip(), "words": words})
            if on_segment:
                on_segment(segments[-1])
            if on_progress:
                on_progress(s.end, info.duration)
        if on_progress:
            on_progress(info.duration, info.duration)
        return {"language": info.language, "language_prob": round(info.language_probability, 3),
                "duration": round(info.duration, 3), "segments": segments}
