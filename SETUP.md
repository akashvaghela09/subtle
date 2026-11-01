# subtle: manual setup guide

Use this if `subtle setup` cannot fix something automatically, for example
when you have no sudo, no internet, or an unusual OS.
Run `subtle doctor` after each step to confirm it worked.

## 1. Python >= 3.9 and subtle itself
  Linux (Debian/Ubuntu):  sudo apt install python3 pipx && pipx ensurepath
  macOS:                  brew install python pipx && pipx ensurepath
  Windows:                winget install Python.Python.3.12  then  py -m pip 
install --user pipx
  Then, from the subtle folder:   pipx install -e .

## 2. Whisper engine (faster-whisper)
  Installed automatically with subtle. If it's missing:
    pipx inject subtle faster-whisper

## 3. Whisper model
  Downloads automatically on the first `subtle run`. To fetch it ahead of time:
    subtle setup --only model
  Offline machine: copy 
~/.cache/huggingface/hub/models--deepdml--faster-whisper-large-v3-turbo-ct2
  from a machine that already has it into the same path.
  You can also point --model at any local folder that contains model.bin.

## 4. ffmpeg (optional, used to burn .ass captions into a video)
  Debian/Ubuntu: sudo apt install ffmpeg
  Fedora:        sudo dnf install ffmpeg
  Arch:          sudo pacman -S ffmpeg
  macOS:         brew install ffmpeg
  Windows:       winget install Gyan.FFmpeg      (or download from 
https://ffmpeg.org/download.html and add bin/ to PATH)

## 5. GPU acceleration (optional, NVIDIA only)
  Needs an NVIDIA driver (`nvidia-smi` must work), plus the CUDA 12 cuBLAS and 
cuDNN 9 libraries:
    pipx inject subtle nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
  subtle loads these automatically; you don't need to set LD_LIBRARY_PATH.
  If the GPU still fails, subtle falls back to CPU. To force CPU: subtle run 
file.wav --device cpu
  Low-VRAM cards (<4 GB): use --model small. Newer cards (RTX) may be faster 
with --compute float16.

## Troubleshooting
  "model.bin not found"     -> the download was interrupted. Delete the model 
folder in
                               ~/.cache/huggingface/hub and run again.
  "CUDA out of memory"      -> use --model small, or --device cpu
  Wrong language detected   -> pass --lang en (or hi, es, ...)
  Names spelled wrong       -> pass --prompt "Names: Ted Bundy, Zodiac, SFPD"

