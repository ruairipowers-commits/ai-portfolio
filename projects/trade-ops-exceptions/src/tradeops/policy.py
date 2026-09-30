"""Proposal contract (SEC-04), deterministic policy, injection screening and approval tokens."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["QUANTITY_MISMATCH", "PRICE_MISMATCH", "SETTLE_DATE_MISMATCH", "SSI_MISMATCH",
                   "MISSING_CONFIRM", "ALLOCATION_MISMATCH", "UNKNOWN"]
FixType = Literal["AMEND_INTERNAL", "REQUEST_BROKER_CORRECTION", "CHASE_CONFIRM", "ESCALATE"]


class Evidence(BaseModel):
    tool: str = Field(description="Tool that returned the value, e.g. get_trade")
    field: str = Field(description="Field name in that tool's result")
    value: str | int | float | bool | None = Field(description="Value exactly as returned")


class EmailDraft(BaseModel):
    recipient: str = Field(description="Counterparty (broker name); ops will map to the address on file")
    subject: str = Field(max_length=200)
    body: str = Field(max_length=3000)


class Proposal(BaseModel):
    """Submit your investigation result for human approval."""

    exception_id: str
    category: Category
    root_cause: str = Field(max_length=1200)
    fix_type: FixType
    fix_details: str = Field(max_length=1200, description="Exactly what should change, e.g. 'amend booked quantity 5250 -> 5000'")
    evidence: list[Evidence] = Field(min_length=1, max_length=12)
    email_draft: EmailDraft | None = None
    confidence: float = Field(ge=0, le=1)


# --------------------------------------------------------------------- screening
INJECTION = [r"ignore (all |any )?(prior|previous|above) instructions", r"^\s*system\s*:", r"\bsystem\s*:",
             r"you are (now )?authori[sz]ed", r"\bapprove this\b", r"cancel and rebook", r"reveal (your )?prompt"]
SSI_CHANGE = [r"bank details (have )?changed", r"update (your|the) ssi", r"new (bank )?account", r"change of (bank|settlement) (details|instructions)"]


def scan_tool_result(text: str) -> list[str]:
    flags = []
    if any(re.search(p, text, re.I | re.M) for p in INJECTION):
        flags.append("injection_suspected")
    if any(re.search(p, text, re.I) for p in SSI_CHANGE):
        flags.append("ssi_change_request")
    return flags


def _flatten(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten(v, f"{prefix}{k}.")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _flatten(v, f"{prefix}{i}.")
    else:
        yield prefix.rstrip("."), obj


def check_evidence(p: Proposal, tool_results: list[tuple[str, str]]) -> list[str]:
    """OBS-02: each cited (tool, field, value) must appear in a result of that tool."""
    by_tool: dict[str, list[dict]] = {}
    for name, text in tool_results:
        try:
            by_tool.setdefault(name, []).append(json.loads(text))
        except (ValueError, TypeError):
            pass
    errors = []
    for ev in p.evidence:
        found = False
        for res in by_tool.get(ev.tool, []):
            for path, val in _flatten(res):
                if path.split(".")[-1] == ev.field and _same(val, ev.value):
                    found = True
                    break
            if found:
                break
        if not found:
            errors.append(f"{ev.tool}.{ev.field}={ev.value!r} not found in tool results")
    return errors


def _same(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


def apply_policy(p: Proposal, flags: set[str], evidence_errors: list[str], hit_limits: bool,
                 tool_errors: int, policy: dict) -> tuple[str, list[str]]:
    """Deterministic gate after the model. Returns (status, reasons): awaiting_approval | escalated."""
    reasons = []
    if hit_limits:
        reasons.append("Step or budget limit reached before a confident proposal")
    if policy.get("escalate_on_injection") and "injection_suspected" in flags:
        reasons.append("Tool results contained instruction-like text (possible prompt injection)")
    if policy.get("escalate_on_ssi_change_request") and "ssi_change_request" in flags:
        reasons.append("Counterparty requested a bank-detail/SSI change: verify by call-back, never via email")
    if policy.get("escalate_on_tool_error") and tool_errors:
        reasons.append(f"{tool_errors} tool call(s) returned errors or malformed data")
    if policy.get("require_evidence_match") and evidence_errors:
        reasons.append("Cited evidence does not match source systems")
    if p.fix_type == "ESCALATE":
        reasons.append("Model escalated")
    allowed = policy.get("allowed_fixes", {}).get(p.category, [])
    if p.fix_type != "ESCALATE" and p.fix_type not in allowed:
        reasons.append(f"{p.fix_type} is not an allowed fix for {p.category}")
    return ("escalated" if reasons else "awaiting_approval"), reasons


# --------------------------------------------------------------------- approval tokens
def signing_key(root: Path, env_value: str | None) -> str:
    if env_value:
        return env_value
    path = root / "warehouse" / ".approval_key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def approval_fields(exception_id, category, fix_type, fix_details, email: dict | None, approver, approval_id, expires_at):
    e = email or {"recipient": "", "subject": "", "body": ""}
    return [exception_id, category, fix_type, fix_details, e["recipient"], e["subject"], e["body"],
            approver, approval_id, expires_at]


def mint_token(key: str, fields: list[str]) -> str:
    """Must match mcp-server/src/approval.ts exactly."""
    digest = _sha("|".join(_sha(f) for f in fields))
    return hmac.new(key.encode(), digest.encode(), hashlib.sha256).hexdigest()


def expiry(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
