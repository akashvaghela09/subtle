"""Interactive mode: run `subtle` with no arguments."""
from __future__ import annotations

from pathlib import Path

import questionary
import typer

from subtle import __version__
from subtle.models import DEFAULT_MODEL, MODELS, is_cached
from subtle.writers import FORMATS

STYLES = {
    "Standard: YouTube captions, up to 2 lines": dict(max_chars=42, max_lines=2, words=None),
    "Compact: 1 line per caption": dict(max_chars=42, max_lines=1, words=None),
    "Shorts: 3 words at a time": dict(max_chars=30, max_lines=1, words=3),
}


def _status_line() -> tuple[str, bool]:
    from subtle.doctor import run_checks
    checks = run_checks()
    ready = all(c.ok for c in checks if c.required)
    parts = [("✓ " if c.ok else "✗ ") + c.name for c in checks]
    return " · ".join(parts), ready


def transcribe_flow() -> None:
    from subtle.cli import err, transcribe_files
    raw = questionary.path("Audio/video file:").ask()
    if not raw:
        return
    f = Path(raw.strip().strip("'\"")).expanduser()
    if not f.is_file():
        err.print(f"[red]Not a file: {f}[/]")
        return
    fmts = questionary.checkbox(
        "Output formats (space to toggle):",
        choices=[questionary.Choice(f"{k:<5} {v[:60]}", value=k, checked=(k == "srt"))
                 for k, v in FORMATS.items()]).ask()
    if not fmts:
        return
    style = questionary.select("Caption style:", choices=list(STYLES)).ask()
    if not style:
        return
    model = questionary.select(
        "Model:", default=next(c for c in _model_choices() if c.value == DEFAULT_MODEL),
        choices=_model_choices()).ask()
    if not model:
        return
    lang = questionary.text("Language code (blank = auto-detect, e.g. en, hi):").ask()
    if lang is None:
        return
    prompt = questionary.text("Names/terms to spell correctly (optional):").ask()
    try:
        transcribe_files([f], fmts, model=model, lang=lang.strip() or None,
                         prompt=(prompt or "").strip() or None, **STYLES[style])
    except typer.Exit:
        pass
    except Exception as e:  # noqa: BLE001
        err.print(f"[red]Failed:[/] {e}")


def _model_choices():
    return [questionary.Choice(f"{n:<9} {s:>7}  {'✓ downloaded' if is_cached(n) else '  (will download)'}  {note}",
                               value=n) for n, (_, s, note) in MODELS.items()]


def main_menu() -> None:
    from subtle.cli import err, formats, models, print_checks, setup
    from subtle.doctor import run_checks
    while True:
        status, ready = _status_line()
        err.rule(f"[bold]subtle {__version__}[/]: subtitles for YouTube")
        err.print(f"[dim]{status}[/]")
        if not ready:
            err.print("[yellow]Something required is missing. Choose 'Fix setup'.[/]")
        choice = questionary.select("What do you want to do?", choices=[
            "Transcribe a file", "Check system (doctor)", "Fix setup (install missing)",
            "Show formats", "Show models", "Quit"]).ask()
        if choice in (None, "Quit"):
            return
        try:
            if choice == "Transcribe a file":
                transcribe_flow()
            elif choice.startswith("Check"):
                print_checks(run_checks())
            elif choice.startswith("Fix"):
                setup(yes=False, guide=False, only=None, model=DEFAULT_MODEL)
            elif choice == "Show formats":
                formats()
            elif choice == "Show models":
                models()
        except typer.Exit:
            pass
        questionary.press_any_key_to_continue().ask()
