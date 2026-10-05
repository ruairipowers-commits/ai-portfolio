"""Turn whatever the speaker has into plain text plus, when available, timing and speaker turns.

Accepted: pasted text, .txt, .md, .docx, .srt, .vtt. Meeting exports with several people ("Name: text" lines, or
WebVTT voice tags <v Name>) are split into turns so you can analyse just yourself.
Audio is not in v1 (see docs/architecture.md, "What's next").
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
SPEAKER_LINE = re.compile(r"^\s*([A-Z][\w.'’-]*(?:\s[A-Z][\w.'’-]*){0,3})\s*:\s+(.*\S)\s*$")
VOICE = re.compile(r"<v(?:\.[\w.-]+)?\s+([^>]+)>(.*?)(?:</v>|$)", re.S)
TAGS = re.compile(r"</?[^>]+>")


@dataclass
class Segment:
    text: str
    speaker: str = ""
    start: float | None = None
    end: float | None = None


@dataclass
class Transcript:
    segments: list[Segment] = field(default_factory=list)
    source: str = "text"
    warnings: list[str] = field(default_factory=list)

    @property
    def speakers(self) -> list[str]:
        seen: list[str] = []
        for s in self.segments:
            if s.speaker and s.speaker not in seen:
                seen.append(s.speaker)
        return seen

    @property
    def timed(self) -> bool:
        return any(s.start is not None for s in self.segments)

    def select(self, speaker: str | None = None) -> list[Segment]:
        return [s for s in self.segments if not speaker or s.speaker == speaker]

    def layout(self, speaker: str | None = None) -> tuple[str, list[tuple[int, int, Segment, bool]]]:
        """One speaker's words as a single string, plus where each segment landed: (start, end, segment, new_turn).
        Consecutive segments from the same person are joined with a space (caption cues often split sentences);
        a new turn starts a new line, which the tokenizer treats as a sentence boundary."""
        text, spans, prev = "", [], None
        all_segs = self.segments
        for k, s in enumerate(all_segs):
            if speaker and s.speaker != speaker:
                prev = None          # someone else spoke: the next segment of ours is a new turn
                continue
            new_turn = prev is None or prev.speaker != s.speaker
            if text:
                text += "\n" if new_turn else " "
            spans.append((len(text), len(text) + len(s.text), s, new_turn))
            text += s.text
            prev = s
        return text, spans

    def text(self, speaker: str | None = None) -> str:
        return self.layout(speaker)[0]


def _secs(m: re.Match) -> float:
    h, mnt, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mnt) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_cues(raw: str) -> Transcript:
    """SRT or WebVTT."""
    t = Transcript(source="captions")
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n").strip())
    for b in blocks:
        lines = [l for l in b.split("\n") if l.strip()]
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        ms = list(TIME.finditer(lines[idx]))
        if len(ms) < 2:
            continue
        start, end = _secs(ms[0]), _secs(ms[1])
        body = " ".join(lines[idx + 1:])
        speaker = ""
        v = VOICE.search(body)
        if v:
            speaker, body = v.group(1).strip(), v.group(2)
        body = TAGS.sub("", body).strip()
        m = SPEAKER_LINE.match(body)
        if m and not speaker:
            speaker, body = m.group(1), m.group(2)
        if body:
            t.segments.append(Segment(body, speaker, start, end))
    if not t.segments:
        t.warnings.append("no caption cues found")
    return t


def parse_text(raw: str) -> Transcript:
    """Plain text. If at least two lines look like 'Name: words' with the same names repeating, treat as turns."""
    lines = [l for l in raw.replace("\r\n", "\n").split("\n")]
    matches = [SPEAKER_LINE.match(l) for l in lines]
    names = [m.group(1) for m in matches if m]
    multi = len(names) >= 2 and any(names.count(n) > 1 for n in names)
    t = Transcript(source="text")
    if not multi:
        text = raw.strip()
        if text:
            t.segments.append(Segment(text))
        return t
    current = None
    for l, m in zip(lines, matches):
        if m:
            current = Segment(m.group(2), m.group(1))
            t.segments.append(current)
        elif l.strip() and current is not None:
            current.text += " " + l.strip()
        elif l.strip():
            current = Segment(l.strip())
            t.segments.append(current)
    return t


def from_docx(data: bytes) -> str:
    import docx  # python-docx

    return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)


def load(name: str, data: bytes | str) -> Transcript:
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else "txt"
    if ext == "docx":
        return parse_text(from_docx(data if isinstance(data, bytes) else data.encode()))
    raw = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    if ext in ("srt", "vtt") or raw.lstrip().startswith("WEBVTT") or re.search(r"\d+:\d{2}[.,]\d{3}\s*-->", raw):
        return parse_cues(raw)
    if ext in ("mp3", "m4a", "wav", "mp4", "ogg", "flac"):
        t = Transcript(source="audio")
        t.warnings.append("audio isn't supported yet — export a transcript (.vtt, .srt or text) and upload that")
        return t
    return parse_text(raw)
