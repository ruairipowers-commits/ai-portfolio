/* Site assistant widget: an "Ask" button in the blog header opening a panel to search the site, ask a question
   (answered by a local model, citing the pages it used) or match a role (a cited fit read to download).

   - Search and Ask are separate buttons, logged separately: a search is a search, an ask is an ask.
   - The panel can be expanded: on wide screens it docks beside the page, so a visitor can click a citation, read
     that page and click the next one without losing the answer. History and the panel's state are kept in this
     browser (localStorage, 3 days, "Clear" removes them), so they survive moving between pages.
   - Any element with data-sa-inline (the 3-minute tour) gets an inline search / ask / role-match box.
   Also records page views and the blog's own searches (no cookies; the server keeps a daily-rotating anonymous
   visitor key, never the IP).
   Load with: <script src="https://…/site-assistant/widget.js" data-endpoint="https://…/site-assistant" defer></script> */
(function () {
  "use strict";
  var me = document.currentScript;
  var API = ((me && (me.dataset.endpoint || (me.src || "").replace(/\/widget\.js(\?.*)?$/, ""))) || "").replace(/\/$/, "");
  if (!API || window.__siteAssistant) return;
  window.__siteAssistant = true;

  var css = document.createElement("link");
  // the stylesheet sits next to this script (the blog ships both, so the button shows even if the service is down)
  css.rel = "stylesheet"; css.href = ((me && me.src) || API + "/widget.js").replace(/widget\.js(\?.*)?$/, "widget.css");
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

  // the blog's built-in search box: record what people looked for (after they pause typing; the daily email keeps
  // only the last of a run of growing queries, so "gover" → "governance console" counts once)
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

  // ---------------------------------------------------------------- state that follows the visitor between pages
  var KEY = "sa-history-v2", TTL = 3 * 864e5, MAX_TURNS = 30;
  var state = load();
  function load() {
    try {
      var s = JSON.parse(localStorage.getItem(KEY) || "null");
      if (s && Date.now() - (s.saved || 0) < TTL && Array.isArray(s.turns)) return s;
    } catch (e) { /* private mode, blocked storage: start fresh */ }
    return { turns: [], view: "closed", wide: false };
  }
  var saveTimer = null;
  function save(now) {
    clearTimeout(saveTimer);
    var go = function () {
      try { state.saved = Date.now(); state.turns = state.turns.slice(-MAX_TURNS); localStorage.setItem(KEY, JSON.stringify(state)); }
      catch (e) { /* storage full or blocked: history just won't survive navigation */ }
    };
    if (now) go(); else saveTimer = setTimeout(go, 400);
  }
  window.addEventListener("pagehide", function () { save(true); });

  // ---------------------------------------------------------------- helpers
  var SUGGEST = ["Would Ruairi be a good fit for a head of AI role at an investment firm?",
                 "What has he built with agents, and how does he keep a human in control?",
                 "Which projects use RAG, and how do they avoid hallucinations?",
                 "How does he govern and evaluate AI before it ships?"];
  function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 7); }
  function samePage(url) {
    try { var u = new URL(url, location.href); return u.pathname.replace(/\/index\.html$/, "/") === location.pathname.replace(/\/index\.html$/, "/"); }
    catch (e) { return false; }
  }
  function wideScreen() { return window.matchMedia("(min-width: 1000px)").matches; }

  // Model text → HTML: escaped first; then bold, quotes, bullet lists and citation links built from the server's
  // own source list (no HTML from the model ever reaches the page).
  function md(text, sources) {
    function inline(s) {
      s = s.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
      return s.replace(/\[(\d{1,2})\]/g, function (m, n) {
        var src = sources[+n - 1];
        return src ? '<a class="sa-cite' + (samePage(src.url) ? " sa-here" : "") + '" href="' + esc(src.url) + '" title="' +
          esc(src.title + (src.section ? " — " + src.section : "")) + '">' + n + "</a>" : m;
      });
    }
    return esc(text).split(/\n{2,}/).map(function (block) {
      var lines = block.split("\n").filter(function (l) { return l.trim(); });
      if (!lines.length) return "";
      if (lines.every(function (l) { return /^\s*[-*•] /.test(l); }))
        return "<ul>" + lines.map(function (l) { return "<li>" + inline(l.replace(/^\s*[-*•] /, "")) + "</li>"; }).join("") + "</ul>";
      return "<p>" + lines.map(function (l) {
        var q = /^&gt; ?(.*)$/.exec(l);
        if (q) return '<span class="sa-quote">' + inline(q[1]) + "</span>";
        var item = /^\s*[-*•] (.*)$/.exec(l);
        return item ? "• " + inline(item[1]) : inline(l);
      }).join("<br>") + "</p>";
    }).join("");
  }

  // ---------------------------------------------------------------- the header button and the panel
  var btn = el("button", "sa-open", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3C6.5 3 2 6.6 2 11c0 2.4 1.3 4.5 3.4 6L4.5 21l4.3-2.3c1 .2 2.1.3 3.2.3 5.5 0 10-3.6 10-8s-4.5-8-10-8m-4 9.3a1.3 1.3 0 1 1 0-2.6 1.3 1.3 0 0 1 0 2.6m4 0a1.3 1.3 0 1 1 0-2.6 1.3 1.3 0 0 1 0 2.6m4 0a1.3 1.3 0 1 1 0-2.6 1.3 1.3 0 0 1 0 2.6"/></svg><span>Ask</span><i class="sa-count" hidden></i>');
  btn.type = "button"; btn.title = "Search the site, ask a question or match a role"; btn.setAttribute("aria-haspopup", "dialog");
  var slot = document.querySelector(".md-header__inner .md-search") || document.querySelector(".md-header__inner");
  if (slot && slot.parentNode && slot.classList.contains("md-search")) slot.parentNode.insertBefore(btn, slot);
  else if (slot) slot.appendChild(btn);
  else { btn.classList.add("sa-floating"); document.body.appendChild(btn); }

  var panel = el("div", "sa-panel");
  panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Ask the portfolio"); panel.hidden = true;
  panel.innerHTML =
    '<div class="sa-head"><div class="sa-title"><b>Ask the portfolio</b><span class="sa-sub">Answers come from this site, with links to the pages used. Your history stays here as you move between pages.</span></div>' +
    '<div class="sa-tools"><button type="button" class="sa-tool sa-wide" title="Expand: keep the answers beside the page"></button>' +
    '<button type="button" class="sa-tool sa-clear" title="Clear your history">Clear</button>' +
    '<button type="button" class="sa-tool sa-close" aria-label="Close" title="Close">×</button></div></div>' +
    '<div class="sa-body"><div class="sa-intro"><p>Try a question:</p><div class="sa-chips"></div>' +
    '<p class="sa-intro-role">Hiring? <button type="button" class="sa-linkbtn sa-role-toggle">Match me to a role</button>: paste a job description and get a cited fit read to download.</p></div>' +
    '<div class="sa-log" aria-live="polite"></div></div>' +
    '<form class="sa-role" hidden></form>' +
    '<form class="sa-form"><input class="sa-input" type="text" maxlength="500" placeholder="Search the site, or ask a question…" aria-label="Search the site, or ask a question" autocomplete="off">' +
    '<button class="sa-go sa-go--search" type="submit" value="search" title="List the pages that match">Search</button>' +
    '<button class="sa-go" type="submit" value="ask" title="Get an answer with citations">Ask</button></form>' +
    '<div class="sa-foot"><button type="button" class="sa-linkbtn sa-role-toggle">Match a role</button> · Runs on a local open model. Searches, questions and role matches are logged (text only, no IP) so Ruairi can see what people look for.</div>';
  document.body.appendChild(panel);
  var log = panel.querySelector(".sa-log"), input = panel.querySelector(".sa-input"), form = panel.querySelector(".sa-form");
  var roleForm = panel.querySelector(".sa-role"), wideBtn = panel.querySelector(".sa-wide"), clearBtn = panel.querySelector(".sa-clear");
  SUGGEST.forEach(function (s) {
    var c = el("button", "sa-chip", esc(s)); c.type = "button";
    c.onclick = function () { run("ask", s); };
    panel.querySelector(".sa-chips").appendChild(c);
  });

  var pill = el("button", "sa-pill", "");
  pill.type = "button"; pill.hidden = true;
  pill.onclick = function () { open(); };
  document.body.appendChild(pill);

  // Views: closed, or open. Open + wide = expanded. On wide screens the panel docks beside the page (the page
  // narrows, nothing is covered); on smaller screens it overlays, full-screen when expanded.
  function layout() {
    var isOpen = state.view === "open";
    panel.hidden = !isOpen;
    panel.classList.toggle("sa-panel--wide", !!state.wide);
    var dock = isOpen && wideScreen();
    document.documentElement.classList.toggle("sa-docked", dock);
    document.documentElement.classList.toggle("sa-docked--wide", dock && !!state.wide);
    btn.setAttribute("aria-expanded", String(isOpen));
    wideBtn.innerHTML = state.wide ? "⤡ Narrow" : "⤢ Expand";
    wideBtn.title = state.wide ? "Make the panel narrower" : "Expand: keep the answers beside the page as you click through";
    var n = state.turns.length, count = btn.querySelector(".sa-count");
    count.hidden = !n; count.textContent = n;
    pill.hidden = isOpen || !n || !state.pill;
    pill.textContent = "← Back to your answers (" + n + ")";
    panel.querySelector(".sa-intro").hidden = n > 0 && roleForm.hidden;
  }
  function open(wide) {
    state.view = "open"; state.pill = false;
    if (wide != null) state.wide = wide;
    layout(); save();
    setTimeout(function () { (roleForm.hidden ? input : roleForm.querySelector("input")).focus(); scrollEnd(); }, 30);
  }
  function close() { state.view = "closed"; state.pill = false; layout(); save(); btn.focus(); }
  function scrollEnd() { var b = panel.querySelector(".sa-body"); b.scrollTop = b.scrollHeight; }
  btn.onclick = function () { state.view === "open" ? close() : open(); };
  panel.querySelector(".sa-close").onclick = close;
  wideBtn.onclick = function () { state.wide = !state.wide; layout(); save(); };
  var clearArmed = null;
  clearBtn.onclick = function () {
    if (!clearArmed) { clearBtn.textContent = "Sure?"; clearArmed = setTimeout(function () { clearArmed = null; clearBtn.textContent = "Clear"; }, 3000); return; }
    clearTimeout(clearArmed); clearArmed = null; clearBtn.textContent = "Clear";
    state.turns = []; log.innerHTML = ""; layout(); save(true);
  };
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && state.view === "open") close(); });
  window.addEventListener("resize", layout);

  // Following a link from the panel: the history comes along. On a phone the panel would cover the page you
  // asked for, so it closes there and a "Back to your answers" button brings it back.
  panel.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || a.target === "_blank") return;
    if (!wideScreen()) { state.view = "closed"; state.pill = true; }
    save(true);
  });

  var submitter = "ask";
  form.addEventListener("click", function (e) { if (e.target.value) submitter = e.target.value; });
  form.onsubmit = function (e) {
    e.preventDefault();
    var mode = (e.submitter && e.submitter.value) || submitter || "ask";
    submitter = "ask";
    var q = input.value.trim();
    if (q.length >= 2) { input.value = ""; run(mode, q); }
  };

  // ---------------------------------------------------------------- role match form (in the panel and inline)
  function roleFields(prefix) {
    return '<label class="sa-field"><span>Role title</span><input name="role" required minlength="2" maxlength="120" placeholder="e.g. Head of AI solutions"></label>' +
      '<label class="sa-field"><span>Job description or what you\'re looking for</span><textarea name="description" required minlength="40" maxlength="8000" rows="7" placeholder="Paste the job description, or list the requirements."></textarea></label>' +
      '<label class="sa-field"><span>How Ruairi can reach you <i>(optional)</i></span><input name="contact" maxlength="160" placeholder="Email or LinkedIn" autocomplete="email"></label>' +
      '<input name="website" class="sa-hp" tabindex="-1" autocomplete="off" aria-hidden="true">' +
      '<p class="sa-note">You\'ll get a read of how the site\'s evidence matches the role, with citations, to download. A copy of the role you paste, the read and any contact you leave are saved and emailed to Ruairi; nothing else is collected.</p>' +
      '<div class="sa-role-actions"><button class="sa-go" type="submit">Get the fit read</button>' + (prefix === "panel" ? '<button type="button" class="sa-linkbtn sa-role-cancel">Cancel</button>' : "") + "</div>" +
      '<p class="sa-role-err" hidden></p>';
  }
  roleForm.innerHTML = '<div class="sa-label">Match a role</div>' + roleFields("panel");
  function toggleRole(show) {
    roleForm.hidden = !show; form.hidden = show;
    panel.querySelector(".sa-intro").hidden = !show && state.turns.length > 0;
    if (show) setTimeout(function () { roleForm.querySelector("input").focus(); }, 30);
  }
  Array.prototype.forEach.call(panel.querySelectorAll(".sa-role-toggle"), function (b) {
    b.onclick = function () { toggleRole(true); };
  });
  roleForm.querySelector(".sa-role-cancel").onclick = function () { toggleRole(false); };
  function roleSubmit(f, after) {
    f.onsubmit = function (e) {
      e.preventDefault();
      var v = function (n) { return (f.elements[n].value || "").trim(); };
      var err = f.querySelector(".sa-role-err");
      if (v("description").length < 40) { err.hidden = false; err.textContent = "Please paste a little more of the role (at least a few lines)."; return; }
      err.hidden = true;
      runRole({ role: v("role"), description: v("description"), contact: v("contact"), website: v("website") });
      f.reset();
      if (after) after();
    };
  }
  roleSubmit(roleForm, function () { toggleRole(false); });

  // ---------------------------------------------------------------- turns: run, render, restore
  function history() {
    var h = [];
    state.turns.forEach(function (t) {
      if (t.mode === "ask" && t.status === "done" && t.text) h.push({ role: "user", content: t.q }, { role: "assistant", content: t.text });
    });
    return h.slice(-4);
  }

  function linkList(label, items) {
    if (!items || !items.length) return "";
    return '<div class="sa-label">' + label + "</div>" + items.map(function (s) {
      var here = samePage(s.url);
      return '<a class="sa-srclink' + (here ? " sa-here" : "") + '" href="' + esc(s.url) + '">' + (s.n ? s.n + ". " : "") +
        esc(s.title) + (s.section ? " · " + esc(s.section) : "") + (here ? ' <em>(this page)</em>' : "") + "</a>";
    }).join("");
  }
  function hitList(label, hits) {
    if (!hits || !hits.length) return "";
    return '<div class="sa-label">' + label + "</div>" + hits.map(function (r) {
      var here = samePage(r.url);
      return '<a class="sa-hit' + (here ? " sa-here" : "") + '" href="' + esc(r.url) + '"><b>' + esc(r.title) + (r.section ? " · " + esc(r.section) : "") +
        (here ? ' <em>(this page)</em>' : "") + "</b><span>" + String(r.snippet || "").replace(/<(?!\/?mark>)[^>]*>/g, "") + "</span></a>";
    }).join("");
  }

  function render(t) {
    var node = log.querySelector('[data-turn="' + t.id + '"]');
    if (!node) { node = el("div", "sa-turn"); node.setAttribute("data-turn", t.id); log.appendChild(node); }
    var tag = { ask: "Ask", search: "Search", role: "Role match" }[t.mode];
    var h = '<div class="sa-q"><span class="sa-tag sa-tag--' + t.mode + '">' + tag + "</span>" + esc(t.mode === "role" ? t.role : t.q) + "</div>";
    var dots = '<span class="sa-dots"><i></i><i></i><i></i></span>';
    if (t.mode === "search") {
      h += t.status === "pending" ? dots : t.err ? '<p class="sa-err">' + esc(t.err) + "</p>" :
        (t.hits && t.hits.length ? hitList(t.hits.length + " page" + (t.hits.length > 1 ? "s" : "") + " match", t.hits) :
          '<p class="sa-muted">No pages match. Try other words, or ask it as a question.</p>');
    } else {
      h += '<div class="sa-a">' + (t.text ? md(t.text, t.sources || []) : (t.status === "pending" ? dots : "")) + "</div>";
      if (t.err) h += '<p class="sa-err">' + esc(t.err) + "</p>";
      if (t.status === "interrupted") h += '<p class="sa-muted">This answer was cut off when you left the page. <button type="button" class="sa-linkbtn sa-retry">Ask again</button></p>';
      if (t.status === "done" || t.mode === "role") {
        var used = (t.sources || []).filter(function (s) { return (t.text || "").indexOf("[" + s.n + "]") >= 0; });
        h += linkList("Sources", used);
      }
      if (t.mode === "ask") h += hitList("Pages that match", (t.hits || []).slice(0, 5));
      if (t.mode === "role" && t.status === "done" && t.text)
        h += '<div class="sa-dl"><button type="button" class="sa-go sa-dl-html">Download the read (.html)</button>' +
          '<button type="button" class="sa-linkbtn sa-dl-md">or Markdown (.md)</button></div>' +
          '<p class="sa-muted">A copy was saved for Ruairi' + (t.contact ? ", with your contact details, so he can get back to you." : ".") + "</p>";
    }
    node.innerHTML = h;
    var retry = node.querySelector(".sa-retry");
    if (retry) retry.onclick = function () { run("ask", t.q); };
    var dl = node.querySelector(".sa-dl-html");
    if (dl) { dl.onclick = function () { download(t, "html"); }; node.querySelector(".sa-dl-md").onclick = function () { download(t, "md"); }; }
    return node;
  }

  function newTurn(mode, q, extra) {
    var t = { id: uid(), mode: mode, q: q, text: "", sources: [], hits: [], status: "pending", ts: Date.now() };
    for (var k in extra || {}) t[k] = extra[k];
    state.turns.push(t);
    layout();
    var node = render(t);
    node.scrollIntoView({ block: "end" });
    save();
    return t;
  }

  function run(mode, q) {
    if (state.view !== "open") open();
    toggleRole(false);
    var t = newTurn(mode, q);
    // search: the pages that match (a search). ask: the same list beside the answer, but it isn't a second search.
    fetch(API + "/api/search?q=" + encodeURIComponent(q) + "&page=" + encodeURIComponent(location.pathname) + "&via=" + mode)
      .then(function (r) { return r.ok ? r.json() : r.json().then(function (d) { throw new Error(d.detail || ("HTTP " + r.status)); }); })
      .then(function (d) {
        t.hits = d.results || [];
        if (mode === "search") t.status = "done";
        render(t); save();
      }).catch(function (err) {
        if (mode === "search") { t.status = "error"; t.err = offline(err); render(t); save(); }
      });
    if (mode === "ask") stream(t, API + "/api/chat", { question: q, history: history(), page: location.pathname });
  }

  function runRole(body) {
    open(wideScreen() ? true : state.wide);
    var t = newTurn("role", body.role, { role: body.role, contact: !!body.contact });
    body.page = location.pathname;
    stream(t, API + "/api/rolematch", body);
  }

  function offline(err) {
    return (err && err.message && !/fetch|network|load failed/i.test(err.message)) ? err.message :
      "The assistant is offline right now. The search box at the top of the page still works.";
  }

  function stream(t, url, body) {
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (d) {
          var detail = d.detail;
          throw new Error(typeof detail === "string" ? detail : "Please check the form and try again.");
        });
        var reader = r.body.getReader(), dec = new TextDecoder(), buf = "";
        function pump() {
          return reader.read().then(function (x) {
            if (x.done) { if (t.status === "pending") { t.status = "done"; render(t); save(true); } return; }
            buf += dec.decode(x.value, { stream: true });
            var lines = buf.split("\n"); buf = lines.pop();
            lines.forEach(function (line) {
              if (!line.trim()) return;
              var m = JSON.parse(line);
              if (m.type === "sources") { t.sources = m.sources; if (m.id) { t.rid = m.id; t.key = m.key; } save(true); }
              else if (m.type === "delta") { t.text += m.text; render(t); save(); }
              else if (m.type === "done") { t.status = "done"; t.model = m.model; render(t); save(true); }
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function (err) { t.status = "error"; t.err = offline(err); render(t); save(true); });
  }

  // A turn still "pending" from the last page was cut off when the visitor navigated. A role read finishes on the
  // server anyway, so it's fetched back; an answer offers "Ask again".
  function restore() {
    state.turns.forEach(function (t) {
      if (t.status === "pending") {
        if (t.mode === "role" && t.rid && t.key) {
          fetch(API + "/api/rolematch/" + t.rid + "?key=" + encodeURIComponent(t.key)).then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
              if (d && d.read && d.status !== "started") { t.text = d.read; t.sources = d.sources; t.status = "done"; }
              else { t.status = "interrupted"; }
              render(t); save();
            }).catch(function () { t.status = "interrupted"; render(t); });
        } else if (t.mode === "search") { t.status = "error"; t.err = "Interrupted. Search again from the box below."; }
        else t.status = "interrupted";
      }
      render(t);
    });
    layout();
    if (state.view === "open") scrollEnd();
  }

  // ---------------------------------------------------------------- the fit read as a file to keep
  function download(t, kind) {
    var name = "Ruairi-Powers-fit-read-" + (t.role || "role").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 50);
    var when = new Date(t.ts || Date.now()).toISOString().slice(0, 10);
    var used = (t.sources || []).filter(function (s) { return t.text.indexOf("[" + s.n + "]") >= 0; });
    var about = ((t.sources || []).filter(function (s) { return /\/about\//.test(s.url); })[0] || {}).url;
    var site = about ? about.replace(/about\/.*$/, "") : location.origin + "/";
    var data, type;
    if (kind === "md") {
      data = "# Fit read: " + t.role + "\n\nGenerated " + when + " by the Ask assistant on " + site + " from Ruairi Powers' published work. " +
        "Every claim cites its source; please check them.\n\n" + t.text.replace(/\[(\d{1,2})\]/g, "[$1]") + "\n\n## Sources\n\n" +
        used.map(function (s) { return s.n + ". [" + s.title + (s.section ? " — " + s.section : "") + "](" + s.url + ")"; }).join("\n") + "\n";
      type = "text/markdown";
    } else {
      var body = md(t.text, t.sources || []).replace(/ class="sa-cite[^"]*"/g, ' class="cite"');
      data = "<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>" +
        "<title>Fit read: " + esc(t.role) + " — Ruairi Powers</title><style>body{font:15px/1.6 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;" +
        "color:#1f2933;max-width:760px;margin:2rem auto;padding:0 16px}h1{font-weight:600;font-size:1.5rem;margin:0 0 .3rem}.meta{color:#5f6b76;font-size:.85rem;margin:0 0 1.4rem}" +
        "a.cite{display:inline-block;min-width:1.1em;padding:0 .3em;border-radius:.6em;background:#546e7a;color:#fff;font-size:.72rem;text-decoration:none;text-align:center}" +
        ".sa-quote{display:block;border-left:3px solid #dde3e8;padding-left:8px;color:#5f6b76}ol{padding-left:1.3rem}li{margin:.2rem 0}" +
        "@media print{a{color:inherit}}</style></head><body><h1>Fit read: " + esc(t.role) + "</h1><p class=meta>Generated " + when +
        " by the Ask assistant on <a href='" + esc(site) + "'>" + esc(site) + "</a> from Ruairi Powers' published work. Every claim links to its source; please check them.</p>" +
        body + "<h2>Sources</h2><ol>" + used.map(function (s) {
          return "<li><a href='" + esc(s.url) + "'>" + esc(s.title + (s.section ? " — " + s.section : "")) + "</a></li>";
        }).join("") + "</ol></body></html>";
      type = "text/html";
    }
    var a = el("a"); a.href = URL.createObjectURL(new Blob([data], { type: type + ";charset=utf-8" }));
    a.download = name + "." + kind; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  // ---------------------------------------------------------------- inline box (the 3-minute tour)
  Array.prototype.forEach.call(document.querySelectorAll("[data-sa-inline]"), function (box) {
    box.classList.add("sa-inline");
    box.innerHTML =
      '<form class="sa-inline__form"><input class="sa-input" type="text" maxlength="500" placeholder="e.g. Has he built governed agents? Does he know financial data?" aria-label="Search the site, or ask a question" autocomplete="off">' +
      '<button class="sa-go sa-go--search" type="submit" value="search">Search</button><button class="sa-go" type="submit" value="ask">Ask</button></form>' +
      '<div class="sa-inline__chips"></div>' +
      '<details class="sa-inline__role"><summary><b>Match me to a role</b>: paste a job description and download a cited fit read</summary><form class="sa-inline__roleform">' + roleFields("inline") + "</form></details>";
    var f = box.querySelector(".sa-inline__form"), inp = f.querySelector("input"), which = "ask";
    f.addEventListener("click", function (e) { if (e.target.value) which = e.target.value; });
    f.onsubmit = function (e) {
      e.preventDefault();
      var mode = (e.submitter && e.submitter.value) || which || "ask"; which = "ask";
      var q = inp.value.trim();
      if (q.length >= 2) { inp.value = ""; open(wideScreen() ? true : state.wide); run(mode, q); }
    };
    SUGGEST.slice(0, 3).forEach(function (s) {
      var c = el("button", "sa-chip", esc(s)); c.type = "button";
      c.onclick = function () { open(wideScreen() ? true : state.wide); run("ask", s); };
      box.querySelector(".sa-inline__chips").appendChild(c);
    });
    roleSubmit(box.querySelector(".sa-inline__roleform"), function () { box.querySelector("details").open = false; });
  });

  // the tour or any page can open it directly: <a href="#ask"> or ?ask=1
  window.SiteAssistant = { open: open, ask: function (q) { run("ask", q); }, search: function (q) { run("search", q); } };
  if (location.hash === "#ask") open();
  restore();
})();
