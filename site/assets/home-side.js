// Side panels: Home's projects and latest posts, and the Blog's upcoming topics, move into the right-hand panel under
// the table of contents on screens wide enough to show it. On narrower screens they stay where they are, in the page.
// Loaded before carousel.js, so the carousels measure themselves in their final place.
(function () {
  function place() {
    var side = document.querySelector("[data-home-side], [data-side-panel]");
    if (!side || side.dataset.placed) return;
    var panel = document.querySelector(".md-sidebar--secondary .md-sidebar__inner");
    var sidebar = document.querySelector(".md-sidebar--secondary");
    if (sidebar && sidebar.hasAttribute("hidden")) sidebar.removeAttribute("hidden");   // no TOC on the page: show it anyway
    var wide = window.matchMedia("(min-width: 76.25em)").matches;
    if (!panel || !wide) return;
    side.dataset.placed = "1";
    side.classList.add("home-side--panel", "md-typeset");   // the panel isn't typeset: give the tiles the page's styles
    panel.appendChild(side);
  }
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(place);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", place);
  else place();
})();
