// "Where it started": once the picture is in view, AnimeUp 2.0 wipes in over 1.6 from the top down, with a
// soft edge; scrolling back up past that point brings 1.6 back. The wipe itself is a CSS transition.
(function () {
  function setup(box) {
    if (box.dataset.ready) return;
    box.dataset.ready = "1";
    var gone = false;
    function check() {
      // it starts once the whole picture is in the window, or its top has passed the middle (a picture taller
      // than the window never fits); it goes back once the picture is down again, mostly below the window
      var r = box.getBoundingClientRect(), vh = window.innerHeight;
      if (!gone && (r.bottom <= vh - 8 || r.top <= vh * 0.5)) gone = true;
      else if (gone && r.top > vh * 0.75) gone = false;
      else return;
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
