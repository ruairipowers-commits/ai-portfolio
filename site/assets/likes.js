// "Was this useful?" at the end of every post: 👍, or 👎 with an optional note on what was missing (never
// published). Like counts also show on the blog list.
// One per visitor per post per day on the server; the browser remembers which posts you liked.
(function () {
  function api() { var t = document.querySelector("script[data-endpoint]"); return t ? t.getAttribute("data-endpoint") : ""; }
  function liked(p) { try { return JSON.parse(localStorage.getItem("post-likes") || "{}")[p]; } catch (e) { return false; } }
  function remember(p, which) { try { var v = JSON.parse(localStorage.getItem("post-likes") || "{}"); v[p] = which || "yes"; localStorage.setItem("post-likes", JSON.stringify(v)); } catch (e) {} }

  function setup() {
    var base = api();
    var box = document.querySelector("[data-like]");
    if (box && !box.dataset.ready) {
      box.dataset.ready = "1";
      if (!base) { box.hidden = true; } else {
        var path = location.pathname, yes = box.querySelector("[data-like-yes]"), no = box.querySelector("[data-like-no]");
        var n = box.querySelector("[data-like-n]"), thanks = box.querySelector("[data-like-thanks]");
        var why = box.querySelector("[data-like-why]");
        var show = function (c) { n.textContent = c ? c + (c === 1 ? " person found" : " people found") + " this useful" : ""; };
        var done = function (which) { yes.disabled = no.disabled = true; (which === "no" ? no : yes).classList.add("is-on"); };
        var prior = liked(path);
        if (prior) done(prior === "no" ? "no" : "yes");
        fetch(base + "/api/likes?paths=" + encodeURIComponent(path)).then(function (r) { return r.json(); })
          .then(function (d) { var v = d && d.likes; show(v ? v[Object.keys(v)[0]] : 0); }).catch(function () {});
        yes.addEventListener("click", function () {
          done("yes");
          fetch(base + "/api/like", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: path }) })
            .then(function (r) { return r.json(); })
            .then(function (d) { remember(path, "yes"); show(d.likes); thanks.hidden = false; })
            .catch(function () { yes.disabled = no.disabled = false; });
        });
        var sendNo = function (note) {
          return fetch(base + "/api/unhelpful", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: path, note: note || "" }) });
        };
        no.addEventListener("click", function () {
          done("no");
          sendNo("").then(function () { remember(path, "no"); why.hidden = false; why.querySelector("textarea").focus(); })
            .catch(function () { yes.disabled = no.disabled = false; });
        });
        why.addEventListener("submit", function (e) {
          e.preventDefault();
          var note = why.querySelector("textarea").value.trim();
          if (!note) { why.hidden = true; thanks.hidden = false; return; }
          sendNo(note).then(function () { why.hidden = true; thanks.textContent = "Thank you, that helps me improve it."; thanks.hidden = false; });
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
