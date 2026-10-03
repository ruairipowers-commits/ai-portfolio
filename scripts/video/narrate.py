"""Edit and narrate a recorded walkthrough: remove dead time, then add a voice-over that speaks each caption.

    python scripts/video/narrate.py --tts piper            # neural voice (Piper); downloads the voice once
    python scripts/video/narrate.py --tts pico --out x.mp4  # quick preview with SVOX Pico

Inputs (default: the governance escalation walkthrough):
  --video  the raw screen recording               projects/governance-console/docs/video/escalation-raw.mp4
  --cues   {"cues": [[seconds, caption], …], "cuts": [[start, end, keep, mode], …]}   (written by the recorder)
                                                   projects/governance-console/docs/video/escalation-cues.json

How the edit works, per caption (a "segment" runs from one caption to the next):
  1. Stretches where the screen doesn't change (a page loading, the recorder waiting) are found with ffmpeg
     freezedetect; blank white screens with blackdetect on the inverted picture.
  2. Blank screens are cut entirely; other still stretches are cut down to STILL_KEEP seconds.
  3. If the voice for that caption is longer than what's left, still stretches get time back (in order), and only
     then is the last frame held — so the narration never talks over the next step and nothing sits idle.
The voice starts VOICE_LEAD seconds after its caption appears. Needs ffmpeg and ffprobe on PATH.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "projects" / "governance-console" / "docs" / "video"
STILL_KEEP = 0.25     # seconds of each still stretch kept as a beat
VOICE_LEAD = 0.10     # voice starts this long after the caption appears
VOICE_TAIL = 0.20     # gap after a sentence before the next caption
MIN_CLIP = 0.06
FPS = 25


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def duration(path: Path) -> float:
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]).stdout)


# ---------------------------------------------------------------- speech
def speakable(text: str) -> str:
    t = text.replace("…", ".").replace("“", "").replace("”", "").replace("—", ",")
    t = re.sub(r"INC-\.*", "the incident number", t)
    t = t.replace("SEC-04", "control SEC zero four").replace("unsafe_action", "unsafe action")
    t = t.replace("OFF", "off").replace("EOD", "E.O.D.")
    return t


class Piper:
    def __init__(self, voice: str, voices_dir: Path, length_scale: float):
        from piper import PiperVoice, SynthesisConfig
        model = voices_dir / f"{voice}.onnx"
        if not model.exists():
            voices_dir.mkdir(parents=True, exist_ok=True)
            run([sys.executable, "-m", "piper.download_voices", voice, "--data-dir", str(voices_dir)])
        self.voice = PiperVoice.load(str(model))
        self.cfg = SynthesisConfig(length_scale=length_scale)
        self.tag = f"piper-{voice}-{length_scale}"

    def to_wav(self, text: str, out: Path) -> None:
        with wave.open(str(out), "wb") as wf:
            self.voice.synthesize_wav(text, wf, syn_config=self.cfg)


class Pico:
    tag = "pico"

    def to_wav(self, text: str, out: Path) -> None:
        run(["pico2wave", "-l", "en-US", "-w", str(out), text])


# ---------------------------------------------------------------- analysis
def intervals(video: Path, vf: str, start_key: str, end_key: str) -> list[tuple[float, float]]:
    log = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf", vf, "-an", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(rf"{start_key}[:=]\s*([\d.]+)", log)]
    ends = [float(x) for x in re.findall(rf"{end_key}[:=]\s*([\d.]+)", log)]
    total = duration(video)
    return [(s, ends[i] if i < len(ends) else total) for i, s in enumerate(starts)]


def stills(video: Path) -> list[tuple[float, float]]:
    return intervals(video, "freezedetect=n=0.002:d=0.25", "freeze_start", "freeze_end")


def blanks(video: Path) -> list[tuple[float, float]]:
    # a white page while something loads = black once inverted
    return [(s, e) for s, e in intervals(video, "negate,blackdetect=d=0.04:pix_th=0.10:pic_th=0.95",
                                         "black_start", "black_end")]


def overlaps(a: tuple[float, float], spans: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(a[1], e) - max(a[0], s)) for s, e in spans)


# ---------------------------------------------------------------- the edit
def plan(total: float, cues: list[tuple[float, str]], voice_len: list[float],
         still: list[tuple[float, float]], blank: list[tuple[float, float]],
         cuts: list[list] | None = None) -> tuple[list[tuple], list[float]]:
    """→ clips [(src_start, src_end, hold_after)] and the output time each caption's segment starts."""
    clips, seg_starts, out_t = [], [], 0.0
    bounds = [c[0] for c in cues] + [total]
    for i, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        seg_starts.append(out_t)
        # split [a, b) into pieces: (start, end, kind) with kind active | still | blank
        removed = list(blank)
        for s, e, keep, mode in cuts or []:       # page loads and waits the recorder marked
            removed.append((s, e - keep) if mode == "end" else (s + keep / 2, e - keep / 2))
        marks = [(s, e, "blank") for s, e in removed if e > s] + \
                [(s, e, "still") for s, e in still if overlaps((s, e), blank) < 0.6 * (e - s)]
        pieces, t = [], a
        for s, e, kind in sorted(marks):
            s, e = max(s, a, t), min(e, b)
            if e - s <= 0:
                continue
            if s > t:
                pieces.append([t, s, "active"])
            pieces.append([s, e, kind])
            t = e
        if t < b:
            pieces.append([t, b, "active"])
        keep = []
        for s, e, kind in pieces:
            k = (e - s) if kind == "active" else (0.0 if kind == "blank" else min(STILL_KEEP, e - s))
            keep.append([s, e, kind, k])
        need = VOICE_LEAD + voice_len[i] + VOICE_TAIL
        extra = need - sum(k for *_, k in keep)
        for p in keep:                          # give stills their time back, in order
            if extra <= 0:
                break
            if p[2] == "still":
                add = min(extra, (p[1] - p[0]) - p[3])
                p[3] += add
                extra -= add
        seg_clips = [(s, s + k) for s, e, kind, k in keep if k >= MIN_CLIP]
        if not seg_clips:                       # a segment that was all blank: show its last moment
            seg_clips = [(max(a, b - 0.3), b)]
        hold = max(0.0, extra)
        for j, (s, e) in enumerate(seg_clips):
            clips.append((s, e, hold if j == len(seg_clips) - 1 else 0.0))
            out_t += (e - s) + (hold if j == len(seg_clips) - 1 else 0.0)
    return clips, seg_starts


