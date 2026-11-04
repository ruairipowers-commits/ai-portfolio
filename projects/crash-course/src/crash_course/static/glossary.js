/* Glossary on course pages: hover definitions for approved terms, and highlight-to-look-up for anything else.
   Everything from the server is inserted with textContent — never as HTML. */
(function () {
  const root = document.querySelector("article.content[data-glossary]");
  const dataEl = document.getElementById("glossary-terms");
  if (!root || !dataEl) return;
  const base = root.dataset.root || "", course = root.dataset.course || "", signedIn = root.dataset.signedIn === "1";
  const terms = JSON.parse(dataEl.textContent || "[]");
  const SKIP = new Set(["CODE", "PRE", "A", "H1", "H2", "H3", "H4", "BUTTON", "SCRIPT", "STYLE", "TEXTAREA", "INPUT"]);

  // ---------- hover definitions: the first use of each approved term in the page
  const esc = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const used = new Set();
  function mark(node) {
    for (const t of terms) {
      if (used.has(t.term)) continue;
      const acronym = t.term === t.term.toUpperCase();
      const re = new RegExp("(^|[^\\w-])(" + esc(t.term) + ")(?![\\w-])", acronym ? "" : "i");
      const m = re.exec(node.nodeValue);
      if (!m) continue;
      used.add(t.term);
      const start = m.index + m[1].length, after = node.splitText(start);
      after.splitText(m[2].length);
      const span = document.createElement("span");
      span.className = "gloss"; span.tabIndex = 0; span.textContent = after.nodeValue;
      span.dataset.term = t.term;
      span.title = (t.expansion ? t.expansion + ": " : "") + t.definition;
      after.parentNode.replaceChild(span, after);
      return true;                          // the node changed: re-walk
    }
    return false;
  }
  if (terms.length) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => {
        for (let p = n.parentNode; p && p !== root; p = p.parentNode)
          if (SKIP.has(p.nodeName) || (p.classList && p.classList.contains("gloss"))) return NodeFilter.FILTER_REJECT;
        return n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }});
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const n of nodes) { let cur = n; while (cur && mark(cur)) cur = cur.nextSibling && cur.nextSibling.nextSibling; }
  }

  // ---------- the bubble
  const bubble = document.createElement("div");
  bubble.className = "gloss-bubble"; bubble.hidden = true; bubble.setAttribute("role", "dialog");
  document.body.appendChild(bubble);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };
  function place(rect) {
    bubble.style.left = Math.max(8, Math.min(window.scrollX + rect.left, window.scrollX + document.documentElement.clientWidth - 340)) + "px";
    bubble.style.top = (window.scrollY + rect.bottom + 8) + "px";
  }
  function close() { bubble.hidden = true; bubble.replaceChildren(); }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  document.addEventListener("mousedown", (e) => { if (!bubble.contains(e.target)) close(); });

  async function post(path, data) {
    const body = new URLSearchParams(data);
    const r = await fetch(base + path, {method: "POST", body, credentials: "same-origin"});
    return r.json();
  }
  function show(term, info, context, rect, asked) {
    bubble.replaceChildren();
    const head = el("div", "gloss-head"); head.append(el("b", "", info.term || term));
    if (info.expansion) head.append(el("span", "muted", " — " + info.expansion));
    bubble.append(head);
    if (info.error) bubble.append(el("p", "error", info.error));
    if (info.found) {
      bubble.append(el("p", "", info.definition));
      if (info.more) bubble.append(el("p", "small", info.more));
      if (!info.reviewed) bubble.append(el("p", "small muted", "AI-generated, not yet reviewed."));
      else if (info.more_ai) bubble.append(el("p", "small muted", "Definition reviewed; the explanation is AI-generated."));
    } else if (info.not_a_term) {
      bubble.append(el("p", "small muted", "That doesn't look like a term to define."));
    } else if (!info.error) {
      bubble.append(el("p", "small muted", "Not in the glossary yet."));
    }
    const row = el("div", "gloss-actions");
    if (signedIn && !asked && !(info.found && info.more) && !info.not_a_term) {
      const b = el("button", "btn small", "Find out more");
      b.onclick = async () => { b.disabled = true; b.textContent = "Thinking…";
        const r = await post("/api/glossary/explain", {term, course, context});
        show(term, r, context, rect, true); };
      row.append(b);
    }
    if (signedIn && !info.reviewed && !info.not_a_term) {
      const a = el("button", "btn small ghost", "Add to glossary");
      a.onclick = async () => { a.disabled = true; const r = await post("/api/glossary/add", {term, course});
        a.textContent = r.message || r.error || "Sent"; };
      row.append(a);
    }
    if (!info.reviewed && !info.not_a_term) {
      const s = el("a", "small", "Suggest as a course");
      s.href = base + "/suggest?topic=" + encodeURIComponent(info.term || term);
      row.append(s);
    }
    if (!signedIn) { const s = el("a", "small", "Sign in to ask or add terms"); s.href = base + "/signin"; row.append(s); }
    bubble.append(row);
    bubble.hidden = false; place(rect);
  }
  async function lookUp(term, context, rect) {
    const r = await fetch(base + "/api/glossary/lookup?term=" + encodeURIComponent(term), {credentials: "same-origin"});
    show(term, await r.json(), context, rect);
  }

  root.addEventListener("click", (e) => {
    const g = e.target.closest && e.target.closest(".gloss");
    if (g) lookUp(g.dataset.term, g.parentNode.textContent, g.getBoundingClientRect());
  });
  root.addEventListener("keydown", (e) => {
    const g = e.target.closest && e.target.closest(".gloss");
    if (g && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); lookUp(g.dataset.term, g.parentNode.textContent, g.getBoundingClientRect()); }
  });
  root.addEventListener("mouseup", () => {
    setTimeout(() => {
      const sel = window.getSelection(), text = sel ? sel.toString().trim() : "";
      if (!text || text.length < 2 || text.length > 60 || text.split(/\s+/).length > 5 || /\n/.test(text)) return;
      if (!root.contains(sel.anchorNode)) return;
      const rect = sel.getRangeAt(0).getBoundingClientRect();
      const ctx = (sel.anchorNode.parentNode && sel.anchorNode.parentNode.textContent) || "";
      lookUp(text, ctx.slice(0, 600), rect);
    }, 0);
  });
})();
