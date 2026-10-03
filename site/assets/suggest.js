// Projects → Suggest a project: send an idea and upvote others. Talks to the site assistant service (the same one
// behind the Ask button; its URL comes from the widget's script tag). New ideas wait for the owner's approval.
(function () {
  function api() { var t = document.querySelector("script[data-endpoint]"); return t ? t.getAttribute("data-endpoint") : ""; }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function voted(id) { try { return JSON.parse(localStorage.getItem("sg-votes") || "{}")[id]; } catch (e) { return false; } }
  function remember(id) { try { var v = JSON.parse(localStorage.getItem("sg-votes") || "{}"); v[id] = 1; localStorage.setItem("sg-votes", JSON.stringify(v)); } catch (e) {} }

  function renderList(box, base) {
    fetch(base + "/api/suggestions").then(function (r) { return r.json(); }).then(function (d) {
      var items = (d && d.suggestions) || [];
      if (!items.length) { box.innerHTML = '<p class="ideas__empty">No ideas yet. Be the first!</p>'; return; }
      box.innerHTML = items.map(function (s) {
        var on = voted(s.id);
        return '<div class="idea"><button type="button" class="idea__vote' + (on ? " is-on" : "") + '" data-vote="' + s.id + '"' +
          (on ? " disabled" : "") + ' aria-label="Upvote"><span class="idea__arrow">▲</span><span class="idea__n">' + s.votes +
          '</span></button><div class="idea__body">' + (s.new ? '<span class="idea__new">New</span>' : "") +
          esc(s.idea) + '<div class="idea__meta">Suggested ' + esc(s.day) + "</div></div></div>";
      }).join("");
      box.querySelectorAll("[data-vote]").forEach(function (b) {
        b.addEventListener("click", function () {
          b.disabled = true;
          fetch(base + "/api/suggestions/" + b.dataset.vote + "/vote", { method: "POST" })
            .then(function (r) { return r.json(); })
            .then(function (d) { if (d && d.votes != null) { b.querySelector(".idea__n").textContent = d.votes; b.classList.add("is-on"); remember(b.dataset.vote); } })
            .catch(function () { b.disabled = false; });
        });
      });
    }).catch(function () { box.innerHTML = '<p class="ideas__empty">Suggestions are offline right now. Please try again later.</p>'; });
  }

  function setup() {
    var base = api();
    var box = document.querySelector("[data-suggestions]");
    if (box && !box.dataset.ready) {
      box.dataset.ready = "1";
      if (base) renderList(box, base); else box.innerHTML = '<p class="ideas__empty">Suggestions are offline in this preview.</p>';
    }
    var form = document.querySelector("[data-suggest]");
    if (!form || form.dataset.ready) return;
    form.dataset.ready = "1";
    var status = form.querySelector("[data-status]");
    if (!base) {
      status.textContent = "The suggestion box is offline in this preview. Please reach me on LinkedIn instead.";
      form.querySelector("button").disabled = true;
      return;
    }
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var f = new FormData(form), btn = form.querySelector("button");
      btn.disabled = true;
      status.textContent = "Sending…";
      fetch(base + "/api/suggest", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idea: f.get("idea"), name: f.get("name"), contact: f.get("contact"),
                               website: f.get("website"), page: location.href })
      }).then(function (r) {
        return r.json().then(function (d) {
          if (r.ok) {
            form.reset();
            status.textContent = d.status === "published" ? "Thank you! Your idea is on the list below." :
              "Thank you! Your idea will appear here once I've reviewed it.";
            if (box && d.status === "published") renderList(box, base);
            return;
          }
          var msg = d && d.detail;
          status.textContent = typeof msg === "string" ? msg : "Please write at least a sentence about your idea.";
        });
      }).catch(function () {
        status.textContent = "The suggestion box is offline right now. Please try again later, or reach me on LinkedIn.";
      }).then(function () { btn.disabled = false; });
    });
  }
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(setup);
  else if (document.readyState !== "loading") setup();
  else document.addEventListener("DOMContentLoaded", setup);
})();
