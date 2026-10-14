"""The shapes everything is validated against (SEC-04): course levels, quiz questions, moderation assessments,
revision proposals. A model's reply is parsed into one of these or rejected; nothing a model writes is trusted
until it validates and passes the content checks."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LevelName = Literal["familiar", "beginner", "intermediate"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Question(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")
    prompt: str = Field(min_length=8, max_length=400)
    options: list[str] = Field(min_length=2, max_length=6)
    answer: int = Field(ge=0)                     # index into options; server-side only, never sent to a browser
    explanation: str = Field(min_length=8, max_length=600)
    evidence: str = Field(min_length=10, max_length=400)   # verbatim span of the source page or the level text

    @field_validator("options", mode="before")
    @classmethod
    def _as_text(cls, v):
        # YAML reads a bare year (2015) or a number as an int; an option is always text
        return [str(o) if isinstance(o, (int, float)) and not isinstance(o, bool) else o for o in v] if isinstance(v, list) else v

    @field_validator("answer")
    @classmethod
    def _in_range(cls, v, info):
        opts = info.data.get("options") or []
        if opts and v >= len(opts):
            raise ValueError(f"answer index {v} out of range for {len(opts)} options")
        return v


class Section(Strict):
    id: str
    heading: str
    body: str = Field(min_length=20)


class Project(Strict):
    title: str
    kind: Literal["runnable", "illustrative"] = "runnable"
    minutes: int = Field(ge=1, le=120)
    goal: str
    steps: list[str] = Field(min_length=1)
    code: str = ""
    language: str = ""
    expected: str = ""
    done_when: list[str] = Field(min_length=1)


class Module(Strict):
    id: str
    title: str
    minutes: int = Field(ge=10, le=60)
    body: str = Field(min_length=40)
    exercise: str = Field(min_length=20)
    check: list[Question] = Field(min_length=3)


class Source(Strict):
    page: str                                     # e.g. tech/streamlit.md, or a docs URL for approved suggestions
    sha: str = ""
    docs: str = ""


class Provenance(Strict):
    written_by: str                               # model alias + model id, or the build session
    prompt_hash: str = ""
    approved_by: str = ""
    approved_at: str = ""
    note: str = ""


class Level(Strict):
    course: str
    level: LevelName
    version: int = Field(ge=1)
    title: str
    status: Literal["draft", "published", "rejected"] = "draft"
    source: Source
    provenance: Provenance
    sections: list[Section] = Field(min_length=1)
    modules: list[Module] = []
    project: Project
    quiz: list[Question] = Field(min_length=3)

    def section(self, sid: str) -> Section | None:
        return next((s for s in self.sections if s.id == sid), None)

    def text(self) -> str:
        """All learner-facing prose (for reading time and as evidence for quiz grounding)."""
        parts = [s.heading + "\n" + s.body for s in self.sections]
        for m in self.modules:
            parts += [m.title, m.body, m.exercise] + [q.explanation for q in m.check]
        p = self.project
        parts += [p.title, p.goal, *p.steps, p.code, p.expected, *p.done_when]
        parts += [q.explanation for q in self.quiz]
        return "\n".join(parts)

    def all_questions(self) -> list[Question]:
        return [*self.quiz, *(q for m in self.modules for q in m.check)]


class Assessment(Strict):
    """The moderator's answer about a suggested topic. Advisory: only the owner's approval creates a course."""
    verdict: Literal["approve-recommended", "needs-review", "reject-recommended"]
    categories: list[str] = []
    reasons: list[str] = Field(min_length=1, max_length=6)
    duplicate_of: str | None = None
    learnable_in_format: bool = True
    proposed_title: str = Field(default="", max_length=80)
    proposed_outline: list[str] = Field(default=[], max_length=8)
    official_docs: str = ""


class Edit(Strict):
    target: str                                  # section id, "project", or "quiz:<qid>"
    change: str = Field(min_length=10, max_length=600)
    reason: str = Field(min_length=10, max_length=300)
    evidence: list[str] = []                     # feedback ids / item stats that support it
    touches_answer_key: bool = False


class Proposal(Strict):
    edits: list[Edit] = Field(max_length=10)
    summary: str = Field(max_length=400)
