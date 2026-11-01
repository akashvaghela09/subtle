# subtle

Turn any audio or video file into YouTube-ready subtitle files. It runs locally on
Whisper (faster-whisper), works offline, and needs no API keys.

```
subtle run episode.wav            # → episode.srt, ready to upload to YouTube Studio
```

## Install

```bash
pipx install -e ~/myDrive/subtle   # makes `subtle` available everywhere
subtle doctor                      # check the system
subtle setup                       # auto-install anything missing (asks first)
```

If something can't be installed automatically, `subtle setup --guide` (also in
[SETUP.md](SETUP.md)) gives manual steps.

## Usage

| Command | What it does |
|---|---|
| `subtle` / `subtle ui [folder]` | Full-screen file browser → pick an audio/video file → options → transcribe |
| `subtle run <files…>` | Transcribe and write subtitle files |
| `subtle doctor [--json]` | Health check: Python, Whisper engine, model, ffmpeg, GPU, disk |
| `subtle setup [-y] [--only engine,model,ffmpeg,cuda]` | Install anything missing |
| `subtle setup --guide` | Manual setup instructions |
| `subtle formats` / `subtle models` | List output formats / Whisper models |
| `subtle --help` | Full reference |

### Interactive mode

Run `subtle` in any folder. It opens a full-screen browser in the same style as tubeline.

| Screen | Keys |
|---|---|
| **Files**: folders, audio (♪) and video (▶); `✓ srt` marks files already done | `Enter` open · `←`/`Backspace` up · `/` filter · `a` show other files · `.` hidden · `~` home · `^D` doctor · `q` quit |
| **Options**: formats, style (Standard / Compact / Shorts), model, language, names hint, save folder | `↑↓` field · `←→` change · `space` toggle format · `e` type a value · `Enter` transcribe · `Esc` back |
| **Transcribe**: progress bar with time left; captions appear live | `Esc` cancel |
| **Done**: output paths and the YouTube upload hint | `Enter` back to files · `n` next file · `o` open folder |

The model loads once per session, so later files start immediately. Your last options are
remembered in `~/.config/subtle/tui.json`.

### Examples

```bash
subtle run ep1.wav                               # SRT next to the input
subtle run ep1.mp4 -f srt,vtt,txt -o subs/       # several formats, custom folder
subtle run ep1.wav -f all --lang en              # every format, skip language detection
subtle run ep1.wav -p "Names: Zodiac, SFPD"      # help Whisper spell names
subtle run short.mp4 -f ass --words 3            # Shorts-style 3-word captions
ffmpeg -i short.mp4 -vf ass=short.ass out.mp4    # burn those captions into the video
```

### Output formats (`-f`)

| Format | Use |
|---|---|
| `srt` | YouTube upload (default) |
| `vtt` | YouTube / web players |
| `txt` | Plain transcript in paragraphs |
| `json` | Segments, word-level timings and cues (for Remotion or other tools) |
| `ass` | Styled captions (bold white, black outline) for burning in with ffmpeg |

### Caption shaping

| Flag | Default | Meaning |
|---|---|---|
| `--max-chars` | 42 | Characters per line (YouTube's guideline) |
| `--max-lines` | 2 | Lines per caption |
| `--max-duration` | 6.0 | Max seconds on screen |
| `-w, --words N` | off | Shorts mode: N words per caption, single line |

Captions break at sentence ends, natural clause breaks and pauses, never mid-word.

## For AI agents and scripts

```bash
subtle doctor --json                    # {"ready": true, "checks": [...]}
subtle run a.wav b.mp3 -f srt,json --json-out
# stdout: {"ok": true, "files": [{"input", "outputs": {"srt": path, …}, "language", "duration", "cues", "seconds"}]}
```

- Progress and logs go to **stderr**; stdout contains only the JSON.
- No prompts are shown when arguments are given.
- Exit codes: `0` ok · `1` transcription error · `2` bad arguments · `3` missing dependency.

## Performance (GTX 1650, `turbo` model, 3 min of audio)

| Device | Time |
|---|---|
| GPU, `int8_float16` (default on GPU) | ~22 s |
| GPU, `float16` | ~74 s |
| CPU, `int8`, 16 threads | ~84 s |

## Layout

```
src/subtle/
  cli.py      commands, help text, run pipeline
  tui.py      full-screen browser (Textual): files → options → run → done, plus doctor
  engine.py   faster-whisper wrapper, ffmpeg decoding, GPU detect + CPU fallback
  cues.py     words → readable caption cues
  writers.py  srt / vtt / txt / json / ass
  doctor.py   checks, auto-setup, manual guide
  models.py   model aliases + cache lookup
```
