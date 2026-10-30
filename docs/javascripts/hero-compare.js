// The guide's cover: a before/after comparison like the one in the app's Compare page.
// The divider sweeps once across the picture to show it can be moved, then follows the
// pointer or a drag. Reduced motion skips the sweep.
(function () {
  function setup(root) {
    if (root.dataset.ready) return;
    root.dataset.ready = "1";
    var set = function (pct) {
      root.style.setProperty("--pos", Math.max(0, Math.min(100, pct)) + "%");
    };
    var touched = false;
    var fromEvent = function (e) {
      var r = root.getBoundingClientRect();
      var x = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
      set((x / r.width) * 100);
    };
    var dragging = false;
    root.addEventListener("pointerdown", function (e) {
      if (e.target.closest(".au-hero__zoom")) return;
      touched = dragging = true;
      root.setPointerCapture(e.pointerId);
      fromEvent(e);
    });
    root.addEventListener("pointermove", function (e) {
      if (dragging || e.pointerType === "mouse") {
        touched = true;
        fromEvent(e);
      }
    });
    root.addEventListener("pointerup", function () { dragging = false; });
    root.addEventListener("keydown", function (e) {
      var now = parseFloat(getComputedStyle(root).getPropertyValue("--pos")) || 50;
      if (e.key === "ArrowLeft") { touched = true; set(now - 5); }
      if (e.key === "ArrowRight") { touched = true; set(now + 5); }
    });
    set(50);
    var zoom = root.querySelector(".au-hero__zoom");
    if (zoom) zoom.addEventListener("click", function (e) {
      e.stopPropagation();
      touched = true;
      openFull(root);
    });
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    // one slow sweep: centre, all the way left, all the way right, back to the centre
    var start = null, dur = 6000;
    var path = function (t) {
      var a = Math.sin(t * Math.PI * 2);
      return 50 - 46 * a;
    };
    var step = function (now) {
      if (touched) return;
      if (start === null) start = now;
      var t = (now - start) / dur;
      if (t >= 1) { set(50); return; }
      var eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      set(path(eased));
      requestAnimationFrame(step);
    };
    var io = new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting) {
        io.disconnect();
        setTimeout(function () { requestAnimationFrame(step); }, 600);
      }
    });
    io.observe(root);
  }
  // 1:1 in an overlay: the same comparison with one picture pixel per screen pixel,
  // panned by scrolling when it's larger than the window. Esc, the button or a click outside closes it.
  function openFull(hero) {
    var imgs = hero.querySelectorAll("img.au-hero__pic");
    var after = imgs[0].currentSrc || imgs[0].src, before = imgs[1].currentSrc || imgs[1].src;
    var w = imgs[0].naturalWidth / (window.devicePixelRatio || 1);
    var h = imgs[0].naturalHeight / (window.devicePixelRatio || 1);
    var box = document.createElement("div");
    box.className = "au-full";
    box.innerHTML =
      '<div class="au-full__scroll"><div class="au-full__pic au-hero" style="width:' + w + 'px;height:' + h + 'px">' +
      '<img src="' + after + '" alt=""><img class="au-hero__before" src="' + before + '" alt="">' +
      '<span class="au-hero__line"><span class="au-hero__knob"><svg width="20" height="14" viewBox="0 0 20 14" aria-hidden="true"><path d="M7 2 2 7l5 5M13 2l5 5-5 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span></span></div></div>' +
      '<span class="au-full__tag au-full__tag--l">' + (hero.dataset.before || "") + '</span><span class="au-full__tag au-full__tag--r">' + (hero.dataset.after || "") + '</span>' +
      '<button class="au-full__close" type="button" aria-label="Close">×</button>';
    document.body.appendChild(box);
    document.documentElement.style.overflow = "hidden";
    var pic = box.querySelector(".au-full__pic");
    pic.dataset.ready = "1";
    var move = function (e) {
      var r = pic.getBoundingClientRect();
      pic.style.setProperty("--pos", Math.max(0, Math.min(100, ((e.clientX - r.left) / r.width) * 100)) + "%");
    };
    pic.addEventListener("pointermove", move);
    pic.addEventListener("pointerdown", move);
    var close = function () {
      box.remove();
      document.documentElement.style.overflow = "";
      document.removeEventListener("keydown", esc);
    };
    var esc = function (e) { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", esc);
    box.querySelector(".au-full__close").addEventListener("click", close);
    box.addEventListener("click", function (e) { if (e.target === box || e.target.classList.contains("au-full__scroll")) close(); });
    var sc = box.querySelector(".au-full__scroll");
    sc.scrollLeft = (sc.scrollWidth - sc.clientWidth) / 2;
    sc.scrollTop = (sc.scrollHeight - sc.clientHeight) / 2;
  }
  function gallery(g) {
    if (g.dataset.ready) return;
    g.dataset.ready = "1";
    var slides = g.querySelectorAll(".au-hero"), tabs = g.querySelectorAll(".au-gallery__tabs button");
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () {
        slides.forEach(function (s, j) { s.classList.toggle("is-on", i === j); });
        tabs.forEach(function (b, j) { b.classList.toggle("is-on", i === j); b.setAttribute("aria-selected", i === j); });
      });
    });
  }
  function init() {
    document.querySelectorAll(".au-gallery").forEach(gallery);
    document.querySelectorAll(".au-hero").forEach(setup);
  }
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(init);
  else document.addEventListener("DOMContentLoaded", init);
})();
