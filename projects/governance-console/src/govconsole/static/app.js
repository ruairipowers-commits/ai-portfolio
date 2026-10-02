/* Dashboard charts. Data comes from /api/summary; every label is inserted with textContent (untrusted). */
(function () {
  const FLAG_TEXT = {
    injection_detected: "Prompt-injection text caught (SEC-02)",
    quarantined_content: "Document chunks quarantined at ingest (SEC-02)",
    bank_change_request: "Payment-fraud pattern escalated (SEC-02)",
    escalated: "Escalated to a human by policy (HITL-02)",
    policy_override: "Deterministic policy overrode the model",
    human_override: "Reviewer disagreed with the AI (HITL-03)",
    edited_by_human: "Approver edited the AI's draft (HITL-03)",
    marked_wrong: "User marked an answer wrong (HITL-03)",
    entitlement_filtered: "Retrieval narrowed by entitlements (DATA-04)",
    licence_excluded: "Licence-restricted content excluded (DATA-04)",
    pii_redacted: "PII redacted before the model (DATA-03)",
    budget_blocked: "Stopped by a budget cap (COST-01)",
    step_or_budget_cap: "Agent hit its step / cost cap (COST-01)",
    dq_gate_failed: "Blocked by the data-quality gate (DATA-02)",
    citation_error: "Citation failed verification (OBS-02)",
    evidence_mismatch: "Evidence didn't match the source (OBS-02)",
    eval_failed: "Eval gate failed (MODEL-02)",
    kill_switch: "Attempt blocked by the kill switch",
    write_failed: "Approved write failed",
    model_not_approved: "Unapproved model refused (SEC-05)",
    late_file: "Late input file detected",
  };
  const charts = {};
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const qs = () => new URLSearchParams(location.search);

  function color(slug, order) {
    const i = order.indexOf(slug);
    return css(i >= 0 && i < 8 ? `--s${i + 1}` : "--other");
  }
  const usd = (v, dp = 2) => (v > 0 && v < 0.01 && dp === 2 ? "$" + Number(v).toFixed(4) : "$" + Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp }));
  // axis ticks: whole dollars once values reach $10, cents below that (so small workflows don't read "$0, $0, $0")
  const usdTick = (v, axis) => usd(v, axis ? (Math.abs(v) >= 10 || v === 0 ? 0 : 2) : 2);
  const int = (v) => Number(v || 0).toLocaleString();
  const compact = (v) => Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(v || 0);
  const shortDay = (d) => new Date(d + "T00:00:00Z").toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });

  function baseOptions(yFmt, stacked, legend) {
    const ink2 = css("--ink-2"), muted = css("--muted"), grid = css("--grid");
    return {
      responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: legend, position: "bottom", labels: { color: ink2, boxWidth: 10, boxHeight: 10, usePointStyle: false, padding: 14 } },
        tooltip: {
          backgroundColor: css("--surface"), titleColor: css("--ink"), bodyColor: css("--ink"), borderColor: css("--border"),
          borderWidth: 1, padding: 10, boxWidth: 12, boxHeight: 2, usePointStyle: false,
          filter: (item) => item.raw !== 0,
          callbacks: { label: (c) => ` ${yFmt(c.raw)}  ${c.dataset.label}` },
        },
      },
      scales: {
        x: { stacked, grid: { display: false }, border: { color: css("--axis") },
             ticks: { color: muted, maxRotation: 0, autoSkipPadding: 18, callback: function (v) { return shortDay(this.getLabelForValue(v)); } } },
        y: { stacked, beginAtZero: true, grid: { color: grid }, border: { display: false },
             ticks: { color: muted, callback: (v) => yFmt(v, true) } },
      },
    };
  }

  function draw(id, type, labels, datasets, yFmt, { stacked = false, legend = true } = {}) {
    const el = document.getElementById(id);
    if (!el) return;
    charts[id]?.destroy();
    charts[id] = new Chart(el, { type, data: { labels, datasets }, options: baseOptions(yFmt, stacked, legend) });
  }

  function barSet(label, data, col) {
    return { label, data, backgroundColor: col, hoverBackgroundColor: col, borderColor: css("--surface"),
             borderWidth: { top: 2 }, borderSkipped: "bottom", borderRadius: 3, maxBarThickness: 28 };
  }
  function lineSet(label, data, col) {
    return { label, data, borderColor: col, backgroundColor: col, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4,
             pointHoverBorderColor: css("--surface"), pointHoverBorderWidth: 2, tension: 0.2 };
  }

  function el(tag, text, cls) {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }
  function table(container, head, rows, numeric = []) {
    const t = el("table"), thead = el("thead"), tr = el("tr");
    head.forEach((h, i) => tr.appendChild(el("th", h, numeric.includes(i) ? "n" : "")));
    thead.appendChild(tr);
    const tb = el("tbody");
    rows.forEach((r) => {
      const row = el("tr");
      r.forEach((c, i) => row.appendChild(el("td", c, numeric.includes(i) ? "n" : "")));
      tb.appendChild(row);
    });
    t.append(thead, tb);
    container.replaceChildren(t);
  }

  function delta(cur, prev) {
    if (!prev) return cur ? "new this period" : "no activity";
    const pct = ((cur - prev) / prev) * 100;
    return `${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct).toFixed(0)}% vs previous period`;
  }
  function fillKpis(d) {
    const k = d.kpi, p = d.prev;
    const vals = [
      [usd(k.cost), delta(k.cost, p.cost)], [int(k.runs), delta(k.runs, p.runs)], [int(k.users), delta(k.users, p.users)],
      [int(k.decisions), delta(k.decisions, p.decisions)], [compact(k.tokens), delta(k.tokens, p.tokens)],
      [compact(k.records_in), delta(k.records_in, p.records_in)],
      [(100 * k.escalation_rate).toFixed(1) + "%", `${int(k.escalated)} of ${int(k.runs)} runs`],
      [k.p95_latency_ms ? (k.p95_latency_ms / 1000).toFixed(1) + " s" : "—", `${int(k.blocked)} blocked · ${int(k.errors)} errors`],
    ];
    document.querySelectorAll("#kpis .kpi").forEach((card, i) => {
      if (!vals[i]) return;
      card.querySelector(".value").textContent = vals[i][0];
      card.querySelector(".delta").textContent = vals[i][1];
    });
  }

  async function fetchSummary(extra) {
    const p = qs();
    Object.entries(extra || {}).forEach(([k, v]) => p.set(k, v));
    document.querySelectorAll(".chart-box").forEach((b) => b.classList.add("loading"));
    const r = await fetch("/api/summary?" + p.toString());
    const d = await r.json();
    document.querySelectorAll(".chart-box").forEach((b) => b.classList.remove("loading"));
    return d;
  }

  function overviewRender(d, opts) {
    const order = d.workflow_order.length ? d.workflow_order : opts.order;
    const name = (s) => opts.names[s] || s;
    fillKpis(d);
    const wfs = order.filter((w) => d.series.cost[w]);
    draw("c-cost", "bar", d.days, wfs.map((w) => barSet(name(w), d.series.cost[w], color(w, opts.order))),
         usdTick, { stacked: true, legend: wfs.length > 1 });
    draw("c-cum", "line", d.days, [lineSet("Cumulative AI spend", d.cumulative_cost, css("--ink-2"))],
         usdTick, { legend: false });
    const rw = order.filter((w) => d.series.runs[w]);
    draw("c-runs", "bar", d.days, rw.map((w) => barSet(name(w), d.series.runs[w], color(w, opts.order))),
         (v) => int(v), { stacked: true, legend: rw.length > 1 });
    const rec = d.days.map((_, i) => Object.values(d.series.records_in).reduce((a, s) => a + s[i], 0));
    draw("c-rec", "line", d.days, [lineSet("Records processed", rec, css("--s1"))], (v) => compact(v), { legend: false });

    const tc = document.getElementById("t-cost");
    if (tc) table(tc, ["Day", ...wfs.map(name), "Total"],
      d.days.map((day, i) => [day, ...wfs.map((w) => usd(d.series.cost[w][i])), usd(wfs.reduce((a, w) => a + d.series.cost[w][i], 0))]),
      wfs.map((_, i) => i + 1).concat([wfs.length + 1]));
    const fl = document.getElementById("flags");
    if (fl) {
      const rows = Object.entries(d.flags).map(([f, n]) => [FLAG_TEXT[f] || f, f, int(n)]);
      rows.length ? table(fl, ["Signal", "Flag", "Events"], rows, [2]) : fl.replaceChildren(el("p", "No flagged events in range.", "muted"));
    }
    const md = document.getElementById("models");
    if (md) table(md, ["Model", "Events", "Input tokens", "Output tokens", "Spend"],
      d.by_model.map((m) => [m.model, int(m.calls), compact(m.input_tokens), compact(m.output_tokens), usd(m.cost)]), [1, 2, 3, 4]);
  }

  function workflowRender(d, opts) {
    fillKpis(d);
    const s = opts.slug, col = color(s, opts.order);
    const cost = d.series.cost[s] || d.days.map(() => 0);
    const runs = d.series.runs[s] || d.days.map(() => 0);
    const esc = d.series.escalated[s] || d.days.map(() => 0);
    const err = d.series.errors[s] || d.days.map(() => 0);
    draw("c-cost", "bar", d.days, [barSet("AI spend", cost, col)], usdTick, { legend: false });
    draw("c-cum", "line", d.days, [lineSet("Cumulative AI spend", d.cumulative_cost, css("--ink-2"))], usdTick, { legend: false });
    draw("c-runs", "bar", d.days, [
      barSet("Completed", runs.map((r, i) => Math.max(0, r - esc[i] - err[i])), col),
      barSet("Escalated / refused", esc, css("--warning")),
      barSet("Errors", err, css("--critical")),
    ], (v) => int(v), { stacked: true, legend: true });
    draw("c-rec", "line", d.days, [lineSet("Records processed", d.series.records_in[s] || d.days.map(() => 0), col)], (v) => compact(v), { legend: false });
    const md = document.getElementById("models");
    if (md) table(md, ["Model", "Events", "Input tokens", "Output tokens", "Spend"],
      d.by_model.map((m) => [m.model, int(m.calls), compact(m.input_tokens), compact(m.output_tokens), usd(m.cost)]), [1, 2, 3, 4]);
  }

  async function run(render, opts, extra) {
    const d = await fetchSummary(extra);
    render(d, opts);
    window.addEventListener("themechange", () => render(d, opts));
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => render(d, opts));
    setInterval(async () => render(await fetchSummary(extra), opts), 60000);   // live tail
  }

  window.Gov = {
    overview: (opts) => run(overviewRender, opts),
    workflow: (opts) => run(workflowRender, opts, { wf: opts.slug }),
  };
})();
