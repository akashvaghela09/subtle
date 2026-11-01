# subtle

Turn any audio or video file into YouTube-ready subtitles (SRT, VTT, TXT, JSON, ASS).
Runs locally on Whisper (faster-whisper): offline, no API keys.

## Install

```bash
pipx install git+https://github.com/akashvaghela09/subtle.git
subtle doctor     # check the system
subtle setup      # install anything missing (asks first)
```

Manual steps: [SETUP.md](SETUP.md) or `subtle setup --guide`.

## Use

```bash
subtle                                   # full-screen file browser
subtle run episode.wav                   # → episode.srt next to the input
subtle run ep1.mp4 -f srt,vtt -o subs/   # several formats, custom folder
subtle run short.mp4 -f ass --words 3    # Shorts-style captions
```

Default model is `small.en`; pick another with `-m` (`base`, `turbo`, `large-v3`, …).
See `subtle models` and `subtle formats`.

## Reference

`subtle --help` for a command overview, or `subtle docs` for the full reference
(every option, JSON output and exit code), written for scripts and AI agents.
