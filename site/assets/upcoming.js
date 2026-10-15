// Blog → Upcoming topics: the editorial queue, live, in the order the daily writer will take it (the owner's picks,
// then readers' votes, then rank), as a one-at-a-time carousel in the right-hand panel (home-side.js moves it there).
// One vote per topic per day. The editorial service's URL comes from the box's data-editorial attribute (empty in a
// local preview without the demos). Cards are filled in from the API, then handed to carousel.js.
(function () {
  function esc(s) { return String(s || "").replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function today() { return new Date().toISOString().slice(0, 10); }
  function voted(id) { try { return JSON.parse(localStorage.getItem("up-votes") || "{}")[id] === today(); } catch (e) { return false; } }
  function remember(id) { try { var v = JSON.parse(localStorage.getItem("up-votes") || "{}"); v[id] = today(); localStorage.setItem("up-votes", JSON.stringify(v)); } catch (e) {} }
  function host(u) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } }
  function plural(n) { return n === 1 ? "1 vote" : n + " votes"; }

  function card(t, i) {
    var on = voted(t.id), n = t.votes || 0;
    var badge = i === 0 ? "Next up" : (t.status === "picked" ? "Picked" : "#" + (i + 1));
    return '<article class="topic-slide">' +
      '<p class="topic-slide__meta"><span class="topic-slide__badge' + (i === 0 ? " is-next" : "") + '">' + badge + "</span> " +
      esc((t.sectors || []).slice(0, 2).join(" · ")) + "</p>" +
      '<h3 class="topic-slide__title"><a href="' + esc(t.url) + '" rel="noopener" target="_blank">' + esc(t.title) + "</a></h3>" +
      '<p class="topic-slide__sum">' + esc(t.summary) + "</p>" +
      '<div class="topic-slide__foot"><button type="button" class="topic-slide__vote' + (on ? " is-on" : "") + '" data-vote="' + esc(t.id) + '"' +
      (on ? " disabled" : "") + ' aria-label="Vote for this topic (' + plural(n) + ')" title="' + plural(n) + '">▲ <span class="topic-slide__n">' + n +
      '</span></button><span class="topic-slide__host">' + esc(host(t.url)) + "</span></div></article>";
  }

  function render(box, base) {
    var track = box.querySelector("[data-upcoming-list]");
    var max = parseInt(box.dataset.max || "8", 10);
    fetch(base + "/api/queue").then(function (r) { return r.json(); }).then(function (rows) {
      rows = (rows || []).slice(0, max);
      if (!rows.length) { track.innerHTML = '<p class="ideas__empty">The queue refills every morning. Check back soon.</p>'; return; }
      track.innerHTML = rows.map(card).join("");
      track.querySelectorAll("[data-vote]").forEach(function (b) {
        b.addEventListener("click", function () {
          b.disabled = true;
          fetch(base + "/api/queue/" + encodeURIComponent(b.dataset.vote) + "/vote", { method: "POST" })
            .then(function (r) { return r.json(); })
            .then(function (d) {
              if (d && d.votes != null) {
                b.querySelector(".topic-slide__n").textContent = d.votes;
                b.setAttribute("aria-label", "Voted (" + plural(d.votes) + ")");
                b.title = plural(d.votes);
                b.classList.add("is-on");
                remember(b.dataset.vote);
              } else { b.disabled = false; }
            })
            .catch(function () { b.disabled = false; });
        });
      });
      box.setAttribute("data-carousel", "");
      if (window.carouselSetup) window.carouselSetup(box);
    }).catch(function () { track.innerHTML = '<p class="ideas__empty">Upcoming topics are offline right now. Please try again later.</p>'; });
  }

  function setup() {
    var box = document.querySelector("[data-upcoming]");
    if (!box || box.dataset.loaded) return;
    box.dataset.loaded = "1";
    var base = (box.dataset.editorial || "").replace(/\/$/, "");
    if (base) render(box, base);
    else box.querySelector("[data-upcoming-list]").innerHTML = '<p class="ideas__empty">Upcoming topics are offline in this preview.</p>';
  }
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(setup);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setup);
  else setup();
})();
