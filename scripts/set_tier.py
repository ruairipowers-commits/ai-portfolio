"""Move a project between FEATURED (home page + main blog) and PERSONAL (the Personal projects page).

    python scripts/set_tier.py eod-heartbeat personal
    python scripts/set_tier.py eod-heartbeat featured
    python scripts/set_tier.py --check            # CI: every post is where its tier says (exit 1 if not)

It edits `personal_projects` in portfolio.yaml (comments kept), moves the project's post between
site/blog/posts/ and site/personal/posts/, fixes relative links in and to the moved post, and points the
project README's write-up link at the new URL. Then run `mkdocs build --strict` to confirm nothing broke.
"""
from __future__ import annotations

import posixpath
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DIRS = {"featured": "blog/posts", "personal": "personal/posts"}
LINK = re.compile(r"(\]\()([^)#\s]+)([^)]*\))")


def personal_slugs() -> list[str]:
    cfg = yaml.safe_load((ROOT / "portfolio.yaml").read_text())
    return [p for p in (cfg.get("personal_projects") or []) if isinstance(p, str)]


def check() -> int:
    cfg = yaml.safe_load((ROOT / "portfolio.yaml").read_text())
    personal, bad = set(personal_slugs()), []
    for slug in cfg["projects"]:
        tier = "personal" if slug in personal else "featured"
        other = "featured" if tier == "personal" else "personal"
        if (SITE / DIRS[other] / f"{slug}.md").exists():
            bad.append(f"{slug} is {tier} in portfolio.yaml but its post is in site/{DIRS[other]}/ — "
                       f"run: python scripts/set_tier.py {slug} {tier}")
    for b in bad:
        print("::error::" + b)
    print("project tiers: OK" if not bad else f"{len(bad)} project(s) in the wrong place")
    return 1 if bad else 0


def _rewrite(text: str, file_dir: str, fn) -> str:
    """Apply fn(resolved site path) -> new site path or None to every relative link in `text`."""
    def sub(m):
        target = m.group(2)
        if re.match(r"^[a-z]+:|^/|^\{\{", target):
            return m.group(0)
        resolved = posixpath.normpath(posixpath.join(file_dir, target))
        new = fn(resolved)
        return m.group(0) if new is None else m.group(1) + new + m.group(3)
    return LINK.sub(sub, text)


def set_tier(slug: str, tier: str) -> None:
    cfg = yaml.safe_load((ROOT / "portfolio.yaml").read_text())
    if slug not in cfg["projects"]:
        sys.exit(f"{slug} isn't in portfolio.yaml projects:")
    old_tier = "personal" if slug in personal_slugs() else "featured"
    if old_tier == tier:
        print(f"{slug} is already {tier}")
        return

    # 1. portfolio.yaml: edit the personal_projects list in place, keeping its comments
    text = (ROOT / "portfolio.yaml").read_text()
    current = personal_slugs()
    new = [s for s in current if s != slug] + ([slug] if tier == "personal" else [])
    block = "personal_projects: []" if not new else "personal_projects:\n" + "".join(f"  - {s}\n" for s in new).rstrip("\n")
    text, n = re.subn(r"(?m)^personal_projects:(?: \[\])?\n(?:  - [a-z0-9-]+\n)*", block + "\n", text, count=1)
    if not n:
        sys.exit("couldn't find personal_projects: in portfolio.yaml")
    (ROOT / "portfolio.yaml").write_text(text)

    # 2. move the post and fix links in it (resolved from its old folder, re-relativised to the new one)
    old_rel, new_rel = f"{DIRS[old_tier]}/{slug}.md", f"{DIRS[tier]}/{slug}.md"
    if (SITE / old_rel).exists():
        (SITE / DIRS[tier]).mkdir(parents=True, exist_ok=True)
        body = (SITE / old_rel).read_text()
        body = _rewrite(body, posixpath.dirname(old_rel),
                        lambda r: posixpath.relpath(r, posixpath.dirname(new_rel)))
        (SITE / new_rel).write_text(body)
        (SITE / old_rel).unlink()          # git sees a rename when you commit (the content barely changes)
        # 3. links to the post from every other page
        for md in SITE.rglob("*.md"):
            rel = md.relative_to(SITE).as_posix()
            if rel == new_rel:
                continue
            t = md.read_text()
            t2 = _rewrite(t, posixpath.dirname(rel),
                          lambda r: posixpath.relpath(new_rel, posixpath.dirname(rel)) if r == old_rel else None)
            if t2 != t:
                md.write_text(t2)
        print(f"moved site/{old_rel} → site/{new_rel}")
    else:
        print(f"no post at site/{old_rel}; nothing to move")

    # 4. the project's README links to its write-up URL
    readme = ROOT / "projects" / slug / "README.md"
    if readme.exists():
        old_url, new_url = ("/blog/", "/personal/") if tier == "personal" else ("/personal/", "/blog/")
        t = readme.read_text().replace("{{SITE_URL}}" + old_url + slug + "/", "{{SITE_URL}}" + new_url + slug + "/")
        readme.write_text(t)
    print(f"{slug} is now {tier}. Check with: mkdocs build --strict")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        sys.exit(check())
    if len(sys.argv) != 3 or sys.argv[2] not in DIRS:
        sys.exit(__doc__)
    set_tier(sys.argv[1], sys.argv[2])
