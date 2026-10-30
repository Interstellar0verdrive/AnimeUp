// The design page's cover: as the page scrolls, the light design system wipes over the dark one along the
// diagonal, from the top-left corner to the bottom-right one (light over dark in the light theme, the other
// way round). Reduced motion keeps the first.
(function () {
  // the page's own theme comes first, the other one wipes over it: in light, light then dark
  function light() {
    var sc = document.body.getAttribute("data-md-color-scheme");
    return sc === "default" || (sc === "animeup-auto" && window.matchMedia("(prefers-color-scheme: light)").matches);
  }
  function order(box) {
    var imgs = box.querySelectorAll("img");
    if (!box.dataset.dark) { box.dataset.dark = imgs[0].getAttribute("src"); box.dataset.light = imgs[1].getAttribute("src"); }
    var l = light();
    imgs[0].setAttribute("src", l ? box.dataset.light : box.dataset.dark);
    imgs[1].setAttribute("src", l ? box.dataset.dark : box.dataset.light);
  }
  function setup(box) {
    if (box.dataset.ready) return;
    box.dataset.ready = "1";
    order(box);
    new MutationObserver(function () { order(box); }).observe(document.body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
    window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", function () { order(box); });
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    var line = box.querySelector(".au-fade__edge line");
    var update = function () {
      // in page coordinates: the wipe starts just before the picture begins to slide under the header
      // (or at once, if the page opens already past that point) and ends when half the picture is gone
      var r = box.getBoundingClientRect(), y = window.scrollY;
      var head = document.querySelector(".md-header"), hh = head ? head.offsetHeight : 0;
      var top = r.top + y - hh, start = Math.max(0, top - window.innerHeight * 0.08), end = top + r.height / 2;
      var p = Math.max(0, Math.min(1, (y - start) / Math.max(1, end - start)));
      var a = Math.min(2 * p, 1), b = Math.max(2 * p - 1, 0);
      box.style.setProperty("--wipe", p.toFixed(4));
      box.style.setProperty("--a", a.toFixed(4));
      box.style.setProperty("--b", b.toFixed(4));
      if (line) {
        line.setAttribute("x1", a * 100); line.setAttribute("y1", b * 100);
        line.setAttribute("x2", b * 100); line.setAttribute("y2", a * 100);
      }
    };
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
  }
  function init() { document.querySelectorAll(".au-fade").forEach(setup); }
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(init);
  else document.addEventListener("DOMContentLoaded", init);
})();
