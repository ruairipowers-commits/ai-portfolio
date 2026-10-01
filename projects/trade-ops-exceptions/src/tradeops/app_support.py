"""Helpers for the Streamlit app: inputs, queue queries and resets. All writes to business data still go
through the approval-gated MCP tool; the only direct writes here are demo inputs (synthetic data reset,
editing a broker confirm's free text) which model what an outside party could send us."""
from __future__ import annotations

import os

from . import db
from .llm import Registry, RegistryError
from .runner import ROOT, db_url, load_settings

PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


def _con():
    s = load_settings()
    con = db.connect(db_url(s))
    db.ensure_audit(con, ROOT)
    return con


def server_built() -> bool:
    return (ROOT / "mcp-server" / "dist" / "index.js").exists()


def has_data() -> bool:
    con = _con()
    try:
        return bool(con.one("select count(*) as n from exceptions")["n"])
    except Exception:
        return False
    finally:
        con.close()


def reset() -> dict:
    """Regenerate the 40 synthetic exceptions and clear runs, approvals and checkpoints."""
    from .data import generate

    s = load_settings()
    out = generate(db_url(s), ROOT)
    for suffix in ("", "-wal", "-shm"):
        (ROOT / (s["checkpoint_db"] + suffix)).unlink(missing_ok=True)
    return out


def open_exceptions() -> list[dict]:
    con = _con()
    try:
        return con.query("""select e.exception_id, e.description, t.trade_id, t.side, t.quantity, t.ticker, t.broker,
                                   t.trade_date, e.status
                            from exceptions e join trades t using (trade_id) order by e.exception_id""")
    finally:
        con.close()


def confirm_text(exception_id: str) -> str | None:
    con = _con()
    try:
        r = con.one("""select c.free_text from broker_confirms c join exceptions e using (trade_id)
                       where e.exception_id = ?""", (exception_id,))
        return None if r is None else r["free_text"]
    finally:
        con.close()


def set_confirm_text(exception_id: str, text: str) -> None:
    """Demo input: simulate a broker sending different free text on the confirm."""
    con = _con()
    try:
        con.execute("""update broker_confirms set free_text = ?
                       where trade_id = (select trade_id from exceptions where exception_id = ?)""",
                    (text, exception_id))
        con.commit()
    finally:
        con.close()


def usable_aliases() -> dict[str, str]:
    s = load_settings()
    reg = Registry(ROOT / "config" / "models.yaml")
    targets, out = set(reg.aliases.values()), {}
    for name in list(reg.aliases) + [m for m in reg.models if m not in targets]:
        try:
            spec = reg.resolve(name)
        except RegistryError:
            continue
        if not spec.priced() and not s["cost"]["allow_unpriced_models"]:
            continue
        if PROVIDER_KEYS.get(spec.provider) and not os.getenv(PROVIDER_KEYS[spec.provider]):
            continue
        out[f"{name} → {spec.name}" if name in reg.aliases else name] = name
    return out


def latest_runs(status: str | None = None) -> list[dict]:
    """Most recent non-eval run per exception (re-investigating replaces the earlier proposal)."""
    con = _con()
    try:
        rows = con.query("""select r.* from agent_runs r
                            join (select exception_id, max(started_at) as ts from agent_runs
                                  where run_id not like 'eval-%' group by exception_id) l
                              on r.exception_id = l.exception_id and r.started_at = l.ts
                            where r.run_id not like 'eval-%' order by r.exception_id""")
        return [r for r in rows if status is None or r["status"] == status]
    finally:
        con.close()


def steps(thread_id: str) -> list[dict]:
    con = _con()
    try:
        return con.query("""select step, kind, name, args_json as args, flag, input_tokens, output_tokens,
                                   round(cost_usd, 5) as cost_usd, result_preview
                            from agent_steps where thread_id = ? order by step""", (thread_id,))
    finally:
        con.close()


def table(sql: str) -> list[dict]:
    con = _con()
    try:
        return con.query(sql)
    finally:
        con.close()
