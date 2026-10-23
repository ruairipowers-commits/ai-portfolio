"""The catalog: one course per technology page on the site, plus topics the owner has approved.

Sources (DATA-01): `sources/tech/<slug>.md` is a copy of the site's `site/tech/<slug>.md` (refreshed by
`course sources`); its hash is recorded on every level built from it. Approved suggestions that have no tech page
are grounded in an owner-supplied docs page instead (stored with the course row).

Content: levels are YAML files. Bundled ones live in `courses/<slug>/<level>.yaml` (in git, reviewed like code).
Builds, revisions and the owner's publish write versioned copies to `<data>/warehouse/courses/<slug>/<level>.v<N>.yaml`.
Learners always get the newest published version; the owner reviews the newest draft.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import LEVELS, data_dir, root
from .schemas import Level

FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)
TAG_KINDS = ("industry", "function", "tech")
TAG_RX = re.compile(r"^[a-z0-9][a-z0-9-]{0,29}$")


def tags_config() -> dict:
    p = root() / "config" / "tags.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {"vocabulary": {}, "courses": {}}


def clean_tags(tags) -> dict:
    """Only {industry|function|tech: [lowercase-dash words]}, at most 6 per kind: anything else is dropped."""
    out = {}
    if isinstance(tags, dict):
        for k in TAG_KINDS:
            vals = tags.get(k) or []
            if isinstance(vals, list):
                out[k] = [v for v in dict.fromkeys(str(x).strip().lower() for x in vals) if TAG_RX.match(v)][:6]
    return out


@dataclass
class Course:
    slug: str
    title: str
    category: str
    summary: str
    docs: str
    source_page: str                      # relative path under sources/, or "" for an approved suggestion
    source_text: str = ""                 # plain text used for grounding checks
    source_md: str = ""
    aliases: list[str] = field(default_factory=list)
    vendor: str = ""
    tags: dict = field(default_factory=dict)        # {"industry": [...], "function": [...], "tech": [...]}

    def tag_list(self) -> list[str]:
        return [t for k in TAG_KINDS for t in self.tags.get(k, [])]

    @property
    def source_sha(self) -> str:
        return hashlib.sha256(self.source_md.encode()).hexdigest()[:16]


def plain(md: str, lower: bool = True) -> str:
    """Markdown → plain text, close enough for verbatim evidence matching."""
    t = FRONT.sub("", md)
    t = re.sub(r"```[a-z]*\n", "", t).replace("```", "")
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[*_`]+", "", t)
    t = re.sub(r"^#+\s*", "", t, flags=re.M)
    t = re.sub(r"^\|?[-:| ]+\|?$", "", t, flags=re.M)
    t = t.replace("|", " ")
    return norm(t) if lower else re.sub(r"\s+", " ", t).strip()


def norm(text: str) -> str:
    t = text.lower().replace("’", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
    t = re.sub(r"[*_`]+", "", t)
    return re.sub(r"\s+", " ", t).strip()


def sources_dir() -> Path:
    return root() / "sources" / "tech"


def load_source(path: Path) -> Course:
    md = path.read_text()
    m = FRONT.match(md)
    meta = yaml.safe_load(m.group(1)) if m else {}
    return Course(slug=path.stem, title=meta.get("title", path.stem), category=meta.get("category", "Other"),
                  summary=meta.get("summary", ""), docs=meta.get("docs", ""),
                  source_page=f"tech/{path.name}", source_text=plain(md), source_md=md,
                  aliases=[a for a in meta.get("aliases", []) if isinstance(a, str)], vendor=meta.get("vendor", ""))


def bundled() -> dict[str, Course]:
    tagged = tags_config().get("courses") or {}
    out = {}
    for p in sorted(sources_dir().glob("*.md")):
        if p.stem != "index":
            c = load_source(p)
            c.tags = clean_tags(tagged.get(p.stem) or {})
            out[p.stem] = c
    return out


def all_courses(conn=None) -> dict[str, Course]:
    """Bundled tech courses plus approved suggestions (rows in the `courses` table)."""
    out = bundled()
    if conn is not None:
        for r in conn.execute("SELECT * FROM courses WHERE status='active'").fetchall():
            out[r["slug"]] = Course(slug=r["slug"], title=r["title"], category=r["category"] or "Suggested",
                                    summary=r["summary"] or "", docs=r["docs"] or "", source_page=r["docs"] or "",
                                    source_text=norm(r["source_text"] or ""), source_md=r["source_text"] or "",
                                    tags=clean_tags(json.loads(r["tags"]) if r["tags"] else {}))
    return out


def runtime_dir(slug: str) -> Path:
    return data_dir() / "warehouse" / "courses" / slug


def _versions(slug: str, level: str) -> list[Level]:
    """Every copy of a level: the bundled file (courses/<slug>/<level>.yaml, in git) and the runtime versions
    (<data>/warehouse/courses/<slug>/<level>.v<N>.yaml) written by builds, revisions and the owner's publish."""
    out = []
    paths = [root() / "courses" / slug / f"{level}.yaml", *sorted(runtime_dir(slug).glob(f"{level}.v*.yaml"))]
    for p in paths:
        if p.exists():
            out.append(Level.model_validate(yaml.safe_load(p.read_text())))
    return out


def load_level(slug: str, level: str, include_drafts: bool = False) -> Level | None:
    """Learners get the newest PUBLISHED version. With include_drafts, the newest version of any status (what the
    owner reviews next). A newer draft never hides the published version from learners."""
    vs = _versions(slug, level)
    if not include_drafts:
        vs = [v for v in vs if v.status == "published"]
    if not vs:
        return None
    # the same version can exist bundled and at runtime (after the owner publishes it): the runtime copy wins
    return max(enumerate(vs), key=lambda iv: (iv[1].version, iv[0]))[1]


def next_version(slug: str, level: str) -> int:
    return max((v.version for v in _versions(slug, level)), default=0) + 1


def save_level(lv: Level) -> Path:
    p = runtime_dir(lv.course) / f"{lv.level}.v{lv.version}.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dump(lv))
    return p


def dump(lv: Level) -> str:
    class D(yaml.SafeDumper):
        pass

    def s(dumper, data):
        style = "|" if "\n" in data else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)

    D.add_representer(str, s)
    return yaml.dump(lv.model_dump(exclude_defaults=False), Dumper=D, sort_keys=False, allow_unicode=True, width=110)


def level_status(slug: str) -> dict[str, str]:
    """published | draft | missing, per level (what the tracker and the operator app show). "draft" means a newer
    version than the published one is waiting for the owner."""
    out = {}
    for lv in LEVELS:
        pub = load_level(slug, lv)
        newest = load_level(slug, lv, include_drafts=True)
        if newest and newest.status == "draft" and (not pub or newest.version > pub.version):
            out[lv] = "draft" if not pub else "published"
        else:
            out[lv] = "published" if pub else "missing"
    return out


def has_pending_draft(slug: str, level: str) -> bool:
    newest = load_level(slug, level, include_drafts=True)
    pub = load_level(slug, level)
    return bool(newest and newest.status == "draft" and (not pub or newest.version > pub.version))
