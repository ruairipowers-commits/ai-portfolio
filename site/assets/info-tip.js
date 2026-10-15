// Info buttons next to a page heading ([data-info-tip], aria-controls → the panel): click or tap toggles the panel;
// Escape or a click elsewhere closes it. Without JavaScript the panel stays hidden and the page still works.
(function () {
  function setup() {
    document.querySelectorAll("[data-info-tip]").forEach(function (btn) {
      if (btn.dataset.ready) return;
      btn.dataset.ready = "1";
      var panel = document.getElementById(btn.getAttribute("aria-controls"));
      if (!panel) return;
      function show(open) { panel.hidden = !open; btn.setAttribute("aria-expanded", String(open)); }
      btn.addEventListener("click", function (ev) { ev.stopPropagation(); show(panel.hidden); });
      document.addEventListener("click", function (ev) { if (!panel.hidden && !panel.contains(ev.target)) show(false); });
      document.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && !panel.hidden) { show(false); btn.focus(); } });
    });
  }
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(setup);
  else if (document.readyState !== "loading") setup();
  else document.addEventListener("DOMContentLoaded", setup);
})();
