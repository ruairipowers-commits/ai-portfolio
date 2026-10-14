// Blog → Upcoming topics: the editorial queue, live, in the order the daily writer will take it (the owner's picks,
// then readers' votes, then rank). One vote per topic per day; the editorial service's URL comes from the box's
// data-editorial attribute (empty in a local preview without the demos).
(function () {
  function esc(s) { return String(s || "").replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function today() { return new Date().toISOString().slice(0, 10); }
  function voted(id) { try { return JSON.parse(localStorage.getItem("up-votes") || "{}")[id] === today(); } catch (e) { return false; } }
  function remember(id) { try { var v = JSON.parse(localStorage.getItem("up-votes") || "{}"); v[id] = today(); localStorage.setItem("up-votes", JSON.stringify(v)); } catch (e) {} }
  function host(u) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } }

  function render(box, base) {
    var list = box.querySelector("[data-upcoming-list]");
    var max = parseInt(box.dataset.max || "6", 10);
    fetch(base + "/api/queue").then(function (r) { return r.json(); }).then(function (rows) {
      rows = (rows || []).slice(0, max);
      if (!rows.length) { list.innerHTML = '<p class="ideas__empty">The queue refills every morning. Check back soon.</p>'; return; }
      list.innerHTML = rows.map(function (t, i) {
        var on = voted(t.id);
        var tag = i === 0 ? '<span class="idea__new">Next up</span>' : (t.status === "picked" ? '<span class="idea__new">Picked</span>' : "");
        return '<div class="idea"><button type="button" class="idea__vote' + (on ? " is-on" : "") + '" data-vote="' + esc(t.id) + '"' +
          (on ? " disabled" : "") + ' aria-label="Vote for this topic"><span class="idea__arrow">▲</span><span class="idea__n">' + (t.votes || 0) +
          '</span></button><div class="idea__body">' + tag + '<a href="' + esc(t.url) + '" rel="noopener" target="_blank">' + esc(t.title) + "</a>" +
          (t.summary ? '<div class="upcoming__sum">' + esc(t.summary) + "</div>" : "") +
          '<div class="idea__meta">' + esc((t.sectors || []).slice(0, 3).join(" · ")) + (t.sectors && t.sectors.length ? " · " : "") + esc(host(t.url)) + "</div></div></div>";
      }).join("");
      list.querySelectorAll("[data-vote]").forEach(function (b) {
        b.addEventListener("click", function () {
          b.disabled = true;
          fetch(base + "/api/queue/" + encodeURIComponent(b.dataset.vote) + "/vote", { method: "POST" })
            .then(function (r) { return r.json(); })
            .then(function (d) { if (d && d.votes != null) { b.querySelector(".idea__n").textContent = d.votes; b.classList.add("is-on"); remember(b.dataset.vote); } else { b.disabled = false; } })
            .catch(function () { b.disabled = false; });
        });
      });
    }).catch(function () { list.innerHTML = '<p class="ideas__empty">Upcoming topics are offline right now. Please try again later.</p>'; });
  }

  function setup() {
    var box = document.querySelector("[data-upcoming]");
    if (!box || box.dataset.ready) return;
    box.dataset.ready = "1";
    var base = (box.dataset.editorial || "").replace(/\/$/, "");
    if (base) render(box, base);
    else box.querySelector("[data-upcoming-list]").innerHTML = '<p class="ideas__empty">Upcoming topics are offline in this preview.</p>';
  }
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(setup);
  else document.addEventListener("DOMContentLoaded", setup);
})();
