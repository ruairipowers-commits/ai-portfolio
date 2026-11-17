"""Structured output contract for the model (SEC-04)."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Recommendation = Literal["PROMOTE", "MORE_RESEARCH", "REJECT"]


class Figure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str = Field(description="Exact key from <run_metrics> or <promotion_checks>")
    value: float | int | str | bool | None


class Headline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    net_sharpe: float
    net_total_return: float
    max_drawdown: float


class ResearchMemo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    strategy: str
    thesis: str = Field(max_length=900)
    headline: Headline
    figures: list[Figure] = Field(min_length=3, max_length=20)
    risks: list[str] = Field(default_factory=list, max_length=10)
    disclosures: list[str] = Field(default_factory=list, max_length=6)
    recommendation: Recommendation
    confidence: float = Field(ge=0, le=1)


class MemoResult(BaseModel):
    memo: ResearchMemo
    model_recommendation: Recommendation
    final_recommendation: Recommendation
    promotable: bool
    blockers: list[str] = Field(default_factory=list)
    citation_errors: list[str] = Field(default_factory=list)
    compliance_errors: list[str] = Field(default_factory=list)
    schema_valid: bool = True
    injection_suspected: bool = False
    pii_redactions: int = 0
    model_name: str = ""
    cost_usd: float = 0.0


def memo_json_schema() -> str:
    return json.dumps(ResearchMemo.model_json_schema(), indent=2)
