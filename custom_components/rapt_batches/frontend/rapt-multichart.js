// One chart that overlays gravity, temperature, velocity, battery and ABV, each on its
// own scale, with toggle chips, a hover tooltip and drag-to-zoom. Used by the sidebar
// panel and the batch card. The caller loads uPlot and passes it in as `lib`.

const ABV_FACTOR = 131.25;
const GRID = "rgba(128,128,128,0.2)";

// Order is the order of chips and of axis assignment: the first enabled series gets the
// left axis, the second the right axis, any others appear in the tooltip only.
export const SERIES = [
  { key: "sg", label: "Gravity", color: "#f2b544", digits: 3, width: 3, minPad: 0.002 },
  { key: "abv", label: "ABV", color: "#4caf7d", digits: 2, unit: "%", width: 2, minPad: 0.2, derived: true },
  { key: "temp", label: "Temperature", color: "#4fc3f7", digits: 1, unit: "°", width: 2, minPad: 0.5 },
  { key: "velocity", label: "Velocity", color: "#b57edc", digits: 2, width: 2, minPad: 1 },
  { key: "battery", label: "Battery", color: "#9e9e9e", digits: 0, unit: "%", width: 2, minPad: 2 },
];
const OG_COLOR = "#e0763f";

export const MULTI_CSS = `
.mc-chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 8px}
.mc-chip{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:16px;border:1px solid var(--divider-color);background:none;color:var(--secondary-text-color);font:inherit;font-size:13px;cursor:pointer}
.mc-chip i{width:10px;height:10px;border-radius:50%;background:var(--c);opacity:.35}
.mc-chip.on{color:var(--primary-text-color);border-color:var(--c);background:var(--secondary-background-color)}
.mc-chip.on i{opacity:1}
.mc-plot{position:relative}
.mc-tip{position:absolute;top:8px;z-index:5;display:none;pointer-events:none;padding:8px 10px;border-radius:8px;background:var(--card-background-color);color:var(--primary-text-color);border:1px solid var(--divider-color);box-shadow:0 2px 12px rgba(0,0,0,.35);font-size:12px;white-space:nowrap}
.mc-tip-time{color:var(--secondary-text-color);margin-bottom:4px}
.mc-tip-row{display:flex;align-items:center;gap:6px;line-height:1.5}
.mc-tip-row i{width:8px;height:8px;border-radius:50%}
.mc-tip-row b{margin-left:auto;padding-left:14px;font-weight:500}
.mc-reset{position:absolute;top:2px;right:6px;z-index:6;display:none;padding:2px 10px;font:inherit;font-size:12px;border-radius:12px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer}
.mc-empty{padding:32px;text-align:center;color:var(--secondary-text-color)}
`;

const rgba = (hex, a) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};
const num = (v, d) => (v == null || Number.isNaN(v) ? "--" : Number(v).toFixed(d));
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// The value a sensor held at time x: its last reading at or before x.
export function lastAt(d, x) {
  if (!d.t.length) return null;
  if (x <= d.t[0]) return d.v[0];
  let lo = 0;
  let hi = d.t.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (d.t[mid] <= x) lo = mid;
    else hi = mid - 1;
  }
  return d.v[lo];
}

