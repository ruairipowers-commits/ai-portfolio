/* Site assistant widget: an "Ask" button in the blog header opening a panel that searches the blog and answers
   questions with a local model, citing the pages it used. Also records page views and the blog's own searches
   (no cookies; the server keeps a daily-rotating anonymous visitor key, never the IP).
   Load with: <script src="https://…/site-assistant/widget.js" data-endpoint="https://…/site-assistant" defer></script> */
(function () {
  "use strict";
  var me = document.currentScript;
  var API = ((me && (me.dataset.endpoint || (me.src || "").replace(/\/widget\.js(\?.*)?$/, ""))) || "").replace(/\/$/, "");
  if (!API || window.__siteAssistant) return;
  window.__siteAssistant = true;

  var css = document.createElement("link");
  css.rel = "stylesheet"; css.href = API + "/widget.css";
  document.head.appendChild(css);

  // ---------------------------------------------------------------- tracking
  function track(payload) {
    try {
      var body = JSON.stringify(payload);
      if (navigator.sendBeacon) navigator.sendBeacon(API + "/api/track", new Blob([body], { type: "text/plain" }));
      else fetch(API + "/api/track", { method: "POST", body: body, keepalive: true, headers: { "Content-Type": "text/plain" } });
    } catch (e) { /* never break the page */ }
  }
  track({ kind: "pageview", path: location.pathname, title: document.title, referrer: document.referrer });

  // the blog's built-in search box: record what people looked for (after they pause typing)
  var lastQ = "", qTimer = null;
  document.addEventListener("input", function (e) {
    var t = e.target;
    if (!t || !t.matches || !t.matches("input.md-search__input")) return;
    clearTimeout(qTimer);
    qTimer = setTimeout(function () {
      var q = (t.value || "").trim();
      if (q.length >= 3 && q !== lastQ) {
        lastQ = q;
        var n = document.querySelectorAll(".md-search-result__item").length;
        track({ kind: "site-search", path: location.pathname, q: q, results: n });
      }
    }, 1500);
  }, true);

  // ---------------------------------------------------------------- UI
  var SUGGEST = ["What does the governance console do?",
                 "Would Ruairi be a good fit for an AI product management role?",
                 "Which projects use RAG, and how do they avoid hallucinations?",
                 "How are the live demos kept safe for visitors?"];
  var history = [];

  function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  var btn = el("button", "sa-open", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3C6.5 3 2 6.6 2 11c0 2.4 1.3 4.5 3.4 6L4.5 21l4.3-2.3c1 .2 2.1.3 3.2.3 5.5 0 10-3.6 10-8s-4.5-8-10-8m-4 9.3a1.3 1.3 0 1 1 0-2.6 1.3 1.3 0 0 1 0 2.6m4 0a1.3 1.3 0 1 1 0-2.6 1.3 1.3 0 0 1 0 2.6m4 0a1.3 1.3 0 1 1 0-2.6 1.3 1.3 0 0 1 0 2.6"/></svg><span>Ask</span>');
  btn.type = "button"; btn.title = "Search the blog or ask a question"; btn.setAttribute("aria-haspopup", "dialog");
  var slot = document.querySelector(".md-header__inner .md-search") || document.querySelector(".md-header__inner");
  if (slot && slot.parentNode && slot.classList.contains("md-search")) slot.parentNode.insertBefore(btn, slot);
  else if (slot) slot.appendChild(btn);
  else { btn.classList.add("sa-floating"); document.body.appendChild(btn); }

  var panel = el("div", "sa-panel");
  panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Ask the portfolio"); panel.hidden = true;
  panel.innerHTML =
    '<div class="sa-head"><b>Ask the portfolio</b><span class="sa-sub">Answers come from this blog, with links to the pages used.</span>' +
    '<button type="button" class="sa-close" aria-label="Close">×</button></div>' +
    '<div class="sa-body"><div class="sa-intro"><p>Try:</p><div class="sa-chips"></div></div><div class="sa-log" aria-live="polite"></div></div>' +
    '<form class="sa-form"><input class="sa-input" type="text" maxlength="500" placeholder="Search or ask a question…" aria-label="Search or ask a question" autocomplete="off">' +
    '<button class="sa-go" type="submit">Ask</button></form>' +
    '<div class="sa-foot">Runs on a local open model. Searches and questions are logged (text only, no IP) to improve the blog.</div>';
  document.body.appendChild(panel);
  var log = panel.querySelector(".sa-log"), input = panel.querySelector(".sa-input"), form = panel.querySelector(".sa-form");
  var chips = panel.querySelector(".sa-chips");
  SUGGEST.forEach(function (s) {
    var c = el("button", "sa-chip", esc(s)); c.type = "button";
    c.onclick = function () { input.value = s; ask(s); };
    chips.appendChild(c);
  });

  function open() { panel.hidden = false; btn.setAttribute("aria-expanded", "true"); setTimeout(function () { input.focus(); }, 30); }
  function close() { panel.hidden = true; btn.setAttribute("aria-expanded", "false"); btn.focus(); }
  btn.onclick = function () { panel.hidden ? open() : close(); };
  panel.querySelector(".sa-close").onclick = close;
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !panel.hidden) close(); });

  form.onsubmit = function (e) { e.preventDefault(); var q = input.value.trim(); if (q.length >= 2) ask(q); };

  function md(text, sources) {
    var h = esc(text);
    h = h.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
    h = h.replace(/^&gt; ?(.*)$/gm, "<span class=\"sa-quote\">$1</span>");
    h = h.replace(/\[(\d{1,2})\]/g, function (m, n) {
      var s = sources[+n - 1];
      return s ? '<a class="sa-cite" href="' + esc(s.url) + '" title="' + esc(s.title + (s.section ? " — " + s.section : "")) + '">' + n + "</a>" : m;
    });
    return h.split(/\n{2,}/).map(function (p) { return "<p>" + p.replace(/\n/g, "<br>") + "</p>"; }).join("");
  }

  function ask(q) {
    panel.querySelector(".sa-intro").hidden = true;
    input.value = "";
    var turn = el("div", "sa-turn");
    turn.appendChild(el("div", "sa-q", esc(q)));
    var a = el("div", "sa-a", '<span class="sa-dots"><i></i><i></i><i></i></span>');
    var src = el("div", "sa-src");
    var hits = el("div", "sa-hits");
    turn.appendChild(a); turn.appendChild(src); turn.appendChild(hits);
    log.appendChild(turn);
    turn.scrollIntoView({ block: "end" });

    // matching pages, straight away
    fetch(API + "/api/search?q=" + encodeURIComponent(q) + "&page=" + encodeURIComponent(location.pathname))
      .then(function (r) { return r.ok ? r.json() : { results: [] }; })
      .then(function (d) {
        if (!d.results || !d.results.length) return;
        hits.innerHTML = '<div class="sa-label">Pages that match</div>' + d.results.slice(0, 5).map(function (r) {
          return '<a class="sa-hit" href="' + esc(r.url) + '"><b>' + esc(r.title) + (r.section ? " · " + esc(r.section) : "") +
                 "</b><span>" + r.snippet.replace(/<(?!\/?mark>)[^>]*>/g, "") + "</span></a>";
        }).join("");
      }).catch(function () {});

    // the answer, streamed
    var sources = [], text = "";
    fetch(API + "/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, history: history.slice(-4), page: location.pathname }) })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || ("HTTP " + r.status)); });
        var reader = r.body.getReader(), dec = new TextDecoder(), buf = "";
        function pump() {
          return reader.read().then(function (x) {
            if (x.done) return;
            buf += dec.decode(x.value, { stream: true });
            var lines = buf.split("\n"); buf = lines.pop();
            lines.forEach(function (line) {
              if (!line.trim()) return;
              var m = JSON.parse(line);
              if (m.type === "sources") sources = m.sources;
              else if (m.type === "delta") { text += m.text; a.innerHTML = md(text, sources); }
              else if (m.type === "done") {
                var used = sources.filter(function (s) { return text.indexOf("[" + s.n + "]") >= 0; });
                if (used.length) src.innerHTML = '<div class="sa-label">Sources</div>' + used.map(function (s) {
                  return '<a href="' + esc(s.url) + '">' + s.n + ". " + esc(s.title) + (s.section ? " · " + esc(s.section) : "") + "</a>";
                }).join("");
                history.push({ role: "user", content: q }, { role: "assistant", content: text });
              }
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function (err) { a.innerHTML = '<p class="sa-err">' + esc(err.message || "Something went wrong.") + "</p>"; });
  }
})();
