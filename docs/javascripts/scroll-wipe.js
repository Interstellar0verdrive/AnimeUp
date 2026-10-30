// The design page's cover: as the page scrolls, the light design system wipes over the dark one, top to
// bottom. Reduced motion keeps the dark one.
(function () {
  function setup(box) {
    if (box.dataset.ready) return;
    box.dataset.ready = "1";
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    var update = function () {
      // in page coordinates: the wipe starts when scrolling brings the picture's top three quarters
      // down the window (or at once, for a picture already in view at the top of the page) and ends
      // when its bottom reaches the window's top third
      var r = box.getBoundingClientRect(), vh = window.innerHeight, y = window.scrollY;
      var top = r.top + y, start = Math.max(0, top - vh * 0.75), end = top + r.height - vh * 0.33;
      var p = (y - start) / Math.max(1, end - start);
      box.style.setProperty("--wipe", Math.max(0, Math.min(1, p)).toFixed(4));
    };
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
  }
  function init() { document.querySelectorAll(".au-fade").forEach(setup); }
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(init);
  else document.addEventListener("DOMContentLoaded", init);
})();
