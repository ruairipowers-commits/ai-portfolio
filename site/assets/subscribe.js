// "Get new posts by email" boxes (end of every post, and on Home). Posts the address to the site assistant, which
// sends ONE confirmation email; nothing else is sent until the reader confirms (double opt-in). Every post email has a
// one-click unsubscribe that deletes the address. Hidden when the assistant isn't configured for this build.
(function () {
  function api() { var t = document.querySelector("script[data-endpoint]"); return t ? t.getAttribute("data-endpoint") : ""; }
  function setup() {
    var base = api();
    document.querySelectorAll("[data-subscribe]").forEach(function (box) {
      if (box.dataset.ready) return;
      box.dataset.ready = "1";
      if (!base) { box.hidden = true; return; }
      var form = box.querySelector("form"), msg = box.querySelector("[data-subscribe-msg]");
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var email = form.querySelector("input[type=email]").value.trim(), btn = form.querySelector("button");
        if (!email) return;
        btn.disabled = true;
        fetch(base + "/api/subscribe", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email, website: form.querySelector("[name=website]").value }) })
          .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
          .then(function (x) {
            msg.textContent = x.ok ? x.d.message : (x.d.detail || "Something went wrong — please try again later.");
            if (x.ok) form.hidden = true; else btn.disabled = false;
          })
          .catch(function () { msg.textContent = "Couldn't reach the server — please try again later."; btn.disabled = false; });
      });
    });
  }
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(setup);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setup);
  else setup();
})();
