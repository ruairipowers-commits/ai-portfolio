// Thumbs up: a "Was this useful?" button at the end of every post, and like counts on the blog list.
// One per visitor per post per day on the server; the browser remembers which posts you liked.
(function () {
  function api() { var t = document.querySelector("script[data-endpoint]"); return t ? t.getAttribute("data-endpoint") : ""; }
  function liked(p) { try { return JSON.parse(localStorage.getItem("post-likes") || "{}")[p]; } catch (e) { return false; } }
  function remember(p) { try { var v = JSON.parse(localStorage.getItem("post-likes") || "{}"); v[p] = 1; localStorage.setItem("post-likes", JSON.stringify(v)); } catch (e) {} }

  function setup() {
    var base = api();
    var box = document.querySelector("[data-like]");
    if (box && !box.dataset.ready) {
      box.dataset.ready = "1";
      if (!base) { box.hidden = true; } else {
        var path = location.pathname, btn = box.querySelector("button"), n = box.querySelector("[data-like-n]");
        var show = function (c) { n.textContent = c ? c + (c === 1 ? " person found" : " people found") + " this useful" : ""; };
        if (liked(path)) { btn.disabled = true; btn.classList.add("is-on"); }
        fetch(base + "/api/likes?paths=" + encodeURIComponent(path)).then(function (r) { return r.json(); })
          .then(function (d) { var v = d && d.likes; show(v ? v[Object.keys(v)[0]] : 0); }).catch(function () {});
        btn.addEventListener("click", function () {
          btn.disabled = true;
          fetch(base + "/api/like", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: path }) })
            .then(function (r) { return r.json(); })
            .then(function (d) { btn.classList.add("is-on"); remember(path); show(d.likes); box.querySelector("[data-like-thanks]").hidden = false; })
            .catch(function () { btn.disabled = false; });
        });
      }
    }
    // the blog list: a count on each card
    var cards = document.querySelectorAll(".post-card[data-path]");
    if (base && cards.length && !document.body.dataset.likesLoaded) {
      document.body.dataset.likesLoaded = "1";
      var paths = Array.prototype.map.call(cards, function (c) { return c.dataset.path; });
      fetch(base + "/api/likes?paths=" + encodeURIComponent(paths.join(","))).then(function (r) { return r.json(); }).then(function (d) {
        var v = (d && d.likes) || {};
        cards.forEach(function (c) {
          var k = c.dataset.key, n = v[k] || 0, el = c.querySelector("[data-card-likes]");
          if (el && n) { el.textContent = "👍 " + n; el.hidden = false; }
        });
      }).catch(function () {});
    }
  }
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(setup);
  else if (document.readyState !== "loading") setup();
  else document.addEventListener("DOMContentLoaded", setup);
})();
