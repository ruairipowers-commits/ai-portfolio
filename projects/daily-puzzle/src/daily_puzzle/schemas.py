"""Model output schemas (SEC-04): every draft and every solver reply is validated before anything uses it."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .config import TRACKS


class AssetRef(BaseModel):
    id: str = Field(max_length=120)
    files: list[str] = Field(default_factory=list, max_length=8)
    revision: str | None = None


class Draft(BaseModel):
    track: str
    kind: str = Field(max_length=32)
    difficulty: Literal["easy", "medium", "hard"]
    title: str = Field(min_length=3, max_length=120)
    statement: str = Field(min_length=20, max_length=4000)
    answer: str = Field(min_length=1, max_length=200)
    answer_type: Literal["text", "int", "float"]
    decimals: int | None = Field(default=None, ge=0, le=8)
    accepted_forms: list[str] = Field(default_factory=list, max_length=32)
    answer_format: str = Field(default="", max_length=200)
    learning_objective: str = Field(default="", max_length=600)
    skill_tags: list[str] = Field(default_factory=list, max_length=10)
    starter: str = Field(default="", max_length=3000)
    solution: str = Field(default="", max_length=4000)
    reference_code: str = Field(default="", max_length=12000)
    assets: list[AssetRef] = Field(default_factory=list, max_length=4)
    spec: dict = Field(default_factory=dict)

    @field_validator("track")
    @classmethod
    def _track(cls, v):
        if v not in TRACKS:
            raise ValueError(f"unknown track {v}")
        return v

    @model_validator(mode="after")
    def _float_needs_decimals(self):
        if self.answer_type == "float" and self.decimals is None:
            raise ValueError("float answers need `decimals`")
        return self


class SolverReply(BaseModel):
    answer: str | None = Field(default=None, max_length=200)
    code: str | None = Field(default=None, max_length=12000)
    other_valid_answers: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(default=0.5, ge=0, le=1)
    reasoning: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _one_of(self):
        if not (self.answer or self.code):
            raise ValueError("solver gave neither an answer nor code")
        return self
