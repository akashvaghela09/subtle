"""Full-screen interactive mode (`subtle` / `subtle ui`): browse → options → transcribe → done.

Look and keys follow tubeline: breadcrumb header, cursor-bar lists, ←→ to change a setting,
a key-hint footer, Tokyo-Night palette.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from subtle import __version__
from subtle.models import DEFAULT_MODEL, MODELS, is_cached
from subtle.writers import FORMATS

# Tokyo Night, same palette as tubeline's "night" theme
C = dict(bg="#1a1b26", fg="#c0caf5", dim="#7a82a8", faint="#3b4261", accent="#7aa2f7",
         accent2="#bb9af7", green="#9ece6a", yellow="#e0af68", red="#f7768e", cursor="#283457")

AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aif", ".aiff"}
VIDEO = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".ts", ".wmv"}
SUB_BADGES = ("srt", "vtt", "ass")

STYLES = {  # key: (label, cue-shaping kwargs)
    "standard": ("Standard · 2 lines", dict(max_chars=42, max_lines=2, max_words=None)),
    "compact":  ("Compact · 1 line", dict(max_chars=42, max_lines=1, max_words=None)),
    "shorts":   ("Shorts · 3 words", dict(max_chars=30, max_lines=1, max_words=3)),
}
LANGS = ["auto", "en", "hi", "es", "fr", "de", "pt", "it", "nl", "ru", "ja", "ko", "zh", "ar", "tr"]


def _config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "subtle" / "tui.json"


@dataclass
class Opts:
    """Options screen state. Remembered between runs in ~/.config/subtle/tui.json."""
    formats: list = field(default_factory=lambda: ["srt"])
    style: str = "standard"
    model: str = DEFAULT_MODEL
    lang: str = "auto"
    prompt: str = ""
    out: str = ""  # empty = next to the file

    @classmethod
    def load(cls) -> "Opts":
        try:
            data = json.loads(_config_path().read_text())
            o = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            o.formats = [f for f in o.formats if f in FORMATS] or ["srt"]
            o.style = o.style if o.style in STYLES else "standard"
            return o
        except Exception:
            return cls()

    def save(self) -> None:
        try:
            _config_path().parent.mkdir(parents=True, exist_ok=True)
            _config_path().write_text(json.dumps(asdict(self), indent=2))
        except OSError:
            pass


# ---------------------------------------------------------------- helpers

def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def human_dur(s: Optional[float]) -> str:
    if s is None:
        return "?"
    s = int(round(s))
    return f"{s // 3600}:{s % 3600 // 60:02}:{s % 60:02}" if s >= 3600 else f"{s // 60}:{s % 60:02}"


def probe_duration(p: Path) -> Optional[float]:
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(p)], capture_output=True, text=True, timeout=10)
        return float(r.stdout.strip())
    except Exception:
        return None


def short_path(p: Path, limit: int = 60) -> str:
    """~-relative path; long ones keep the last folders: …/rnd/pilot-911/audio"""
    home = str(Path.home())
    s = str(p)
    s = "~" + s[len(home):] if s.startswith(home) else s
    if len(s) <= limit:
        return s
    parts = s.split("/")
    out = parts[-1]
    for part in reversed(parts[:-1]):
        if len(out) + len(part) + 3 > limit:
            break
        out = part + "/" + out
    return "…/" + out


def open_in_file_manager(p: Path) -> None:
    cmd = {"Darwin": "open", "Windows": "explorer"}.get(platform.system(), "xdg-open")
    try:
        subprocess.Popen([cmd, str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def hints(*pairs: tuple[str, str]) -> Text:
    t = Text()
    for i, (k, label) in enumerate(pairs):
        if i:
            t.append(" · ", style=C["faint"])
        t.append(k, style=C["accent"])
        t.append(f" {label}", style=C["dim"])
    return t


def crumbs(*parts: str) -> Text:
    t = Text("subtle", style=f"bold {C['accent']}", no_wrap=True, overflow="ellipsis")
    for i, p in enumerate(parts):
        t.append(" › ", style=C["faint"])
        t.append(p, style=C["fg"] if i == len(parts) - 1 else C["dim"])
    return t


class Base(Screen):
    """Header breadcrumb + body + key-hint footer."""

    def compose(self) -> ComposeResult:
        yield Static(id="crumbs")
        yield from self.body()
        yield Static(id="hints")

    def body(self) -> ComposeResult:
        yield from ()

    def set_chrome(self, crumb: Text, keys: Text) -> None:
        self.query_one("#crumbs", Static).update(crumb)
        self.query_one("#hints", Static).update(keys)


# ---------------------------------------------------------------- browse

class Browse(Base):
    BINDINGS = [
        Binding("backspace,left", "up_dir", show=False),
        Binding("right", "enter", show=False),
        Binding("slash", "filter", show=False),
        Binding("a", "toggle_all", show=False),
        Binding("full_stop", "toggle_hidden", show=False),
        Binding("tilde", "go_home", show=False),
        Binding("ctrl+d", "doctor", show=False),
        Binding("escape", "clear_filter", show=False),
        Binding("q", "app.quit", show=False),
    ]

    def __init__(self, start: Path):
        super().__init__()
        self.cwd = start
        self.show_all = False
        self.show_hidden = False
        self.filter = ""
        self.entries: list[Path] = []
        self.came_from: dict[Path, str] = {}

    def body(self) -> ComposeResult:
        yield Static(id="status")
        yield OptionList(id="files")
        yield Input(placeholder="filter… (Enter keep · Esc clear)", id="filter",
                    select_on_focus=False)

    def on_mount(self) -> None:
        self.query_one("#filter").display = False
        self.refresh_list()
        self.update_status()

    def on_screen_resume(self) -> None:
        self.refresh_list(keep=True)
        self.update_status()

    def update_status(self) -> None:
        st = self.app.status
        t = Text()
        if st is None:
            t.append("checking system…", style=C["dim"])
        else:
            for c in st:
                if c.name in ("python", "disk"):
                    continue
                ok = c.ok or not c.required
                mark, col = ("✓", C["green"]) if c.ok else (("✗", C["red"]) if c.required else ("!", C["yellow"]))
                label = {"whisper engine": "engine", "model": f"model {DEFAULT_MODEL}"}.get(c.name, c.name)
                if c.name == "gpu":
                    label = "GPU" if c.ok and "CUDA ready" in c.status else "CPU mode"
                    mark, col = ("✓", C["green"]) if label == "GPU" else ("·", C["dim"])
                t.append(f"{mark} ", style=col)
                t.append(label, style=C["dim"] if ok else C["red"])
                t.append("   ")
            if not all(c.ok for c in st if c.required):
                t.append("^D fix setup", style=f"bold {C['red']}")
        self.query_one("#status", Static).update(t)

    # -- listing
    def scan(self) -> tuple[list[Path], int]:
        try:
            items = list(self.cwd.iterdir())
        except OSError as e:
            self.notify(f"Can't open {self.cwd}: {e.strerror}", severity="error")
            items = []
        if not self.show_hidden:
            items = [p for p in items if not p.name.startswith(".")]
        if self.filter:
            items = [p for p in items if self.filter.lower() in p.name.lower()]
        dirs = sorted((p for p in items if p.is_dir()), key=lambda p: p.name.lower())
        media = sorted((p for p in items if p.is_file() and p.suffix.lower() in AUDIO | VIDEO),
                       key=lambda p: p.name.lower())
        other = sorted((p for p in items if p.is_file() and p.suffix.lower() not in AUDIO | VIDEO),
                       key=lambda p: p.name.lower())
        shown = dirs + media + (other if self.show_all else [])
        return shown, 0 if self.show_all else len(other)

    def row(self, p: Path, width: int) -> Text:
        t = Text(no_wrap=True, overflow="ellipsis")
        if p.is_dir():
            t.append("▸ ", style=C["accent"])
            t.append(p.name + "/", style=f"bold {C['accent']}")
            return t
        ext = p.suffix.lower()
        icon, col = ("♪ ", C["accent2"]) if ext in AUDIO else (("▶ ", C["accent2"]) if ext in VIDEO else ("  ", C["faint"]))
        name_style = C["fg"] if col != C["faint"] else C["dim"]
        t.append(icon, style=col)
        t.append(p.name[: width].ljust(width), style=name_style)
        try:
            t.append(f"  {human_size(p.stat().st_size):>9}", style=C["dim"])
        except OSError:
            t.append(" " * 11)
        if ext in AUDIO | VIDEO:
            have = [e for e in SUB_BADGES if p.with_suffix(f".{e}").exists()]
            if have:
                t.append("   ✓ " + " ".join(have), style=C["green"])
        return t

    def refresh_list(self, keep: bool = False, select: Optional[str] = None,
                     focus_list: bool = True) -> None:
        ol = self.query_one("#files", OptionList)
        prev = None
        if keep and ol.highlighted is not None and ol.highlighted < len(self.entries):
            prev = self.entries[ol.highlighted].name
        shown, hidden = self.scan()
        has_parent = self.cwd.parent != self.cwd
        self.entries = ([self.cwd.parent] if has_parent else []) + shown
        width = max([len(p.name) for p in shown if p.is_file()] + [24])
        width = min(width, 56)
        opts = []
        if has_parent:
            opts.append(Option(Text.assemble(("▸ ", C["dim"]), ("..", C["dim"])), id="__parent"))
        opts += [Option(self.row(p, width)) for p in shown]
        ol.set_options(opts)
        if not shown:
            ol.add_option(Option(Text("  (no audio/video files here: a shows all files)"
                                      if not self.filter else "  (nothing matches the filter)",
                                      style=C["dim"]), disabled=True))
        elif hidden:
            ol.add_option(Option(Text(f"  · {hidden} other file{'s' if hidden != 1 else ''} hidden "
                                      f"(a to show)", style=C["faint"]), disabled=True))
        target = select or prev
        idx = next((i for i, p in enumerate(self.entries) if p.name == target and
                    not (has_parent and i == 0)), None)
        if idx is None:
            idx = 1 if has_parent and len(self.entries) > 1 else 0
        if self.entries:
            ol.highlighted = idx
        n_media = sum(1 for p in shown if p.is_file() and p.suffix.lower() in AUDIO | VIDEO)
        flt = f" · filter “{self.filter}”" if self.filter else ""
        self.set_chrome(
            crumbs(short_path(self.cwd) + flt) + Text(f"   {n_media} media", style=C["dim"]),
            hints(("Enter", "open/select"), ("←", "up"), ("/", "filter"),
                  ("a", "hide other files" if self.show_all else "all files"), (".", "hidden"),
                  ("~", "home"), ("^D", "doctor"), ("q", "quit")))
        if focus_list:
            ol.focus()

    # -- actions
    def on_option_list_option_selected(self, ev: OptionList.OptionSelected) -> None:
        self.open_index(ev.option_index)

    def action_enter(self) -> None:
        ol = self.query_one("#files", OptionList)
        if ol.highlighted is not None:
            self.open_index(ol.highlighted)

    def open_index(self, i: int) -> None:
        if i >= len(self.entries):
            return
        p = self.entries[i]
        if i == 0 and p == self.cwd.parent and self.cwd.parent != self.cwd:
            return self.action_up_dir()
        if p.is_dir():
            self.came_from[self.cwd] = p.name
            self.cwd, self.filter = p, ""
            self.query_one("#filter", Input).value = ""
            self.query_one("#filter").display = False
            self.refresh_list(select=self.came_from.get(p))
        elif p.suffix.lower() in AUDIO | VIDEO:
            self.app.push_screen(Options(p))
        else:
            self.notify("Not an audio/video file.", severity="warning", timeout=2)

    def action_up_dir(self) -> None:
        if self.cwd.parent == self.cwd:
            return
        child = self.cwd.name
        self.cwd, self.filter = self.cwd.parent, ""
        self.query_one("#filter", Input).value = ""
        self.query_one("#filter").display = False
        self.refresh_list(select=child)

    def action_go_home(self) -> None:
        self.cwd, self.filter = Path.home(), ""
        self.refresh_list()

    def action_toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.refresh_list(keep=True)

    def action_toggle_hidden(self) -> None:
        self.show_hidden = not self.show_hidden
        self.refresh_list(keep=True)

    def action_filter(self) -> None:
        f = self.query_one("#filter", Input)
        f.display = True
        f.focus()

    def action_clear_filter(self) -> None:
        f = self.query_one("#filter", Input)
        if self.filter or f.display:
            f.value, self.filter, f.display = "", "", False
            self.refresh_list(keep=True)

    def on_input_changed(self, ev: Input.Changed) -> None:
        if ev.input.id == "filter":
            self.filter = ev.value
            self.refresh_list(focus_list=False)

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        if ev.input.id == "filter":
            if not self.filter:
                ev.input.display = False
            self.query_one("#files").focus()

    def action_doctor(self) -> None:
        self.app.push_screen(Doctor())


# ---------------------------------------------------------------- options

ROWS = ["formats", "style", "model", "lang", "prompt", "out"]


class Options(Base):
    AUTO_FOCUS = None  # the hidden edit box must not grab keys
    BINDINGS = [
        Binding("up,k", "move(-1)", show=False),
        Binding("down,j", "move(1)", show=False),
        Binding("left,h", "change(-1)", show=False),
        Binding("right,l", "change(1)", show=False),
        Binding("space", "toggle", show=False),
        Binding("e", "edit", show=False),
        Binding("enter", "start", show=False),
        Binding("escape", "back", show=False),
    ]

    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.o = Opts()
        self.row_i = 0
        self.fmt_i = 0
        self.editing: Optional[str] = None
        self.duration: Optional[float] = None

    def body(self) -> ComposeResult:
        yield Static(id="title")
        yield Static(id="rows")

    def on_mount(self) -> None:
        self.o = Opts(**asdict(self.app.opts))
        self.duration = probe_duration(self.path)
        self.on_mount_chrome()
        self.render_rows()

    def est(self) -> str:
        if not self.duration:
            return ""
        gpu = self.app.gpu_ready
        factor = {"base": 0.03, "turbo": 0.13, "large-v3": 0.35, "medium": 0.25, "small": 0.06, "small.en": 0.06,
                  "base.en": 0.03, "tiny": 0.02}.get(self.o.model, 0.2) * (1 if gpu else 3.5)
        secs = max(2, self.duration * factor)
        return f"≈ {human_dur(secs)} on {'GPU' if gpu else 'CPU'}"

    def render_rows(self) -> None:
        o = self.o
        title = Text()
        title.append(f"Transcribe {self.path.name}", style=f"bold {C['fg']}")
        info = f"   {human_dur(self.duration)} · {human_size(self.path.stat().st_size)}"
        title.append(info, style=C["dim"])
        self.query_one("#title", Static).update(title)

        lines = Text()
        full = max(60, self.query_one("#rows", Static).size.width or self.size.width or 100)

        def row(i: int, label: str, value: Text, extra: Text = Text()) -> None:
            active = i == self.row_i
            line = Text()
            line.append(" ▸ " if active else "   ", style=C["accent"])
            line.append(f"{label:<10}", style=C["fg"] if active else C["dim"])
            line.append_text(value)
            line.append("   ")
            line.append_text(extra)
            if active:
                line.pad_right(max(0, full - len(line.plain)))
                line.stylize(f"on {C['cursor']}", 0, len(line.plain))
            lines.append_text(line)
            lines.append("\n")

        def cycle(val: str, choices: list[str], labels: Optional[dict] = None) -> tuple[Text, Text]:
            labels = labels or {}
            v = Text()
            v.append("‹ ", style=C["accent"])
            v.append(labels.get(val, val), style=f"bold {C['fg']}")
            v.append(" ›", style=C["accent"])
            rest = Text()
            for c in choices:
                if c != val:
                    rest.append(labels.get(c, c) + "  ", style=C["dim"])
            return v, rest

        # formats
        fv = Text()
        for j, f in enumerate(FORMATS):
            on = f in o.formats
            style = f"bold {C['accent']}" if on else C["dim"]
            if self.row_i == 0 and j == self.fmt_i:
                style += " underline"
            fv.append(f"[{f}]" if on else f" {f} ", style=style)
            fv.append(" ")
        row(0, "Formats", fv, Text(FORMATS[list(FORMATS)[self.fmt_i]].split(".")[0], style=C["dim"])
            if self.row_i == 0 else Text())
        # style
        v, rest = cycle(o.style, list(STYLES), {k: s[0] for k, s in STYLES.items()})
        row(1, "Style", v, rest)
        # model
        v = Text()
        v.append("‹ ", style=C["accent"])
        v.append(o.model, style=f"bold {C['fg']}")
        v.append(" ›", style=C["accent"])
        size = MODELS.get(o.model, ("", "?", ""))[1]
        extra = Text("✓ downloaded" if is_cached(o.model) else f"↓ {size} download on first use",
                     style=C["green"] if is_cached(o.model) else C["yellow"])
        extra.append(f"   {MODELS.get(o.model, ('', '', 'custom model'))[2]}", style=C["dim"])
        row(2, "Model", v, extra)
        # language
        v, _ = cycle(o.lang, LANGS)
        row(3, "Language", v, Text("auto = detect · e to type any code", style=C["dim"]))
        # prompt
        row(4, "Names", Text(o.prompt or "—", style=C["fg"] if o.prompt else C["dim"]),
            Text("e type names/terms Whisper should spell right", style=C["dim"]))
        # out
        row(5, "Save to", Text(short_path(Path(o.out).expanduser()) if o.out else "next to the file",
                               style=C["fg"]), Text("e type a folder", style=C["dim"]))

        lines.append("\n")
        go = Text()
        go.append("   ▶ Enter  ", style=f"bold {C['green']}")
        nf = len(o.formats)
        go.append(f"transcribe → {', '.join(o.formats) or '(pick a format)'}", style=C["green"])
        go.append(f"   {self.est()}", style=C["dim"])
        if not nf:
            go = Text("   pick at least one format (space)", style=C["yellow"])
        lines.append_text(go)
        self.query_one("#rows", Static).update(lines)

    # -- actions
    def action_move(self, d: int) -> None:
        if self.editing:
            return
        self.row_i = (self.row_i + d) % len(ROWS)
        self.render_rows()

    def action_change(self, d: int) -> None:
        if self.editing:
            return
        o, key = self.o, ROWS[self.row_i]
        if key == "formats":
            self.fmt_i = (self.fmt_i + d) % len(FORMATS)
        elif key == "style":
            ks = list(STYLES)
            o.style = ks[(ks.index(o.style) + d) % len(ks)]
        elif key == "model":
            ks = list(MODELS) if o.model in MODELS else [o.model] + list(MODELS)
            o.model = ks[(ks.index(o.model) + d) % len(ks)]
        elif key == "lang":
            ks = LANGS if o.lang in LANGS else [o.lang] + LANGS
            o.lang = ks[(ks.index(o.lang) + d) % len(ks)]
        self.render_rows()

    def action_toggle(self) -> None:
        if self.editing:
            return
        if ROWS[self.row_i] != "formats":
            return self.action_change(1)
        f = list(FORMATS)[self.fmt_i]
        self.o.formats = [x for x in FORMATS if (x in self.o.formats) != (x == f)]
        self.render_rows()

    def action_edit(self) -> None:
        key = ROWS[self.row_i]
        if key not in ("prompt", "out", "lang", "model"):
            return
        self.editing = key
        inp = Input(id="edit")
        inp.placeholder = {"prompt": "e.g. Names: Zodiac, SFPD, Arthur Leigh Allen",
                           "out": "folder path (blank = next to the file)",
                           "lang": "language code, e.g. en, hi, es (blank = auto)",
                           "model": "model alias, HF repo id or local folder"}[key]
        inp.value = {"prompt": self.o.prompt, "out": self.o.out,
                     "lang": "" if self.o.lang == "auto" else self.o.lang, "model": self.o.model}[key]
        self.mount(inp)
        inp.focus()
        self.set_chrome(crumbs(short_path(self.path.parent), self.path.name),
                        hints(("Enter", "save"), ("Esc", "cancel")))

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        if not self.editing:
            return
        v = ev.value.strip()
        if self.editing == "prompt":
            self.o.prompt = v
        elif self.editing == "out":
            self.o.out = v
        elif self.editing == "lang":
            self.o.lang = v.lower() or "auto"
        elif self.editing == "model":
            self.o.model = v or DEFAULT_MODEL
        self.end_edit()
        ev.stop()

    def end_edit(self) -> None:
        self.editing = None
        for inp in self.query("#edit"):
            inp.remove()
        self.set_focus(None)
        self.on_mount_chrome()
        self.render_rows()

    def on_mount_chrome(self) -> None:
        self.set_chrome(crumbs(short_path(self.path.parent), self.path.name),
                        hints(("Enter", "transcribe"), ("↑↓", "field"), ("←→", "change"),
                              ("space", "toggle format"), ("e", "type a value"), ("Esc", "back")))

    def action_back(self) -> None:
        if self.editing:
            return self.end_edit()
        self.app.pop_screen()

    def action_start(self) -> None:
        if self.editing or not self.o.formats:
            return
        self.app.opts = Opts(**asdict(self.o))
        self.app.opts.save()
        self.app.switch_screen(Run(self.path, self.o, self.duration))


# ---------------------------------------------------------------- run / done

class Run(Base):
    AUTO_FOCUS = None
    BINDINGS = [
        Binding("escape", "cancel_or_back", show=False),
        Binding("enter", "back", show=False),
        Binding("o", "open_folder", show=False),
        Binding("n", "next_file", show=False),
    ]

    def __init__(self, path: Path, o: Opts, duration: Optional[float]):
        super().__init__()
        self.path, self.o, self.duration = path, o, duration
        self.cancel = threading.Event()
        self.finished = False
        self.outputs: dict[str, str] = {}
        self.t0 = time.time()

    def body(self) -> ComposeResult:
        yield Static(id="title")
        yield Static(id="phase")
        yield Static(id="bar")
        log = RichLog(id="live", wrap=True, markup=False, auto_scroll=True)
        log.can_focus = False
        yield log
        yield Static(id="result")

    def on_mount(self) -> None:
        self.set_chrome(crumbs(short_path(self.path.parent), self.path.name, "transcribe"),
                        hints(("Esc", "cancel")))
        title = Text(f"Transcribing {self.path.name}", style=f"bold {C['fg']}")
        title.append(f"   {', '.join(self.o.formats)} · {STYLES[self.o.style][0]} · {self.o.model}",
                     style=C["dim"])
        self.query_one("#title", Static).update(title)
        self.phase("Loading audio and model…")
        self.progress(0, self.duration or 0)
        self.work()

    def phase(self, msg: str, color: str = C["dim"]) -> None:
        self.query_one("#phase", Static).update(Text(msg, style=color))

    def log_seg(self, seg: dict) -> None:
        """Show the segment as the actual captions it becomes, with their start times."""
        from subtle.cues import build_cues
        log = self.query_one("#live", RichLog)
        for c in build_cues([seg], **STYLES[self.o.style][1]):
            t = Text()
            t.append(f"{human_dur(c.start):>6}  ", style=C["faint"])
            t.append(c.text.replace("\n", " / "), style=C["fg"])
            log.write(t)

    def progress(self, done: float, total: float) -> None:
        width = 48
        frac = min(1.0, done / total) if total else 0.0
        n = int(frac * width)
        t = Text()
        t.append("━" * n, style=C["green"] if frac >= 1 else C["accent"])
        t.append("━" * (width - n), style=C["faint"])
        t.append(f"  {frac * 100:3.0f}%", style=C["fg"])
        if total:
            t.append(f"   {human_dur(done)} / {human_dur(total)}", style=C["dim"])
            el = time.time() - self.t0
            if 0.02 < frac < 1 and el > 2:
                t.append(f"   ≈ {human_dur(el / frac - el)} left", style=C["dim"])
        self.query_one("#bar", Static).update(t)

    @work(thread=True, exclusive=True)
    def work(self) -> None:
        from subtle.engine import Cancelled
        from subtle.writers import write_all
        app, o = self.app, self.o
        call = app.call_from_thread
        try:
            tr = app.transcriber(o.model, warn=lambda m: call(self.phase, m, C["yellow"]))
            call(self.phase, f"{o.model} on {tr.device.upper()} · listening…")

            def on_seg(seg: dict) -> None:
                if self.cancel.is_set():
                    raise Cancelled()
                call(self.log_seg, seg)

            res = tr.transcribe(str(self.path), language=None if o.lang == "auto" else o.lang,
                                prompt=o.prompt or None, on_segment=on_seg,
                                on_progress=lambda d, t: call(self.progress, d, t))
            res["source"], res["model"] = str(self.path), o.model
            out_dir = Path(o.out).expanduser() if o.out else None
            outputs, cues = write_all(res, o.formats, self.path, out_dir, **STYLES[o.style][1])
            call(self.done, outputs, len(cues), res)
        except Cancelled:
            call(self.failed, "Cancelled.", C["yellow"])
        except Exception as e:  # noqa: BLE001
            call(self.failed, f"Failed: {e}", C["red"])

    def done(self, outputs: dict, n_cues: int, res: dict) -> None:
        self.finished, self.outputs = True, outputs
        self.progress(res["duration"], res["duration"])
        secs = time.time() - self.t0
        self.phase(f"✓ Done in {secs:.1f}s · {n_cues} captions · language {res['language']} · "
                   f"{human_dur(res['duration'])} audio", C["green"])
        t = Text()
        for fmt, p in outputs.items():
            t.append(f"  {fmt:<5}", style=f"bold {C['accent']}")
            t.append(short_path(Path(p), 90) + "\n", style=C["fg"])
        if "srt" in outputs:
            t.append("\n  Upload the .srt in YouTube Studio → Subtitles → Add language → Upload file.",
                     style=C["dim"])
        self.query_one("#result", Static).update(t)
        self.set_chrome(crumbs(short_path(self.path.parent), self.path.name, "done"),
                        hints(("Enter", "back to files"), ("o", "open folder"),
                              ("n", "next file"), ("q", "quit")))
        self.app.bell()

    def failed(self, msg: str, color: str) -> None:
        self.finished = True
        self.phase(msg, color)
        self.set_chrome(crumbs(short_path(self.path.parent), self.path.name),
                        hints(("Enter", "back to files"), ("^D", "doctor"), ("q", "quit")))

    def action_cancel_or_back(self) -> None:
        if self.finished:
            return self.action_back()
        self.cancel.set()
        self.phase("Cancelling after the current segment…", C["yellow"])

    def action_back(self) -> None:
        if self.finished:
            self.app.pop_screen()

    def action_open_folder(self) -> None:
        if self.outputs:
            open_in_file_manager(Path(next(iter(self.outputs.values()))).parent)

    def action_next_file(self) -> None:
        """Back to the browser with the cursor on the next media file."""
        if not self.finished:
            return
        self.app.pop_screen()
        b = self.app.screen
        if isinstance(b, Browse):
            ol = b.query_one("#files", OptionList)
            names = [p.name for p in b.entries]
            if self.path.name in names:
                i = names.index(self.path.name) + 1
                while i < len(b.entries) and not (b.entries[i].is_file() and
                                                   b.entries[i].suffix.lower() in AUDIO | VIDEO):
                    i += 1
                if i < len(b.entries):
                    ol.highlighted = i


# ---------------------------------------------------------------- doctor

class Doctor(Base):
    BINDINGS = [
        Binding("s", "setup", show=False),
        Binding("g", "guide", show=False),
        Binding("r", "recheck", show=False),
        Binding("escape,q", "app.pop_screen", show=False),
    ]

    def body(self) -> ComposeResult:
        with VerticalScroll(id="docbody"):
            yield Static(id="doc")

    def on_mount(self) -> None:
        self.set_chrome(crumbs("doctor"), hints(("s", "auto-setup missing"), ("g", "manual guide"),
                                                ("r", "re-check"), ("Esc", "back")))
        self.show_checks()

    def show_checks(self) -> None:
        st = self.app.status
        t = Text()
        if st is None:
            t.append("Checking…", style=C["dim"])
        else:
            t.append("System check\n\n", style=f"bold {C['fg']}")
            for c in st:
                mark, col = ("✓", C["green"]) if c.ok else (("✗", C["red"]) if c.required else ("!", C["yellow"]))
                t.append(f"  {mark} ", style=col)
                t.append(f"{c.name:<16}", style=C["fg"])
                t.append(f"{c.status}", style=C["dim"] if c.ok else col)
                t.append("   optional\n" if not c.required else "\n", style=C["faint"])
            fixes = [c for c in st if c.fix]
            t.append("\n")
            if fixes:
                t.append("  s ", style=f"bold {C['accent']}")
                t.append("installs what's missing (asks before each download / sudo).  ", style=C["dim"])
                t.append("g ", style=f"bold {C['accent']}")
                t.append("shows manual steps.", style=C["dim"])
            else:
                t.append("  All good. Ready to transcribe.", style=C["green"])
        self.query_one("#doc", Static).update(t)

    def action_recheck(self) -> None:
        self.app.status = None
        self.show_checks()
        self.app.load_status(then=self.show_checks)

    def action_guide(self) -> None:
        from subtle.doctor import GUIDE
        self.query_one("#doc", Static).update(Text(GUIDE, style=C["fg"]))
        self.set_chrome(crumbs("doctor", "manual guide"),
                        hints(("↑↓", "scroll"), ("r", "back to checks"), ("Esc", "back")))

    def action_setup(self) -> None:
        import typer

        from subtle.cli import setup
        with self.app.suspend():
            try:
                setup(yes=False, guide=False, only=None, model=DEFAULT_MODEL)
            except typer.Exit:
                pass
            except Exception as e:  # noqa: BLE001
                print(f"setup failed: {e}")
            input("\nPress Enter to return to subtle…")
        self.action_recheck()


# ---------------------------------------------------------------- app

class SubtleApp(App):
    TITLE = f"subtle {__version__}"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding("ctrl+c,ctrl+q", "quit", priority=True, show=False)]
    CSS = f"""
    Screen {{ background: {C['bg']}; color: {C['fg']}; }}
    #crumbs {{ height: 2; padding: 0 1; border-bottom: solid {C['faint']}; }}
    #hints {{ dock: bottom; height: 2; padding: 0 1; border-top: solid {C['faint']}; }}
    #status {{ height: 3; padding: 1 1 1 1; }}
    #title {{ height: 3; padding: 1 1 1 1; }}
    #rows {{ padding: 0 0; width: 100%; }}
    #phase {{ height: 1; padding: 0 1; }}
    #bar {{ padding: 1 1 1 1; height: 3; }}
    #live {{ height: 1fr; border: none; background: {C['bg']}; background-tint: 0%; padding: 0 1;
            scrollbar-size-vertical: 1; scrollbar-background: {C['bg']};
            scrollbar-color: {C['faint']}; }}
    #result {{ height: auto; padding: 1 1; }}
    #docbody {{ padding: 1 1; }}
    OptionList {{ border: none; background: {C['bg']}; padding: 0 1; height: 1fr;
                 scrollbar-size-vertical: 1; scrollbar-background: {C['bg']};
                 scrollbar-color: {C['faint']}; }}
    OptionList:focus {{ border: none; background-tint: 0%; }}
    OptionList > .option-list--option-highlighted,
    OptionList:focus > .option-list--option-highlighted {{
        background: {C['cursor']}; color: {C['fg']}; text-style: none; }}
    OptionList > .option-list--option-hover {{ background: #1f2335; }}
    Input {{ border: tall {C['accent']}; background: {C['bg']}; margin: 0 1; }}
    """

    def __init__(self, start: Path):
        super().__init__()
        self.start = start
        self.opts = Opts.load()
        self.status = None
        self._tr = None
        self._tr_lock = threading.Lock()

    @property
    def gpu_ready(self) -> bool:
        return bool(self.status) and any(c.name == "gpu" and "CUDA ready" in c.status
                                         for c in self.status)

    def on_mount(self) -> None:
        self.theme = "tokyo-night"
        self.push_screen(Browse(self.start))
        self.load_status()

    @work(thread=True, exclusive=True, group="status")
    def load_status(self, then=None) -> None:
        from subtle.doctor import run_checks
        st = run_checks(DEFAULT_MODEL)

        def apply():
            self.status = st
            for s in self.screen_stack:
                if isinstance(s, Browse):
                    s.update_status()
            if then:
                then()
        self.call_from_thread(apply)

    def transcriber(self, model: str, warn):
        """Load once, reuse across files (model load is the slow part)."""
        from subtle.engine import Transcriber
        with self._tr_lock:
            if self._tr is None or self._tr.model_name != model:
                self._tr = None
                self._tr = Transcriber(model, warn=warn)
            else:
                self._tr.warn = warn
            return self._tr


def run_tui(start: Path) -> None:
    SubtleApp(start).run()
