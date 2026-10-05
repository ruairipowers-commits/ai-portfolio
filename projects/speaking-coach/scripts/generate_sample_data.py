"""Write the demo samples from the labelled golden transcripts (deterministic: strips the [[labels]]).

    python scripts/generate_sample_data.py      # → samples/*.txt|vtt  (+ samples/word-lists/*.txt)
All transcripts are fictional, written for this project.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ["interview-answer.txt", "team-update.txt", "conference-opening.vtt", "podcast-segment.vtt", "pitch.txt",
           "physics-lecture.txt", "like-as-verb.txt", "clean-control.txt"]
WORD_LISTS = {
    "my-meeting-habits.txt": "# Ruairi's list: the seven fillers, plus repeated words (on in the starter preset)\n"
                             "um\nuh\nlike\nyou know\nkind of\nso | sentence starter | 1 | opener\n"
                             "I guess | closing crutch | 1 | closer\n",
    "pitch-crutches.txt": "# phrases that creep into a pitch; weight 2 = counts double\nto be honest | crutch phrase | 2\n"
                          "at the end of the day | crutch phrase\nbasically\ngoing forward | jargon\n",
    "lecturer.txt": "# a lecturer who says 'basically' as a term of art\nliterally\nactually\ntotally\n!basically\n",
}


def main() -> None:
    out = ROOT / "samples"
    (out / "word-lists").mkdir(parents=True, exist_ok=True)
    for name in SAMPLES:
        raw = (ROOT / "evals" / "transcripts" / name).read_text()
        (out / name).write_text(re.sub(r"\[\[(.+?)\]\]", r"\1", raw))
    for name, text in WORD_LISTS.items():
        (out / "word-lists" / name).write_text(text)
    print(f"wrote {len(SAMPLES)} transcripts and {len(WORD_LISTS)} word lists to samples/")


if __name__ == "__main__":
    main()
