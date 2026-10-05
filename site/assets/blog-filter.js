// Blog index: filter the post list by topic (chips), type, audience and date. The list itself is rendered at build time
// (scripts/mkdocs_hooks.py → <!-- posts:all -->), so without JavaScript every post is still listed.
// Material loads pages instantly (XHR), so this re-runs on each page change via document$ when available.
(function () {
  function setup() {
    var box = document.querySelector("[data-posts-filter]");
    if (!box || box.dataset.ready) return;
    box.dataset.ready = "1";

    // On wide screens the filters live in the left side panel; on phones they stay above the list.
    var home = document.createElement("div");
    home.className = "post-filter-home";
    box.parentNode.insertBefore(home, box);
    var side = document.querySelector(".md-sidebar--primary .md-sidebar__inner");
    var wide = window.matchMedia("(min-width: 76.25em)");
    function place() {
      if (wide.matches && side) { side.appendChild(box); box.classList.add("post-filter--side"); }
      else { home.parentNode.insertBefore(box, home); box.classList.remove("post-filter--side"); }
    }
    place();
    if (wide.addEventListener) wide.addEventListener("change", place); else if (wide.addListener) wide.addListener(place);
    var cards = Array.prototype.slice.call(document.querySelectorAll(".post-card"));
    var chips = Array.prototype.slice.call(box.querySelectorAll(".post-chip"));
    var section = box.querySelector("[data-section-select]");
    var when = box.querySelector("[data-when-select]");
    var audience = box.querySelector("[data-audience-select]");
    var count = box.querySelector("[data-count]");
    var empty = document.querySelector("[data-empty]");
    var state = { topic: "", section: "", audience: "", when: "" };

    // the newest post is "today" for the relative ranges, so they stay meaningful on a quiet blog
    var newest = cards.reduce(function (m, c) { return c.dataset.date > m ? c.dataset.date : m; }, "");
    var ref = new Date(Math.max(Date.now(), Date.parse(newest || 0)));

    function matches(c) {
      if (state.topic && c.dataset.topics.split("|").indexOf(state.topic) < 0) return false;
      if (state.section && c.dataset.section !== state.section) return false;
      if (state.audience && (c.dataset.audience || "").split("|").indexOf(state.audience) < 0) return false;
      if (state.when) {
        if (/^\d{4}-\d{2}$/.test(state.when)) { if (c.dataset.date.slice(0, 7) !== state.when) return false; }
        else if ((ref - Date.parse(c.dataset.date)) / 864e5 > Number(state.when)) return false;
      }
      return true;
    }
    function apply() {
      var shown = 0;
      cards.forEach(function (c) { var ok = matches(c); c.hidden = !ok; if (ok) shown++; });
      chips.forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.topic === state.topic)); });
      count.textContent = shown + " of " + cards.length + " posts";
      if (empty) empty.hidden = shown > 0;
      var q = new URLSearchParams();
      if (state.topic) q.set("topic", state.topic);
      if (state.section) q.set("type", state.section);
      if (state.audience) q.set("audience", state.audience);
      if (state.when) q.set("when", state.when);
      var s = q.toString();
      history.replaceState(null, "", location.pathname + (s ? "?" + s : "") + location.hash);
    }
    chips.forEach(function (b) {
      b.addEventListener("click", function () { state.topic = b.dataset.topic === state.topic ? "" : b.dataset.topic; apply(); });
    });
    section.addEventListener("change", function () { state.section = section.value; apply(); });
    when.addEventListener("change", function () { state.when = when.value; apply(); });
    if (audience) audience.addEventListener("change", function () { state.audience = audience.value; apply(); });

    // deep links: ?topic=Agents&type=Class&audience=Hiring%20managers&when=90
    var p = new URLSearchParams(location.search);
    state.topic = p.get("topic") || "";
    state.section = section.value = p.get("type") || "";
    state.when = when.value = p.get("when") || "";
    if (section.value !== state.section) state.section = "";
    if (when.value !== state.when) state.when = "";
    if (audience) { audience.value = p.get("audience") || ""; state.audience = audience.value; }
    apply();
  }
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(setup);
  else if (document.readyState !== "loading") setup();
  else document.addEventListener("DOMContentLoaded", setup);
})();
