// Helpers shared by the RAPT Batch Library dashboard cards.

export const BASE = new URL("./", import.meta.url).href;
export const PANEL_PATH = "/rapt-batches";
export const ABV_FACTOR = 131.25;
export const COLORS = { sg: "#f2b544", og: "#e0763f", abv: "#4caf7d", temp: "#4fc3f7", battery: "#9e9e9e", velocity: "#b57edc" };
export const LABEL = { active: "Active", completed: "Finished", archived: "Archived" };
export const CHART_LABEL = { sg: "Specific gravity", abv: "ABV %", temp: "Temperature", velocity: "Gravity velocity", battery: "Battery %" };

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const fmt = (v, d = 3) => (v == null || Number.isNaN(v) ? "--" : Number(v).toFixed(d));
export const abv = (og, sg) => (og == null || sg == null ? null : Math.max(0, (og - sg) * ABV_FACTOR));
export const daysOf = (b) => ((b.status !== "active" && b.end_ts ? b.end_ts : Date.now() / 1000) - b.start_ts) / 86400;

export function navigate(path) {
  history.pushState(null, "", path);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
}

let _lib;
export function loadLib() {
  if (!_lib) {
    _lib = (async () => {
      const css = await (await fetch(BASE + "uplot.min.css")).text();
      if (!window.uPlot) {
        await new Promise((resolve, reject) => {
          const s = document.createElement("script");
          s.src = BASE + "uplot.iife.min.js";
          s.onload = resolve;
          s.onerror = reject;
          document.head.appendChild(s);
        });
      }
      return { uPlot: window.uPlot, css };
    })();
  }
  return _lib;
}

export const CARD_STYLE = `
:host{display:block}
ha-card{padding:12px 16px 8px;overflow:hidden}
.head{display:flex;align-items:center;gap:8px;cursor:pointer;margin-bottom:8px}
.head h2{margin:0;font-size:18px;font-weight:500;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.badge{display:inline-block;padding:2px 10px;border-radius:10px;font-size:12px;color:#fff}
.s-active{background:#4caf7d}.s-completed{background:#e0a458}.s-archived{background:#7a7f8c}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(88px,1fr));gap:8px;margin-bottom:8px}
.stat b{display:block;font-size:20px;font-weight:500}
.stat span{font-size:12px;color:var(--secondary-text-color)}
.chart{margin-top:4px}
.empty{padding:16px;text-align:center;color:var(--secondary-text-color)}
.u-title{color:var(--primary-text-color);font-size:13px!important}
.u-legend{color:var(--secondary-text-color);font-size:11px}
`;

// Newest first. selector: "active" (default), "latest", a batch id or a batch name.
export function pickBatch(batches, selector) {
  const newest = (a, b) => b.start_ts - a.start_ts;
  if (!selector || selector === "active") return batches.filter((b) => b.status === "active").sort(newest)[0];
  if (selector === "latest") return [...batches].sort(newest)[0];
  return batches.find((b) => b.id === selector) || batches.find((b) => b.name === selector);
}

// Current reading: the live sensor state for an active batch, else the last stored value.
export function liveValue(hass, batch, key) {
  const eid = batch.entities && batch.entities[key];
  const st = eid && hass && hass.states[eid];
  const v = st ? parseFloat(st.state) : NaN;
  return Number.isNaN(v) ? batch.latest[key] : v;
}

export function drawChart(lib, host, title, data, series, opts = {}) {
  if (!data[0] || !data[0].length) {
    host.innerHTML = `<div class="empty">No ${esc(title)} data yet</div>`;
    return null;
  }
  const cs = getComputedStyle(host);
  const txt = cs.getPropertyValue("--secondary-text-color").trim() || "#999";
  const grid = "rgba(128,128,128,0.2)";
  const digits = opts.digits ?? 2;
  const axis = (extra = {}) => ({ stroke: txt, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 }, ...extra });
  return new lib.uPlot(
    {
      width: Math.max(host.clientWidth, 240),
      height: opts.height ?? 200,
      title,
      scales: { x: { time: opts.time !== false } },
      cursor: { drag: { x: true, y: false } },
      series: [
        opts.time === false ? { label: "Day", value: (u, v) => (v == null ? "--" : v.toFixed(1)) } : {},
        ...series.map((s) => ({
          label: s.label,
          stroke: s.color,
          width: s.width ?? 2,
          dash: s.dash,
          spanGaps: true,
          points: { show: false },
          value: (u, v) => (v == null ? "--" : v.toFixed(digits)),
        })),
      ],
      axes: [axis(), axis({ size: 60, values: (u, vals) => vals.map((v) => (v == null ? "" : v.toFixed(digits))) })],
    },
    data,
    host
  );
}
