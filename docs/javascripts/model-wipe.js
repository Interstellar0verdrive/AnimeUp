/* Wipe comparison for the model study: two versions of the same region, one over the other.
   Markup (written by Markdown, so MkDocs rewrites the image paths):
   <div class="ms-wipe" data-right="cugan" markdown>
   ![](../img/model-study/<case>/wipe-original.webp){ .ms-a }
   </div>
   The other versions are looked up next to that image as wipe-<model>.webp. Optional:
   data-models="original lanczos …" limits the choice, data-stretch adds a contrast-stretched
   view (wipe-<model>-x.webp). */
(function () {
  const MODELS = [
    ["original", "Original (pixels enlarged)"],
    ["lanczos", "Lanczos 2×"],
    ["animevideov3", "Real-ESRGAN animevideov3"],
    ["cugan", "Real-CUGAN no-denoise"],
    ["denoise", "Real-CUGAN light denoise"],
    ["conservative", "Real-CUGAN conservative"],
    ["fallin", "Fallin Soft"],
    ["adore", "Adore"],
    ["janai", "AnimeJaNai HD V3 Compact"],
    ["futsuu", "Futsuu Anime"],
    ["avc", "HFA2kAVCCompact"],
    ["spanim", "ModernSpanimation V1"],
  ];

  function select(label, keys, value, onChange) {
    const wrap = document.createElement("label");
    wrap.textContent = label + " ";
    const s = document.createElement("select");
    for (const [k, name] of MODELS) if (keys.includes(k)) s.add(new Option(name, k, false, k === value));
    s.addEventListener("change", () => onChange(s.value));
    wrap.appendChild(s);
    return wrap;
  }

  function setup(box) {
    if (box.dataset.ready) return;
    const a = box.querySelector("img");
    if (!a) return;
    box.dataset.ready = "1";
    const base = a.getAttribute("src").replace(/wipe-[a-z0-9]+\.webp$/, "");
    const keys = box.dataset.models ? box.dataset.models.split(" ") : MODELS.map((m) => m[0]);
    let stretched = false;
    const url = (k) => base + "wipe-" + k + (stretched ? "-x" : "") + ".webp";
    let left = a.getAttribute("src").match(/wipe-([a-z0-9]+)\.webp$/)[1];
    let right = box.dataset.right || "cugan";

    const view = document.createElement("div");
    view.className = "ms-wipe__view";
    view.style.setProperty("--x", "50%");
    const b = document.createElement("img");
    b.className = "ms-wipe__b";
    b.alt = "";
    b.src = url(right);
    a.classList.add("ms-wipe__a");
    a.alt = "";
    a.closest("p") ? a.closest("p").replaceWith(view) : a.remove();
    const handle = document.createElement("span");
    handle.className = "ms-wipe__handle";
    view.append(b, a, handle);

    const range = document.createElement("input");
    range.type = "range";
    range.min = "0";
    range.max = "100";
    range.value = "50";
    range.setAttribute("aria-label", "Divider position");
    const move = (p) => {
      p = Math.max(0, Math.min(100, p));
      view.style.setProperty("--x", p + "%");
      range.value = String(Math.round(p));
    };
    range.addEventListener("input", () => move(+range.value));
    view.addEventListener("pointermove", (e) => {
      const r = view.getBoundingClientRect();
      move(((e.clientX - r.left) / r.width) * 100);
    });

    const pick = document.createElement("div");
    pick.className = "ms-wipe__pick";
    pick.append(
      select("Left", keys, left, (k) => (a.src = url((left = k)))),
      select("Right", keys, right, (k) => (b.src = url((right = k))))
    );
    if ("stretch" in box.dataset) {
      const wrap = document.createElement("label");
      const box2 = document.createElement("input");
      box2.type = "checkbox";
      box2.addEventListener("change", () => {
        stretched = box2.checked;
        a.src = url(left);
        b.src = url(right);
      });
      wrap.append(box2, " Stretch contrast");
      pick.append(wrap);
    }
    box.prepend(pick);
    box.append(range);
  }

  const run = () => document.querySelectorAll(".ms-wipe").forEach(setup);
  if (window.document$ && window.document$.subscribe) window.document$.subscribe(run);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
  else run();
})();
