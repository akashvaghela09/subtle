"""subtle: audio/video -> YouTube-ready subtitle files."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table
from typing_extensions import Annotated

from subtle import __version__
from subtle.models import DEFAULT_MODEL, MODELS, is_cached

err = Console(stderr=True)  # all human UI goes to stderr; stdout stays clean for --json-out
out = Console()

EPILOG = """\
[bold]Quick start[/]
  subtle  /  subtle ui <folder>           full-screen file browser → pick a file → transcribe
  subtle run episode.wav                  writes episode.srt next to the file
  subtle run ep.mp4 -f srt,vtt,txt -o subs/
  subtle run ep.wav -f all --lang en --prompt "Names: Zodiac, SFPD"
  subtle run short.mp4 -f ass --words 3   Shorts-style 1-3 word captions
  subtle doctor  /  subtle setup          check / fix the system

[bold]For AI agents & scripts[/]
  1. `subtle doctor --json`  ->  {"ready": true|false, "checks": [...]}
  2. `subtle run <files> -f <fmts> --json-out`  ->  stdout is JSON:
     {"ok": true, "files": [{"input", "outputs": {fmt: path}, "language", "duration", "cues", "seconds"}]}
  All progress/logs go to stderr. No prompts are shown when arguments are given.
  Exit codes: 0 ok · 1 transcription error · 2 bad arguments · 3 missing dependency
