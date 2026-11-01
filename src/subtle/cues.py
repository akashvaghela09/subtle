"""Group word timestamps into readable caption cues."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SENTENCE_END = (".", "?", "!", "…")
CLAUSE_END = (",", ";", ":", "—", "-")


@dataclass
class Cue:
    start: float
    end: float
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _wrap(words: list[str], max_chars: int, max_lines: int) -> list[str]:
    text = " ".join(words)
    if len(text) <= max_chars or max_lines == 1:
        return [text]
    if max_lines == 2:  # balanced split: minimise the longer line
        best = min(range(1, len(words)),
                   key=lambda i: max(len(" ".join(words[:i])), len(" ".join(words[i:]))))
        return [" ".join(words[:best]), " ".join(words[best:])]
    lines, cur = [], []
    for w in words:
        if cur and len(" ".join(cur + [w])) > max_chars:
            lines.append(" ".join(cur))
            cur = []
        cur.append(w)
    return lines + [" ".join(cur)]


def build_cues(segments: list[dict], max_chars: int = 42, max_lines: int = 2,
               max_duration: float = 6.0, max_words: Optional[int] = None,
               gap: float = 0.8, min_duration: float = 0.8) -> list[Cue]:
    words = [w for s in segments for w in s["words"]]
    if not words:  # no word timings: one cue per segment
        return [Cue(s["start"], s["end"], _wrap(s["text"].split(), max_chars, max_lines))
                for s in segments if s["text"]]

    limit = max_chars * (1 if max_words else max_lines)
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if cur:
            text_len = len(" ".join(x["word"] for x in cur + [w]))
            if ((max_words and len(cur) >= max_words)
                    or text_len > limit
                    or w["end"] - cur[0]["start"] > max_duration
                    or w["start"] - cur[-1]["end"] > gap):
                groups.append(cur)
                cur = []
        cur.append(w)
        n = len(" ".join(x["word"] for x in cur))
        if w["word"].endswith(SENTENCE_END) and (max_words or n >= 12):
            groups.append(cur)
            cur = []
        elif w["word"].endswith(CLAUSE_END) and not max_words and n >= limit * 0.6:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    cues = [Cue(g[0]["start"], g[-1]["end"],
                _wrap([x["word"] for x in g], max_chars, 1 if max_words else max_lines))
            for g in groups]
    # stretch very short cues so they stay readable, without overlapping the next one
    for i, c in enumerate(cues):
        nxt = cues[i + 1].start if i + 1 < len(cues) else c.end + min_duration
        if c.end - c.start < min_duration:
            c.end = max(c.end, min(c.start + min_duration, nxt))
    return cues
