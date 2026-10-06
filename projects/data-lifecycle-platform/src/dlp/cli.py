"""`dlp` — the command line. Every command runs offline with the mock model unless an alias points elsewhere."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta

from sqlmodel import select

from . import (assess, catalog, commerce, context, evals, graph, licensing, lifecycle, marketplaces, monetize,
               ontology, pipeline, search, semantic, store)
from .config import ROOT, Settings
from .llm import Registry


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_data(a, s):
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_sample_data.py")], check=True)


def cmd_fetch(a, s):
    """Replace the offline fixture with real slices from the Hugging Face Hub (needs network + '.[hub]')."""
    hf = marketplaces.HuggingFace(live=True)
    landing = s.path("landing")
    hub = s["hub"]
    p = hf.download(hub["options_dataset"], landing / "options_iv.parquet", where_symbols=hub["slice_symbols"],
                    max_rows=hub["slice_max_rows"])
    import pandas as pd
    df = pd.read_parquet(p)
    want = {"symbol", "date", "ATM_IV", "hv_20", "VIX", "calls_contracts_traded", "puts_contracts_traded"}
    missing = want - set(df.columns)
    if missing:
        sys.exit(f"The Hub dataset's columns differ from the fixture: missing {sorted(missing)}.\n"
                 f"Real columns: {list(df.columns)}\nUpdate semantic/models/staging/stg_options.sql to match.")
    hf.download(hub["constituents_dataset"], landing / "constituents.parquet", max_rows=1000)
    card = hf.card(hub["options_dataset"])
    (ROOT / "data" / "seed" / "sources" / "hf_cards" / (hub["options_dataset"].replace("/", "__") + ".md")).write_text(card)
    (landing / "SOURCE").write_text("huggingface\n")
    print(f"fetched {len(df)} option rows for {df['symbol'].nunique()} symbols → {landing}; run `dlp build`")


def cmd_build(a, s):
    _print(pipeline.build(s, reseed=not a.keep_catalog))


def cmd_all(a, s):
    rep = pipeline.build(s)
    print(f"build: {rep['semantic']['tests_passed']} data tests passed, graph {rep['graph']['instance_triples']} triples "
          f"(SHACL {'conforms' if rep['graph']['conforms'] else 'FAILED'}), {rep['seconds']}s, data: {rep['landing']}")
    r = evals.run_eval(s)
    print(f"eval: {'PASS' if r['passed'] else 'FAIL'} {r['metrics']}")
    return 0 if r["passed"] else 1


def cmd_ontology(a, s):
    if a.action == "check":
        probs = ontology.check()
        _print({"summary": ontology.summary(), "problems": probs})
        return 1 if probs else 0
    if a.action == "diff":
        old = subprocess.run(["git", "show", f"{a.ref}:projects/data-lifecycle-platform/ontology/dlp.ttl"],
                             capture_output=True, text=True, cwd=ROOT).stdout
        _print(ontology.diff(old, (ROOT / "ontology" / "dlp.ttl").read_text()))


def cmd_graph(a, s):
    if a.sparql:
        _print(graph.sparql(s, a.sparql))
    elif a.dataset:
        _print(graph.dataset_neighbourhood(s, a.dataset))
    else:
        _print({"info": graph.info(s), "counts": graph.counts(s)})


def cmd_metric(a, s):
    r = semantic.query(s, a.metrics.split(","), a.by.split(",") if a.by else None)
    _print({"rows": r.rows, "sql": r.sql if a.sql else r.query_id})


def cmd_search(a, s):
    _print(search.run(s, a.need, a.customer, actor=a.actor))


def cmd_ask(a, s):
    r = context.answer(s, a.question, a.customer, actor=a.actor)
    _print({"status": r.status, "answer": r.answer, "citations": r.citations, "checks": r.checks,
            "packet_tokens": r.packet.token_estimate, "excluded": r.packet.excluded, "model": r.model})


def cmd_assess(a, s):
    if len(a.datasets) > 1:
        _print(assess.compare(s, a.datasets, a.customer))
    else:
        _print(assess.assess(s, a.datasets[0], a.customer, actor=a.actor))


def cmd_extract(a, s):
    text = open(a.file).read()
    ap = catalog.extract(s, text, a.url or a.file, actor=a.actor)
    _print({"approval_id": ap.id, "flags": ap.flags, "draft": ap.payload})


def cmd_approvals(a, s):
    with store.session(s) as ss:
        _print([{"id": x.id, "kind": x.kind, "subject": x.subject_id, "flags": x.flags, "requested_by": x.requested_by}
                for x in catalog.pending(ss, a.kind)])


def cmd_decide(a, s):
    x = catalog.decide(s, a.approval_id, a.reviewer, a.approve, a.note or "")
    print(f"{x.id} {x.status} by {x.decided_by}")
    pipeline.refresh_graph(s)


def cmd_licence(a, s):
    with store.session(s) as ss:
        _print(licensing.matrix(ss, s, a.customer))


def cmd_register(a, s):
    _print(commerce.register(s, a.customer, a.dataset, a.use, a.actor))


def cmd_subscribe(a, s):
    _print(commerce.subscribe(s, a.customer, a.datasets, date.fromisoformat(a.start), date.fromisoformat(a.end),
                              a.price, a.use, a.actor, a.notice_days, a.auto_renew))


def cmd_roi(a, s):
    _print({"roi": lifecycle.roi(s, a.customer), "candidates": lifecycle.candidates(s, a.customer) if a.customer else [],
            "budget": lifecycle.budget(s, a.customer) if a.customer else None})


def cmd_retire(a, s):
    _print(lifecycle.request_retirement(s, a.dataset, a.actor, a.customer, a.substitute))


def cmd_monetize(a, s):
    o = monetize.submit(s, a.company, open(a.description).read(), a.sample)
    _print(monetize.assess(s, o.id, actor=a.actor))


def cmd_marketplace(a, s):
    if a.name == "all":
        _print([l.to_dict() for l in marketplaces.search_all(a.query)])
    else:
        ad = marketplaces.get(a.name, **({"live": True} if a.live and a.name == "huggingface" else {}))
        _print([l.to_dict() for l in ad.search(a.query)])


def cmd_alpha(a, s):
    _print(assess.iv_hv_check(s, a.horizon))


def cmd_eval(a, s):
    r = evals.run_eval(s, a.alias)
    _print({"passed": r["passed"], "failures": r["failures"], "metrics": r["metrics"], "model": r["model_name"]})
    if a.baseline:
        base = evals.latest(Registry(ROOT / "config" / "models.yaml").resolve(a.baseline).name)
        if base:
            reg = evals.compare(r, base)
            print("regressions vs baseline:", reg or "none")
            if reg:
                return 1
    return 0 if r["passed"] else 1


def cmd_promote(a, s):
    reg = Registry(ROOT / "config" / "models.yaml")
    rep = evals.latest(a.model)
    if not rep or not rep["passed"]:
        sys.exit(f"Refusing to promote {a.model}: no passing eval on record (MODEL-02).")
    from .ai import Runner
    current = {k: Runner(s).prompt(k)[2] for k in s["llm"]["prompts"]}
    if rep["prompt_shas"] != current:
        sys.exit("Refusing to promote: a prompt changed since the last eval. Re-run `dlp eval`.")
    reg.set_alias(a.alias, a.model)
    print(f"{a.alias} -> {a.model} (eval {rep['ts']} passed)")


def cmd_models_check(a, s):
    reg = Registry(ROOT / "config" / "models.yaml")
    warn = s["governance"]["deprecation_warning_days"]
    issues = 0
    for name, m in reg.models.items():
        notes = []
        if not m.approved:
            notes.append("not approved")
        if not m.priced():
            notes.append("no pricing")
        if m.deprecation_date and m.deprecation_date - date.today() <= timedelta(days=warn):
            notes.append(f"deprecates {m.deprecation_date} — start the migration runbook (docs/governance.md)")
            issues += 1
        used = [al for al, n in reg.aliases.items() if n == name]
        print(f"{name:16s} {m.provider:9s} aliases={used or '-'} {'; '.join(notes) or 'ok'}")
    return 1 if issues else 0


def cmd_cost_report(a, s):
    with store.session(s) as ss:
        calls = ss.exec(select(store.AICall)).all()
    rows: dict[tuple, list] = {}
    for c in calls:
        k = (c.ts.strftime("%Y-%m"), c.model_name, c.purpose, "eval" if c.run_id.startswith("eval-") else "prod")
        r = rows.setdefault(k, [0, 0, 0, 0.0])
        r[0] += 1; r[1] += c.input_tokens; r[2] += c.output_tokens; r[3] += c.cost_usd
    print(f"{'month':8s} {'model':12s} {'purpose':9s} {'kind':5s} {'calls':>6s} {'in_tok':>8s} {'out_tok':>8s} {'usd':>9s}")
    totals: dict[str, float] = {}
    for (mo, mn, p, kind), (n, ti, to, usd) in sorted(rows.items()):
        totals[mo] = totals.get(mo, 0) + usd
        print(f"{mo:8s} {mn:12s} {p:9s} {kind:5s} {n:6d} {ti:8d} {to:8d} {usd:9.4f}")
    limit = s["cost"]["monthly_alert_usd"]
    for mo, usd in totals.items():
        print(f"{mo} total ${usd:.4f} vs alert ${limit:.2f} (reviewer: {s['cost']['reviewer']})" +
              ("  <-- OVER ALERT (COST-04)" if usd > limit else ""))
    print(f"budget-blocked calls: {sum(1 for c in calls if c.status == 'budget_exceeded')}")


def cmd_ui(a, s):
    os.execvp("streamlit", ["streamlit", "run", str(ROOT / "src" / "dlp" / "ui.py")])


def cmd_api(a, s):
    import uvicorn
    uvicorn.run("dlp.api:app", host=a.host, port=a.port)


def cmd_token(a, s):
    from .api import issue_token
    print(issue_token(a.principal))


def cmd_mcp(a, s):
    from .mcp_server import main as mcp_main
    mcp_main()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="dlp", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    def actor(sp):
        sp.add_argument("--actor", default=os.getenv("USER", "cli"))

    add("data", cmd_data, "build the offline fixture in data/landing")
    add("fetch", cmd_fetch, "real Hugging Face slices (needs network)")
    b = add("build", cmd_build, "seed → dbt build + tests → SHACL → graph"); b.add_argument("--keep-catalog", action="store_true")
    add("all", cmd_all, "build, then the eval gate")
    o = add("ontology", cmd_ontology, "check or diff the ontology"); o.add_argument("action", choices=["check", "diff"]); o.add_argument("--ref", default="HEAD~1")
    g = add("graph", cmd_graph, "graph counts, a dataset's neighbourhood, or SPARQL"); g.add_argument("--dataset"); g.add_argument("--sparql")
    m = add("metric", cmd_metric, "query governed metrics"); m.add_argument("metrics"); m.add_argument("--by"); m.add_argument("--sql", action="store_true")
    se = add("search", cmd_search, "AI data search"); se.add_argument("need"); se.add_argument("--customer"); actor(se)
    q = add("ask", cmd_ask, "question → context packet → grounded answer"); q.add_argument("question"); q.add_argument("--customer", required=True); actor(q)
    asx = add("assess", cmd_assess, "assess one dataset, or compare 2–4"); asx.add_argument("datasets", nargs="+"); asx.add_argument("--customer"); actor(asx)
    ex = add("extract", cmd_extract, "draft catalog records from a source file"); ex.add_argument("file"); ex.add_argument("--url"); actor(ex)
    ap = add("approvals", cmd_approvals, "pending approvals"); ap.add_argument("--kind")
    for name, ok in (("approve", True), ("reject", False)):
        d = add(name, cmd_decide, f"{name} a pending action"); d.add_argument("approval_id"); d.add_argument("--reviewer", required=True); d.add_argument("--note"); d.set_defaults(approve=ok)
    li = add("licence", cmd_licence, "licence verdict matrix"); li.add_argument("--customer")
    rg = add("register", cmd_register, "register a free dataset"); rg.add_argument("customer"); rg.add_argument("dataset"); rg.add_argument("--use", nargs="+", default=["v:InternalResearch"]); actor(rg)
    sb = add("subscribe", cmd_subscribe, "draft a paid contract"); sb.add_argument("customer"); sb.add_argument("datasets", nargs="+")
    sb.add_argument("--start", required=True); sb.add_argument("--end", required=True); sb.add_argument("--price", type=float, required=True)
    sb.add_argument("--use", nargs="+", default=["v:InternalResearch"]); sb.add_argument("--notice-days", type=int, default=30); sb.add_argument("--auto-renew", action="store_true"); actor(sb)
    ro = add("roi", cmd_roi, "spend, usage, cost per query, candidates"); ro.add_argument("--customer")
    rt = add("retire", cmd_retire, "impact-checked retirement request"); rt.add_argument("dataset"); rt.add_argument("--customer"); rt.add_argument("--substitute"); actor(rt)
    mo = add("monetize", cmd_monetize, "assess a data owner's sample"); mo.add_argument("company"); mo.add_argument("description"); mo.add_argument("sample"); actor(mo)
    mk = add("marketplace", cmd_marketplace, "search a marketplace"); mk.add_argument("query"); mk.add_argument("--name", default="all"); mk.add_argument("--live", action="store_true")
    al = add("alpha-check", cmd_alpha, "IV–HV spread test on the options data"); al.add_argument("--horizon", type=int, default=10)
    e = add("eval", cmd_eval, "golden-set gate; non-zero exit on failure"); e.add_argument("--alias"); e.add_argument("--baseline")
    pr = add("promote", cmd_promote, "point an alias at a model that passed evals"); pr.add_argument("alias"); pr.add_argument("model")
    add("models-check", cmd_models_check, "approval, pricing and deprecation check")
    add("cost-report", cmd_cost_report, "tokens and $ by month, model and purpose")
    add("ui", cmd_ui, "Streamlit app")
    api = add("api", cmd_api, "REST API (FastAPI)"); api.add_argument("--host", default="127.0.0.1"); api.add_argument("--port", type=int, default=8700)
    tk = add("api-token", cmd_token, "issue an API token for a customer id or 'operator'"); tk.add_argument("principal")
    add("mcp", cmd_mcp, "read-only MCP server (stdio)")
    a = p.parse_args(argv)
    return a.fn(a, Settings.load()) or 0


if __name__ == "__main__":
    raise SystemExit(main())