// opts: series (the readings API result), og, height, storageKey (remember the toggles),
// chips (show the toggles), initial (series on by default), allowed (limit the series),
// state ({enabled, zoom} from a previous chart, to survive a redraw),
// window ({start, end} in seconds: everything outside is greyed out), selectMode (drag selects a
// range instead of zooming) and onSelect(range|null).
export function createMultiChart(lib, host, opts = {}) {
  const { series: S = {}, og = null, height = 300, storageKey = null, chips = true, state = null, allowed = null } = opts;

  const data = {};
  for (const def of SERIES) {
    let d = null;
    if (def.key === "abv") {
      if (S.sg && S.sg.t.length && og != null) d = { t: S.sg.t, v: S.sg.v.map((v) => Math.max(0, (og - v) * ABV_FACTOR)) };
    } else if (S[def.key] && S[def.key].t.length) d = S[def.key];
    if (d && (!allowed || allowed.includes(def.key))) data[def.key] = d;
  }
  const avail = SERIES.filter((s) => data[s.key]);

  let stored = null;
  if (storageKey) {
    try {
      stored = JSON.parse(localStorage.getItem(storageKey));
    } catch (e) {
      stored = null;
    }
  }
  const initial = (state && state.enabled) || (Array.isArray(stored) && stored) || opts.initial || ["sg", "temp"];
  const enabled = new Set(avail.map((s) => s.key).filter((k) => initial.includes(k)));
  if (!enabled.size && avail.length) enabled.add(avail[0].key);

  host.innerHTML =
    (chips && avail.length > 1
      ? `<div class="mc-chips">${avail
          .map((s) => `<button class="mc-chip ${enabled.has(s.key) ? "on" : ""}" data-k="${s.key}" style="--c:${s.color}" aria-pressed="${enabled.has(s.key)}"><i></i>${esc(s.label)}</button>`)
          .join("")}</div>`
      : "") + `<div class="mc-plot"><button class="mc-reset">Reset zoom</button></div>`;
  const plotEl = host.querySelector(".mc-plot");
  const resetBtn = plotEl.querySelector(".mc-reset");

  let win = opts.window ? { ...opts.window } : null;
  let sel = null;
  let u = null;
  let full = null;
  let zoom = (state && state.zoom) || null;
  let zoomed = false;

  const currentZoom = () => (u ? (zoomed ? { min: u.scales.x.min, max: u.scales.x.max } : null) : zoom);
  const persist = () => {
    if (!storageKey) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify([...enabled]));
    } catch (e) {
      /* storage can be unavailable; the toggles just will not be remembered */
    }
  };

  function build() {
    if (sel) {
      sel = null; // a redraw drops the selection box
      if (opts.onSelect) opts.onSelect(null);
    }
    if (u) {
      zoom = currentZoom();
      u.destroy();
      u = null;
    }
    const on = avail.filter((s) => enabled.has(s.key));
    if (!on.length) {
      plotEl.insertAdjacentHTML("afterbegin", `<div class="mc-empty">No data to chart yet</div>`);
      return;
    }
    const cs = getComputedStyle(host);
    const txt = cs.getPropertyValue("--secondary-text-color").trim() || "#999";
    const tables = [];
    const sers = [];
    const scales = { x: { time: true } };
    const axes = [{ stroke: txt, grid: { stroke: GRID, width: 1 }, ticks: { stroke: GRID, width: 1 } }];
    on.forEach((s, i) => {
      const d = data[s.key];
      tables.push([d.t, d.v]);
      sers.push({
        label: s.label,
        scale: s.key,
        stroke: s.color,
        width: s.width,
        spanGaps: true,
        points: { show: false },
        fill: on.length === 1 ? rgba(s.color, 0.14) : undefined,
      });
      scales[s.key] = {
        range: (uu, min, max) => {
          const pad = Math.max((max - min) * 0.12, s.minPad);
          return [min - pad, max + pad];
        },
      };
      axes.push({
        scale: s.key,
        side: i === 0 ? 3 : 1,
        show: i < 2,
        stroke: s.color,
        size: 62,
        grid: { show: i === 0, stroke: GRID, width: 1 },
        ticks: { stroke: GRID, width: 1 },
        values: (uu, vals) => vals.map((v) => (v == null ? "" : num(v, s.digits))),
      });
      if (s.key === "sg" && og != null) {
        tables.push([d.t, d.t.map(() => og)]);
        sers.push({ label: "OG", scale: "sg", stroke: OG_COLOR, width: 1, dash: [6, 4], spanGaps: true, points: { show: false } });
      }
    });
    const joined = lib.uPlot.join(tables);
    full = [joined[0][0], joined[0][joined[0].length - 1]];

    const tip = document.createElement("div");
    tip.className = "mc-tip";
    const hooks = {
      ready: [(uu) => uu.over.appendChild(tip)],
      draw: [
        (uu) => {
          if (!win) return;
          const { ctx, bbox } = uu;
          const left = bbox.left;
          const right = bbox.left + bbox.width;
          const clamp = (x) => Math.min(Math.max(x, left), right);
          const x0 = clamp(uu.valToPos(win.start, "x", true));
          const x1 = clamp(uu.valToPos(win.end, "x", true));
          ctx.save();
          ctx.fillStyle = "rgba(128,128,128,0.35)";
          if (x0 - left > 0.5) ctx.fillRect(left, bbox.top, x0 - left, bbox.height);
          if (right - x1 > 0.5) ctx.fillRect(x1, bbox.top, right - x1, bbox.height);
          ctx.strokeStyle = OG_COLOR;
          ctx.lineWidth = 1.5;
          ctx.setLineDash([6, 4]);
          for (const x of [x0, x1]) {
            if (x > left && x < right) {
              ctx.beginPath();
              ctx.moveTo(x, bbox.top);
              ctx.lineTo(x, bbox.top + bbox.height);
              ctx.stroke();
            }
          }
          ctx.restore();
        },
      ],
      setSelect: [
        (uu) => {
          if (!opts.selectMode) return;
          const sb = uu.select;
          sel = sb.width > 3 ? { min: uu.posToVal(sb.left, "x"), max: uu.posToVal(sb.left + sb.width, "x") } : null;
          if (opts.onSelect) opts.onSelect(sel);
        },
      ],
      setScale: [
        (uu, key) => {
          if (key !== "x") return;
          const sc = uu.scales.x;
          zoomed = sc.min > full[0] + 1 || sc.max < full[1] - 1;
          resetBtn.style.display = zoomed ? "block" : "none";
        },
      ],
      setCursor: [
        (uu) => {
          const { left, idx } = uu.cursor;
          if (idx == null || left == null || left < 0) {
            tip.style.display = "none";
            return;
          }
          const x = uu.posToVal(left, "x");
          tip.innerHTML =
            `<div class="mc-tip-time">${new Date(x * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</div>` +
            on
              .map((s) => `<div class="mc-tip-row"><i style="background:${s.color}"></i><span>${esc(s.label)}</span><b>${num(lastAt(data[s.key], x), s.digits)}${s.unit || ""}</b></div>`)
              .join("");
          tip.style.display = "block";
          const w = tip.offsetWidth;
          const ow = uu.over.clientWidth;
          tip.style.left = (left + 14 + w > ow ? Math.max(0, left - w - 14) : left + 14) + "px";
        },
      ],
    };
    u = new lib.uPlot(
      {
        width: Math.max(plotEl.clientWidth, 240),
        height,
        scales,
        series: [{}, ...sers],
        axes,
        legend: { show: false },
        cursor: { x: true, y: false, points: { show: false }, drag: { x: true, y: false, setScale: !opts.selectMode } },
        hooks,
      },
      joined,
      plotEl
    );
    if (zoom) u.setScale("x", { min: Math.max(zoom.min, full[0]), max: Math.min(zoom.max, full[1]) });
  }

  function toggle(key) {
    if (enabled.has(key)) {
      if (enabled.size === 1) return; // always keep one series showing
      enabled.delete(key);
    } else enabled.add(key);
    persist();
    host.querySelectorAll(".mc-chip").forEach((b) => {
      b.classList.toggle("on", enabled.has(b.dataset.k));
      b.setAttribute("aria-pressed", String(enabled.has(b.dataset.k)));
    });
    build();
  }

  const onClick = (e) => {
    const chip = e.target.closest(".mc-chip");
    if (chip) return toggle(chip.dataset.k);
    if (e.target.closest(".mc-reset") && u) {
      zoom = null;
      u.setScale("x", { min: full[0], max: full[1] });
    }
  };
  host.addEventListener("click", onClick);
  build();

  return {
    root: plotEl,
    destroy() {
      host.removeEventListener("click", onClick);
      if (u) u.destroy();
      u = null;
    },
    setSize({ width }) {
      if (u) u.setSize({ width, height });
    },
    getState() {
      return { enabled: [...enabled], zoom: currentZoom() };
    },
    // Window editing: grey out what is outside, read and clear the dragged range, zoom into it.
    setWindow(w) {
      win = w ? { ...w } : null;
      if (u) u.redraw(false);
    },
    getSelection() {
      return sel;
    },
    clearSelection() {
      sel = null;
      if (u) u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
      if (opts.onSelect) opts.onSelect(null);
    },
    zoomTo(range) {
      this.clearSelection();
      if (u) u.setScale("x", { min: Math.max(range.min, full[0]), max: Math.min(range.max, full[1]) });
    },
  };
}
