(() => {
  const select = document.getElementById("animeup-theme-select");
  if (!select) return;

  const paletteIds = {
    slate: "__palette_0",
    "animeup-auto": "__palette_1",
    default: "__palette_2",
  };
  const favicon = document.querySelector('link[rel="icon"]');
  const systemLight = window.matchMedia("(prefers-color-scheme: light)");

  const sync = () => {
    const scheme = document.body.dataset.mdColorScheme || "slate";
    if (scheme in paletteIds) select.value = scheme;
    const light = scheme === "default" || (scheme === "animeup-auto" && systemLight.matches);
    if (favicon) favicon.href = light ? select.dataset.faviconLight : select.dataset.faviconDark;
  };

  select.addEventListener("change", () => {
    document.getElementById(paletteIds[select.value])?.click();
    sync();
  });
  new MutationObserver(sync).observe(document.body, {
    attributes: true,
    attributeFilter: ["data-md-color-scheme"],
  });
  systemLight.addEventListener("change", sync);
  sync();
})();
