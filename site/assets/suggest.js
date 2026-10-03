// About page → "Suggest a project": posts to the site assistant's /api/suggest (the same service as the Ask button;
// its URL comes from the widget's script tag). Suggestions land in Ruairi's daily email.
(function () {
  function setup() {
    var form = document.querySelector("[data-suggest]");
    if (!form || form.dataset.ready) return;
    form.dataset.ready = "1";
    var status = form.querySelector("[data-status]");
    var tag = document.querySelector("script[data-endpoint]");
    var api = tag ? tag.getAttribute("data-endpoint") : "";
    if (!api) {
      status.textContent = "The suggestion box is offline in this preview. Please reach me on LinkedIn instead.";
      form.querySelector("button").disabled = true;
      return;
    }
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var f = new FormData(form), btn = form.querySelector("button");
      btn.disabled = true;
      status.textContent = "Sending…";
      fetch(api + "/api/suggest", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idea: f.get("idea"), name: f.get("name"), contact: f.get("contact"),
                               website: f.get("website"), page: location.href })
      }).then(function (r) {
        if (r.ok) { form.reset(); status.textContent = "Thank you! Your suggestion is on its way to me."; return; }
        return r.json().then(function (d) {
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
