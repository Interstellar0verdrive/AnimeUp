(() => {
  const links = [...document.querySelectorAll('.md-sidebar--secondary [data-md-component="toc"] a[href^="#"]')];
  const sections = links
    .map((link) => ({ link, heading: document.getElementById(decodeURIComponent(link.hash.slice(1))) }))
    .filter(({ heading }) => heading);
  if (!sections.length) return;

  let frame = 0;
  const update = () => {
    frame = 0;
    const marker = Math.min(140, window.innerHeight * 0.25);
    let current = sections[0];
    for (const section of sections) {
      if (section.heading.getBoundingClientRect().top > marker) break;
      current = section;
    }
    for (const section of sections) {
      const active = section === current;
      section.link.classList.toggle('animeup-toc-current', active);
      if (active) section.link.setAttribute('aria-current', 'location');
      else section.link.removeAttribute('aria-current');
    }
  };
  const schedule = () => {
    if (!frame) frame = requestAnimationFrame(update);
  };

  addEventListener('scroll', schedule, { passive: true });
  addEventListener('resize', schedule);
  addEventListener('hashchange', schedule);
  schedule();
})();
