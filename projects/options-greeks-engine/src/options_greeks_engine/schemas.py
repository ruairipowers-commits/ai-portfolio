"""Structured output contracts for the two model calls (SEC-04)."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Leg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    side: Literal["BUY", "SELL"]
    quantity: int = Field(ge=1, le=100_000)
    option_type: Literal["CALL", "PUT"]
    strike: float = Field(gt=0)
    expiry: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class TradeParse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["OK", "CLARIFY"]
    legs: list[Leg] = Field(default_factory=list, max_length=8)
    limit_price: float | None = None
    price_type: Literal["DEBIT", "CREDIT"] | None = None
    clarification: str | None = Field(default=None, max_length=300)
    notes: list[str] = Field(default_factory=list, max_length=5)


class Figure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str
    value: float | int | str | None


class RiskExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket_id: str
    summary: str = Field(max_length=900)
    figures: list[Figure] = Field(min_length=2, max_length=16)
    risks: list[str] = Field(default_factory=list, max_length=8)


def parse_json_schema() -> str:
    return json.dumps(TradeParse.model_json_schema(), indent=2)


def explain_json_schema() -> str:
    return json.dumps(RiskExplanation.model_json_schema(), indent=2)
