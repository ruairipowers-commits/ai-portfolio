// Carousels on the home page (the portfolio gallery and the latest posts).
// Markup (rendered by scripts/mkdocs_hooks.py):
//   <div class="carousel" data-carousel data-interval="7000" aria-roledescription="carousel" aria-label="...">
//     <div class="carousel__track"> ...items... </div>
//   </div>
// Without JavaScript the track is a horizontally scrollable row with scroll-snap. This adds page dots, previous /
// next buttons and auto-advance. Auto-advance pauses while the pointer is over it, while anything inside has focus,
// while the tab is hidden, after the visitor uses the controls, and never runs with prefers-reduced-motion.
(function () {
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function setup(root) {
    if (root.dataset.ready) return;
    root.dataset.ready = "1";
    var track = root.querySelector(".carousel__track");
    if (!track) return;
    var interval = parseInt(root.dataset.interval || "7000", 10);
    var controls = document.createElement("div");
    controls.className = "carousel__controls";
    var prev = button("carousel__arrow", "Previous", "‹");
    var dots = document.createElement("div");
    dots.className = "carousel__dots";
    var next = button("carousel__arrow", "Next", "›");
    controls.append(prev, dots, next);
    root.appendChild(controls);

    var paused = false, hovering = false, focused = false, timer = null;

    function pages() { return Math.max(1, Math.round(track.scrollWidth / track.clientWidth)); }
    function current() { return Math.min(pages() - 1, Math.round(track.scrollLeft / track.clientWidth)); }
    function go(i) {
      var n = pages();
      i = (i + n) % n;
      track.scrollTo({ left: i * track.clientWidth, behavior: reduced ? "auto" : "smooth" });
    }
    function drawDots() {
      var n = pages();
      if (dots.children.length !== n) {
        dots.innerHTML = "";
        for (var i = 0; i < n; i++) {
          var d = button("carousel__dot", "Page " + (i + 1) + " of " + n, "");
          d.dataset.page = i;
          d.addEventListener("click", function (ev) { stopAuto(); go(+ev.currentTarget.dataset.page); });
          dots.appendChild(d);
        }
      }
      var c = current();
      Array.prototype.forEach.call(dots.children, function (d, i) {
        d.setAttribute("aria-current", i === c ? "true" : "false");
      });
      controls.hidden = n < 2;
    }
    function tick() { if (!paused && !hovering && !focused && !document.hidden) go(current() + 1); }
    function startAuto() { if (!reduced && !timer && interval > 0) timer = setInterval(tick, interval); }
    function stopAuto() { paused = true; if (timer) { clearInterval(timer); timer = null; } }

    prev.addEventListener("click", function () { stopAuto(); go(current() - 1); });
    next.addEventListener("click", function () { stopAuto(); go(current() + 1); });
    root.addEventListener("mouseenter", function () { hovering = true; });
    root.addEventListener("mouseleave", function () { hovering = false; });
    root.addEventListener("focusin", function () { focused = true; });
    root.addEventListener("focusout", function () { focused = root.contains(document.activeElement); });
    track.addEventListener("touchstart", stopAuto, { passive: true });
    var t;
    track.addEventListener("scroll", function () { clearTimeout(t); t = setTimeout(drawDots, 80); }, { passive: true });
    window.addEventListener("resize", drawDots);
    drawDots();
    startAuto();
  }

  function button(cls, label, text) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = cls;
    b.setAttribute("aria-label", label);
    b.textContent = text;
    return b;
  }

  function init() { document.querySelectorAll("[data-carousel]").forEach(setup); }
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(init);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
