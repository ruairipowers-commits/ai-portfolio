"""Output contracts for every model call (SEC-04). Anything that doesn't validate is rejected and falls back."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Extracted(BaseModel):
    value: Optional[str | float | list[str]] = None
    quote: str = ""                      # verbatim span from the source that supports the value


class ExtractedField(BaseModel):
    name: str
    type: str = "string"
    description: str = ""
    concept: Optional[str] = None        # vocabulary term proposed by the model; code re-checks it


class Extraction(BaseModel):
    """Vendor and dataset facts from a vendor page, dataset card or dictionary."""
    vendor: dict[str, Extracted] = Field(default_factory=dict)       # name, website, hq, docs_url, api_base_url
    dataset: dict[str, Extracted] = Field(default_factory=dict)      # title, description, coverage, history_start, …
    fields: list[ExtractedField] = Field(default_factory=list)
    notes: str = ""


class SearchPlan(BaseModel):
    """A natural-language data need, turned into terms chosen from the vocabulary list the prompt supplied."""
    concepts: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    factors: list[str] = Field(default_factory=list)
    free_only: bool = False
    needs_ai_processing: bool = False
    rationale: str = ""


class Answer(BaseModel):
    """An answer about the estate, written only from the context packet."""
    answer: str
    status: Literal["ANSWERED", "NOT_DEFINED", "NOT_ENTITLED", "NO_DATA"] = "ANSWERED"
    citations: list[str] = Field(default_factory=list)   # ids of packet items used (metric query ids, graph IRIs)


class AlphaIdea(BaseModel):
    hypothesis: str
    horizon: str = ""
    test: str = ""                       # how to test it; every idea is untested until someone does


class Assessment(BaseModel):
    summary: str
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    alpha_ideas: list[AlphaIdea] = Field(default_factory=list)
    recommendation: Literal["SHORTLIST", "TRIAL", "PASS", "LEGAL_REVIEW"] = "TRIAL"
    citations: list[str] = Field(default_factory=list)


class MonetizationAdvice(BaseModel):
    summary: str
    buyer_segments: list[str] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    packaging: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
