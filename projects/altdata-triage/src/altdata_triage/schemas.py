"""Structured output contract for the LLM (SEC-04)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Recommendation = Literal["PURSUE", "PARK", "REJECT", "ESCALATE"]


class Evidence(BaseModel):
    metric: str = Field(description="Exact field name from <vendor_facts>")
    value: float | int | bool | str = Field(description="Exact value from <vendor_facts>")


class TriageMemo(BaseModel):
    vendor_id: str
    recommendation: Recommendation
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(max_length=800)
    strengths: list[str] = Field(default_factory=list, max_length=6)
    risks: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[Evidence] = Field(min_length=1, max_length=10)
    next_steps: list[str] = Field(default_factory=list, max_length=5)


class TriageResult(BaseModel):
    """What the pipeline stores: the LLM memo plus deterministic post-processing."""

    memo: TriageMemo
    llm_recommendation: Recommendation
    final_recommendation: Recommendation
    policy_overrides: list[str] = Field(default_factory=list)
    citation_errors: list[str] = Field(default_factory=list)
    schema_valid: bool = True
    injection_suspected: bool = False
    pii_redactions: int = 0
    model_name: str = ""
    cost_usd: float = 0.0


def memo_json_schema() -> str:
    import json

    return json.dumps(TriageMemo.model_json_schema(), indent=2)
