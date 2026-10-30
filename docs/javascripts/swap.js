// "Where it started": scrolling down, just before the picture reaches the middle of the window, AnimeUp 2.0 wipes
// in over 1.6 from the top down with a soft edge, lit as if by a burst of sun that then fades. Scrolling back
// up past that point brings 1.6 back the same way, without the light. The wipe itself is a CSS transition.
(function () {
  function setup(box) {
    if (box.dataset.ready) return;
    box.dataset.ready = "1";
    var gone = false;
    function check() {
      // forwards just before the picture's middle reaches the window's; back once it's a little below again
      var r = box.getBoundingClientRect(), mid = r.top + r.height / 2, vh = window.innerHeight;
      if (!gone && mid <= vh * 0.62) gone = true;
      else if (gone && mid > vh * 0.72) gone = false;
      else return;
      box.classList.toggle("is-sunlit", gone);
      box.classList.toggle("is-gone", gone);
    }
    window.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check);
    check();
  }
  function init() { document.querySelectorAll(".au-swap").forEach(setup); }
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(init);
  else document.addEventListener("DOMContentLoaded", init);
})();
