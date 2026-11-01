"""Output formats. Each writer takes (cues, result) and returns file text."""
from __future__ import annotations

import json

from subtle.cues import Cue

FORMATS = {
    "srt":  "SubRip captions. Upload to YouTube Studio > Subtitles. The default.",
    "vtt":  "WebVTT captions. Also accepted by YouTube; used by web players.",
    "txt":  "Plain transcript in paragraphs, for descriptions, chapters and script checks.",
    "json": "Full data: segments, word-level timings and cues. Use it for Remotion or other tools.",
    "ass":  "Styled captions (bold white, black outline) to burn in: ffmpeg -i v.mp4 -vf ass=v.ass out.mp4",
}


def _ts(t: float, sep: str = ",") -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}{sep}{ms:03}"


def srt(cues: list[Cue], result: dict) -> str:
    return "\n".join(f"{i}\n{_ts(c.start)} --> {_ts(c.end)}\n{c.text}\n"
                     for i, c in enumerate(cues, 1))


def vtt(cues: list[Cue], result: dict) -> str:
    return "WEBVTT\n\n" + "\n".join(f"{_ts(c.start, '.')} --> {_ts(c.end, '.')}\n{c.text}\n"
                                    for c in cues)


def txt(cues: list[Cue], result: dict) -> str:
    paras, cur, last_end = [], [], None
    for s in result["segments"]:
        if cur and last_end is not None and s["start"] - last_end > 1.5:
            paras.append(" ".join(cur))
            cur = []
        cur.append(s["text"])
        last_end = s["end"]
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(paras) + "\n"


def json_(cues: list[Cue], result: dict) -> str:
    data = dict(result)
    data["cues"] = [{"start": round(c.start, 3), "end": round(c.end, 3), "text": c.text}
                    for c in cues]
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,80,80,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_ts(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def ass(cues: list[Cue], result: dict) -> str:
    def esc(t: str) -> str:
        return t.replace("{", "(").replace("}", ")").replace("\n", "\\N")
    return ASS_HEADER + "".join(
        f"Dialogue: 0,{_ass_ts(c.start)},{_ass_ts(c.end)},Default,,0,0,0,,{esc(c.text)}\n"
        for c in cues)


WRITERS = {"srt": srt, "vtt": vtt, "txt": txt, "json": json_, "ass": ass}