"""

app = typer.Typer(
    help="[bold]subtle[/]: turn any audio/video file into YouTube-ready subtitles "
         "(SRT, VTT, TXT, JSON, ASS) with local Whisper. Offline, no API keys.",
    epilog=EPILOG, rich_markup_mode="rich", add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version(v: bool):
    if v:
        out.print(f"subtle {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context,
         version: Annotated[bool, typer.Option("--version", "-V", callback=_version,
                                               is_eager=True, help="Show version.")] = False):
    if ctx.invoked_subcommand is None:
        if sys.stdin.isatty() and sys.stdout.isatty():
            from subtle.tui import run_tui
            run_tui(Path.cwd())
        else:
            out.print(ctx.get_help())


def parse_formats(spec: str) -> list[str]:
    from subtle.writers import WRITERS
    fmts = list(WRITERS) if spec.strip().lower() == "all" else \
        [f.strip().lower().lstrip(".") for f in spec.split(",") if f.strip()]
    bad = [f for f in fmts if f not in WRITERS]
    if bad or not fmts:
        err.print(f"[red]Unknown format(s): {', '.join(bad) or spec}[/]. "
                  f"Choose from: {', '.join(WRITERS)}, all")
        raise typer.Exit(2)
    return list(dict.fromkeys(fmts))


def transcribe_files(files: list[Path], formats: list[str], out_dir: Optional[Path] = None,
                     model: str = DEFAULT_MODEL, lang: Optional[str] = None, device: str = "auto",
                     compute: Optional[str] = None, max_chars: int = 42, max_lines: int = 2,
                     max_duration: float = 6.0, words: Optional[int] = None,
                     prompt: Optional[str] = None, beam: int = 5, vad: bool = True) -> list[dict]:
    """Core pipeline shared by `run` and the TUI. Raises on failure."""
    import importlib.util
    if importlib.util.find_spec("faster_whisper") is None:
        err.print("[red]Whisper engine (faster-whisper) is not installed.[/] "
                  "Run [bold]subtle setup[/] or see [bold]subtle setup --guide[/].")
        raise typer.Exit(3)
    from subtle.engine import Transcriber
    from subtle.writers import write_all

    if not is_cached(model):
        err.print(f"[yellow]Model '{model}' isn't downloaded yet; downloading it now "
                  f"({MODELS.get(model, ('', '?'))[1]}).[/]")
    with err.status(f"Loading model [bold]{model}[/]…"):
        tr = Transcriber(model, device=device, compute=compute,
                         warn=lambda m: err.print(f"[yellow]{m}[/]"))
    err.print(f"Model [bold]{model}[/] on [bold]{tr.device.upper()}[/]")

    results = []
    for f in files:
        t0 = time.time()
        with Progress(TextColumn("[bold]{task.description}"), BarColumn(),
                      TextColumn("{task.percentage:>3.0f}%"), TimeRemainingColumn(),
                      console=err, transient=True) as bar:
            task = bar.add_task(f.name[:40], total=1.0)
            res = tr.transcribe(str(f), language=lang, prompt=prompt, beam=beam, vad=vad,
                                on_progress=lambda done, total: bar.update(
                                    task, completed=done / total if total else 1))
        res["source"], res["model"] = str(f), model
        outputs, cues = write_all(res, formats, f, out_dir, max_chars=max_chars,
                                  max_lines=max_lines, max_duration=max_duration, max_words=words)
        secs = round(time.time() - t0, 1)
        err.print(f"[green]✓[/] {f.name}: {res['duration']:.0f}s audio, lang={res['language']}, "
                  f"{len(cues)} cues, {secs}s")
        for p in outputs.values():
            err.print(f"   → {p}", soft_wrap=True, highlight=False)
        results.append({"input": str(f.resolve()), "outputs": outputs, "language": res["language"],
                        "duration": res["duration"], "cues": len(cues), "seconds": secs})
    return results


@app.command()
def run(
    files: Annotated[List[Path], typer.Argument(help="Audio/video file(s): wav, mp3, m4a, mp4, mkv…",
                                                exists=True, dir_okay=False, readable=True)],
    format: Annotated[str, typer.Option("-f", "--format",
                                        help="Comma list: srt,vtt,txt,json,ass, or 'all'.")] = "srt",
    out_dir: Annotated[Optional[Path], typer.Option("-o", "--out",
                                                    help="Output folder \\[default: next to input].")] = None,
    model: Annotated[str, typer.Option("-m", "--model",
                                       help="Model alias (see `subtle models`), HF repo, or local path.")] = DEFAULT_MODEL,
    lang: Annotated[Optional[str], typer.Option("-l", "--lang",
                                                help="Language code (en, hi, es…) \\[default: auto-detect].")] = None,
    max_chars: Annotated[int, typer.Option(help="Max characters per caption line.")] = 42,
    max_lines: Annotated[int, typer.Option(help="Max lines per caption.")] = 2,
    max_duration: Annotated[float, typer.Option(help="Max seconds a caption stays on screen.")] = 6.0,
    words: Annotated[Optional[int], typer.Option("-w", "--words",
                                                 help="Shorts mode: N words per caption, one line (e.g. 3).")] = None,
    prompt: Annotated[Optional[str], typer.Option("-p", "--prompt",
                                                  help="Hint text for spelling names/jargon.")] = None,
    device: Annotated[str, typer.Option(help="auto | cuda | cpu")] = "auto",
    compute: Annotated[Optional[str], typer.Option(
        help="CTranslate2 compute type, e.g. float16, int8_float16, int8 \\[default: int8_float16 on GPU, int8 on CPU].")] = None,
    beam: Annotated[int, typer.Option(help="Beam size (higher = slightly better, slower).")] = 5,
    vad: Annotated[bool, typer.Option("--vad/--no-vad", help="Skip silence and music (recommended).")] = True,
    json_out: Annotated[bool, typer.Option("--json-out", help="Print a machine-readable JSON result on stdout.")] = False,
):
    """Transcribe file(s) and write subtitle files."""
    fmts = parse_formats(format)
    if device not in ("auto", "cuda", "cpu"):
        err.print("[red]--device must be auto, cuda or cpu[/]")
        raise typer.Exit(2)
    try:
        results = transcribe_files(files, fmts, out_dir, model, lang, device, compute, max_chars,
                                   max_lines, max_duration, words, prompt, beam, vad)
    except typer.Exit:
        raise
    except Exception as e:  # noqa: BLE001 (report any engine failure cleanly)
        if json_out:
            out.print_json(json.dumps({"ok": False, "error": str(e)}))
        err.print(f"[red]Failed:[/] {e}\nTry [bold]subtle doctor[/] to check your setup.")
        raise typer.Exit(1)
    if json_out:
        out.print_json(json.dumps({"ok": True, "files": results}))


@app.command()
def ui(path: Annotated[Path, typer.Argument(help="Folder to start in.", exists=True,
                                            file_okay=False)] = Path(".")):
    """Full-screen file browser: pick an audio/video file and transcribe it (same as bare `subtle`)."""
    from subtle.tui import run_tui
    run_tui(path.resolve())


@app.command()
def doctor(
    model: Annotated[str, typer.Option("-m", "--model", help="Model to check for.")] = DEFAULT_MODEL,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
):
    """Check that everything subtle needs is installed (ffmpeg, Whisper, model, GPU)."""
    from subtle.doctor import checks_json, run_checks
    checks = run_checks(model)
    if as_json:
        out.print_json(json.dumps(checks_json(checks)))
    else:
        print_checks(checks)
    if not all(c.ok for c in checks if c.required):
        raise typer.Exit(3)


def print_checks(checks) -> None:
    t = Table(title="subtle doctor", show_lines=False)
    t.add_column(""), t.add_column("component"), t.add_column("status"), t.add_column("needed")
    for c in checks:
        mark = "[green]✓[/]" if c.ok else ("[red]✗[/]" if c.required else "[yellow]![/]")
        t.add_row(mark, c.name, c.status, "required" if c.required else "optional")
    err.print(t)
    if any(c.fix for c in checks):
        err.print("Fix automatically: [bold]subtle setup[/]   ·   manual steps: [bold]subtle setup --guide[/]")
    else:
        err.print("[green]All good. Ready to transcribe.[/]")


@app.command()
def setup(
    yes: Annotated[bool, typer.Option("-y", "--yes", help="Don't ask; install everything missing.")] = False,
    guide: Annotated[bool, typer.Option("--guide", help="Print the manual setup guide instead.")] = False,
    only: Annotated[Optional[str], typer.Option(help="Only fix these: engine,model,ffmpeg,cuda")] = None,
    model: Annotated[str, typer.Option("-m", "--model", help="Model to download.")] = DEFAULT_MODEL,
):
    """Install missing components automatically (asks first). Falls back to the manual guide."""
    from subtle.doctor import GUIDE, download_model, plan_fixes, run_checks
    if guide:
        out.print(GUIDE, markup=False, highlight=False)
        return
    plan = plan_fixes(run_checks(model), model)
    if only:
        keep = {k.strip() for k in only.split(",")}
        plan = [p for p in plan if p[0] in keep]
    if not plan:
        err.print("[green]Nothing to fix. Everything is installed.[/]")
        return
    err.print("[bold]subtle setup will:[/]")
    for _, desc, cmd in plan:
        err.print(f"  • {desc}" + (f"\n      [dim]{' '.join(cmd)}[/]" if cmd else ""))
    if not yes:
        if not sys.stdin.isatty():
            err.print("[yellow]Not a terminal. Re-run with --yes to proceed.[/]")
            raise typer.Exit(2)
        if not typer.confirm("Proceed?", default=True, err=True):
            raise typer.Exit()
    failed = []
    for key, desc, cmd in plan:
        err.rule(desc)
        try:
            if key == "model":
                download_model(model)
            elif cmd is None:
                raise RuntimeError("no supported package manager found")
            else:
                subprocess.run(cmd, check=True)
            err.print(f"[green]✓ {desc}[/]")
        except Exception as e:  # noqa: BLE001
            err.print(f"[red]✗ {desc}: {e}[/]")
            failed.append(key)
    if failed:
        err.print(f"\n[yellow]Some steps failed ({', '.join(failed)}). Manual steps follow:[/]\n")
        out.print(GUIDE, markup=False, highlight=False)
        raise typer.Exit(3)
    err.print("\n[green]Setup complete.[/] Run [bold]subtle doctor[/] to verify.")


@app.command()
def formats():
    """List output formats and what each is for."""
    from subtle.writers import FORMATS
    t = Table(title="Output formats  (-f srt,vtt,… or -f all)")
    t.add_column("format", style="bold"), t.add_column("use")
    for k, v in FORMATS.items():
        t.add_row(k, v)
    out.print(t)


@app.command()
def models():
    """List Whisper models and which are already downloaded."""
    t = Table(title="Whisper models  (-m <name>)")
    for col in ("name", "downloaded", "size", "notes"):
        t.add_column(col)
    for name, (_, size, note) in MODELS.items():
        t.add_row(name + (" *" if name == DEFAULT_MODEL else ""),
                  "[green]yes[/]" if is_cached(name) else "no", size, note)
    out.print(t)
    out.print("[dim]* default. Any faster-whisper HF repo id or local model folder also works.[/]")


def main():
    app()


if __name__ == "__main__":
    main()
