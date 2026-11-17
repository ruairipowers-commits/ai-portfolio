"""Structured output contract for the model (SEC-04)."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Disposition = Literal["ESCALATE", "NEEDS_INFO", "CLOSE"]


class Figure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="Exact key from <alert_facts>")
    value: float | int | str = Field(description="Exact value from <alert_facts>")


class AlertNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alert_id: str
    pattern: Literal["layering", "wash", "stuffing", "ignition"]
    summary: str = Field(max_length=900)
    sequence: list[str] = Field(default_factory=list, max_length=8, description="What happened, in order")
    cited_events: list[int] = Field(min_length=1, max_length=40)
    figures: list[Figure] = Field(min_length=1, max_length=12)
    observations: list[str] = Field(default_factory=list, max_length=6)
    suggested_disposition: Disposition
    confidence: float = Field(ge=0, le=1)


class AlertResult(BaseModel):
    """What the workflow stores: the model's narrative plus deterministic post-processing."""
    alert_id: str
    pattern: str
    severity: str
    narrative: AlertNarrative
    model_suggestion: Disposition
    final_suggestion: Disposition
    policy_overrides: list[str] = Field(default_factory=list)
    citation_errors: list[str] = Field(default_factory=list)
    schema_valid: bool = True
    injection_suspected: bool = False
    pii_redactions: int = 0
    model_name: str = ""
    cost_usd: float = 0.0


def narrative_json_schema() -> str:
    return json.dumps(AlertNarrative.model_json_schema(), indent=2)