def render(video: Path, clips: list[tuple], voices: list[Path], seg_starts: list[float], out: Path, work: Path) -> None:
    """Cut each clip to its own file (fast: input seeking), join them, then lay the voices over the result."""
    cdir = work / "clips"
    cdir.mkdir(parents=True, exist_ok=True)
    for f in cdir.glob("*.mp4"):
        f.unlink()
    names = []
    for i, (s, e, hold) in enumerate(clips):
        name = cdir / f"{i:04d}.mp4"
        vf = f"fps={FPS},format=yuv420p" + (f",tpad=stop_mode=clone:stop_duration={hold:.3f}" if hold > 0 else "")
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s:.3f}", "-i", str(video), "-t", f"{e - s:.3f}", "-an",
             "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(name)])
        names.append(name)
    lst = work / "clips.txt"
    lst.write_text("".join(f"file '{n}'\n" for n in names))
    silent = work / "edited.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(silent)])
    inputs, parts = ["-i", str(silent)], []
    for i, (w, t) in enumerate(zip(voices, seg_starts), start=1):
        inputs += ["-i", str(w)]
        ms = int((t + VOICE_LEAD) * 1000)
        parts.append(f"[{i}:a]aresample=48000,adelay={ms}|{ms}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(1, len(voices) + 1))
    parts.append(f"{mix}amix=inputs={len(voices)}:normalize=0,loudnorm=I=-16:TP=-1.5,aresample=48000[aout]")
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[aout]",
         "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
         "-ac", "1", "-movflags", "+faststart", "-t", f"{duration(silent):.3f}", str(out)])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--video", type=Path, default=DEFAULT_DIR / "escalation-raw.mp4")
    ap.add_argument("--cues", type=Path, default=DEFAULT_DIR / "escalation-cues.json")
    ap.add_argument("--tts", choices=["piper", "pico"], default="piper")
    ap.add_argument("--voice", default="en_US-lessac-high", help="any Piper voice name")
    ap.add_argument("--length-scale", type=float, default=0.95, help="< 1 speaks a little faster")
    ap.add_argument("--voices-dir", type=Path, default=Path.home() / ".cache" / "piper-voices")
    ap.add_argument("--work", type=Path, default=Path(tempfile.gettempdir()) / "narrate-work")
    ap.add_argument("--out", type=Path, default=Path.cwd() / "escalation.mp4")
    a = ap.parse_args()

    data = json.loads(a.cues.read_text())
    data = data if isinstance(data, dict) else {"cues": data, "cuts": []}
    cues = [(float(t), text) for t, text in data["cues"]]
    tts = Piper(a.voice, a.voices_dir, a.length_scale) if a.tts == "piper" else Pico()
    a.work.mkdir(parents=True, exist_ok=True)
    voices, lens = [], []
    for _, text in cues:
        w = a.work / (hashlib.md5(f"{tts.tag}|{text}".encode()).hexdigest()[:12] + ".wav")
        if not w.exists():
            tts.to_wav(speakable(text), w)
        voices.append(w)
        lens.append(duration(w))
    total = duration(a.video)
    clips, seg_starts = plan(total, cues, lens, stills(a.video), blanks(a.video), data.get("cuts"))
    render(a.video, clips, voices, seg_starts, a.out, a.work)
    print(f"{a.out}: {duration(a.out):.1f}s (raw {total:.1f}s), {len(cues)} narrated steps, voice {tts.tag}")


if __name__ == "__main__":
    main()
