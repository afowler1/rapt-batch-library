// RAPT Batches: "Brewing" sidebar panel. Plain web component, no build step.
// Charts use the bundled uPlot (MIT) from this folder, so nothing is loaded from the internet.

const BASE = new URL("./", import.meta.url).href;
const ABV_FACTOR = 131.25;
const PALETTE = ["#f2b544", "#4fc3f7", "#4caf7d", "#e0763f", "#b57edc", "#ef5350"];
const COLORS = { sg: "#f2b544", og: "#e0763f", abv: "#4caf7d", temp: "#4fc3f7", battery: "#9e9e9e", velocity: "#b57edc" };
const LABEL = { active: "Active", completed: "Finished", archived: "Archived" };

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 3) => (v == null || Number.isNaN(v) ? "--" : Number(v).toFixed(d));
const fmtDate = (ts) =>
  ts ? new Date(ts * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "--";
const abv = (og, sg) => (og == null || sg == null ? null : Math.max(0, (og - sg) * ABV_FACTOR));
const daysOf = (b) => ((b.status !== "active" && b.end_ts ? b.end_ts : Date.now() / 1000) - b.start_ts) / 86400;
const gravityOf = (b) => (b.status === "active" ? b.latest.sg : b.fg ?? b.latest.sg);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let _libPromise;
function loadLib() {
  if (!_libPromise) {
    _libPromise = (async () => {
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
  return _libPromise;
}

const STYLE = `
:host{display:block;height:100%;overflow:auto;box-sizing:border-box;background:var(--primary-background-color);color:var(--primary-text-color);font-family:var(--paper-font-body1_-_font-family,Roboto,sans-serif)}
*{box-sizing:border-box}
.bar{position:sticky;top:0;z-index:3;display:flex;align-items:center;gap:12px;padding:0 16px;height:56px;background:var(--app-header-background-color,var(--primary-color));color:var(--app-header-text-color,#fff)}
.bar h1{font-size:20px;font-weight:400;margin:0;flex:1}
.wrap{max-width:1200px;margin:0 auto;padding:16px 16px 56px}
button,.btn{font:inherit;cursor:pointer;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);border-radius:18px;padding:6px 14px}
button:hover{border-color:var(--primary-color)}
button.primary{background:var(--primary-color);border-color:var(--primary-color);color:var(--text-primary-color,#fff)}
button.danger{color:var(--error-color,#db4437);border-color:var(--error-color,#db4437)}
button.icon{border:none;background:none;color:inherit;font-size:22px;padding:4px 8px}
button:disabled{opacity:.4;cursor:default}
.chips{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
.chip.on{background:var(--primary-color);border-color:var(--primary-color);color:var(--text-primary-color,#fff)}
.grow{flex:1}
.card{background:var(--card-background-color);border-radius:var(--ha-card-border-radius,12px);border:1px solid var(--divider-color);padding:12px 16px;margin-bottom:16px}
.card h3{margin:0 0 8px;font-size:16px;font-weight:500}
.tablewrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:640px}
th,td{padding:10px 8px;text-align:left;border-bottom:1px solid var(--divider-color);white-space:nowrap}
th{cursor:pointer;font-weight:500;color:var(--secondary-text-color);user-select:none}
tr.row:hover td{background:var(--secondary-background-color)}
.name{cursor:pointer;font-weight:500;color:var(--primary-text-color);background:none;border:none;padding:0;border-radius:0;text-align:left}
.badge{display:inline-block;padding:2px 10px;border-radius:10px;font-size:12px;color:#fff}
.s-active{background:#4caf7d}.s-completed{background:#e0a458}.s-archived{background:#7a7f8c}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:16px}
.stat{background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:12px;padding:10px 12px}
.stat b{display:block;font-size:22px;font-weight:500}
.stat span{font-size:12px;color:var(--secondary-text-color)}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}
.form{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--secondary-text-color)}
input,textarea{font:inherit;color:var(--primary-text-color);background:var(--secondary-background-color);border:1px solid var(--divider-color);border-radius:8px;padding:8px}
textarea{width:100%;min-height:80px;resize:vertical;margin-top:12px}
.empty,.err{padding:24px;text-align:center;color:var(--secondary-text-color)}
.err{color:var(--error-color,#db4437)}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:16px}
.charts .card{margin:0;padding:8px;overflow:hidden}
.u-title{color:var(--primary-text-color);font-size:14px!important}
.u-legend{color:var(--secondary-text-color);font-size:12px}
@media(max-width:600px){.charts{grid-template-columns:1fr}.wrap{padding:12px 8px 56px}}
`;

class RaptBatchesPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._view = "list";
    this._filter = "all";
    this._sort = { key: "start_ts", dir: -1 };
    this._batches = [];
    this._selected = new Set();
    this._charts = [];
    this._detailId = null;
    this._series = {};
    this._lib = null;
    this._ready = false;
    this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
    this.shadowRoot.addEventListener("change", (e) => this._onChange(e));
  }

  connectedCallback() {
    this._onResize = () => this._resize();
    window.addEventListener("resize", this._onResize);
    this._timer = setInterval(() => this._tick(), 60000);
  }
  disconnectedCallback() {
    window.removeEventListener("resize", this._onResize);
    clearInterval(this._timer);
    this._destroyCharts();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._boot();
  }
  set narrow(v) {
    const changed = v !== this._narrow;
    this._narrow = v;
    if (changed && this._ready) this._render();
  }
  set panel(_) {}
  set route(_) {}

  // ---- data -----------------------------------------------------------

  _ws(msg) {
    return this._hass.callWS(msg);
  }

  async _boot() {
    try {
      this._lib = await loadLib();
    } catch (e) {
      this._error = "Could not load the chart library.";
    }
    await this._refresh();
  }

  async _refresh() {
    try {
      this._batches = (await this._ws({ type: "rapt_batches/list" })).batches;
      this._error = null;
    } catch (e) {
      this._error = (e && e.message) || "Could not load batches.";
    }
    this._ready = true;
    this._render();
  }

  async _retryRefresh() {
    // Finishing, reopening or archiving reloads the integration, so wait briefly.
    for (let i = 0; i < 6; i++) {
      await sleep(1200);
      try {
        this._batches = (await this._ws({ type: "rapt_batches/list" })).batches;
        this._error = null;
        break;
      } catch (e) {
        this._error = null;
      }
    }
    if (this._view === "detail") {
      if (this._current()) await this._openDetail(this._detailId);
      else this._go("list");
    } else this._render();
  }

  _tick() {
    if (this._view === "list") this._refresh();
    else if (this._view === "detail" && this._current()?.status === "active" && !this._editing()) {
      this._refresh().then(() => this._openDetail(this._detailId));
    }
  }

  _editing() {
    const a = this.shadowRoot.activeElement;
    return a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA");
  }

  _current() {
    return this._batches.find((b) => b.id === this._detailId);
  }

  _go(view) {
    this._view = view;
    this._render();
  }

  async _openDetail(id) {
    this._detailId = id;
    try {
      this._series = (await this._ws({ type: "rapt_batches/readings", batch_id: id, max_points: 1500 })).series;
    } catch (e) {
      this._series = {};
      this._error = (e && e.message) || "Could not load readings.";
    }
    this._view = "detail";
    this._render();
  }

  // ---- events ---------------------------------------------------------

  _onChange(e) {
    const t = e.target;
    if (t.classList && t.classList.contains("sel")) {
      if (t.checked) this._selected.add(t.dataset.id);
      else this._selected.delete(t.dataset.id);
      const top = this.scrollTop;
      this._render();
      this.scrollTop = top;
    }
  }

  async _onClick(e) {
    const t = e.target.closest("[data-act]");
    if (!t) return;
    const act = t.dataset.act;
    const id = t.dataset.id || this._detailId;
    switch (act) {
      case "menu":
        this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
        break;
      case "new":
        history.pushState(null, "", "/config/integrations/integration/rapt_batches");
        window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
        break;
      case "filter":
        this._filter = t.dataset.v;
        this._render();
        break;
      case "sort":
        this._sort = { key: t.dataset.k, dir: this._sort.key === t.dataset.k ? -this._sort.dir : 1 };
        this._render();
        break;
      case "open":
        await this._openDetail(id);
        break;
      case "back":
        this._go("list");
        this._refresh();
        break;
      case "compare":
        this._view = "compare";
        this._render();
        break;
      case "clear":
        this._selected.clear();
        this._render();
        break;
      case "finish": {
        const v = prompt("Final gravity (leave blank to use the latest reading)", "");
        if (v === null) return;
        const fg = v.trim() === "" ? null : parseFloat(v);
        if (fg !== null && Number.isNaN(fg)) return alert("That is not a number.");
        await this._action(id, "finish", { fg });
        break;
      }
      case "reopen":
        await this._action(id, "reopen");
        break;
      case "archive":
        if (confirm("Archive this batch? It moves off the integration page and stays here in the panel.")) {
          await this._action(id, "archive");
        }
        break;
      case "unarchive":
        await this._action(id, "unarchive");
        break;
      case "delete":
        if (confirm("Permanently delete this batch and all its readings? This cannot be undone.")) {
          await this._action(id, "delete");
          this._view = "list";
        }
        break;
      case "save":
        await this._save();
        break;
      case "export":
        await this._export(id);
        break;
    }
  }

  async _action(id, action, extra = {}) {
    try {
      await this._ws({ type: "rapt_batches/action", batch_id: id, action, ...extra });
    } catch (e) {
      return alert((e && e.message) || "That did not work.");
    }
    await this._retryRefresh();
  }

  async _save() {
    const q = (s) => this.shadowRoot.querySelector(s);
    const num = (el) => (el && el.value.trim() !== "" ? parseFloat(el.value) : null);
    const msg = { type: "rapt_batches/update", batch_id: this._detailId, name: q("#f-name").value.trim(), notes: q("#f-notes").value };
    const og = num(q("#f-og"));
    const fg = num(q("#f-fg"));
    if (og !== null) msg.og = og;
    if (fg !== null && !q("#f-fg").disabled) msg.fg = fg;
    try {
      await this._ws(msg);
    } catch (e) {
      return alert((e && e.message) || "Could not save.");
    }
    await this._retryRefresh();
  }

  async _export(id) {
    try {
      const r = await this._ws({ type: "rapt_batches/export", batch_id: id });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([r.csv], { type: "text/csv" }));
      a.download = r.filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (e) {
      alert((e && e.message) || "Export failed.");
    }
  }

  // ---- rendering ------------------------------------------------------

  _destroyCharts() {
    this._charts.forEach((c) => c.destroy());
    this._charts = [];
  }

  _resize() {
    this._charts.forEach((c) => {
      const w = c.root.parentElement ? c.root.parentElement.clientWidth : 0;
      if (w > 0) c.setSize({ width: w, height: 220 });
    });
  }

  _render() {
    this._destroyCharts();
    const top = this.scrollTop;
    let body = "";
    if (this._view === "detail" && this._current()) body = this._detailHtml(this._current());
    else if (this._view === "compare") body = this._compareHtml();
    else {
      this._view = "list";
      body = this._listHtml();
    }
    const showBack = this._view !== "list";
    this.shadowRoot.innerHTML =
      `<style>${STYLE}${this._lib ? this._lib.css : ""}</style>` +
      `<div class="bar">${this._narrow ? '<button class="icon" data-act="menu" title="Menu">&#9776;</button>' : ""}` +
      `<h1>Brewing</h1>` +
      (showBack ? '<button data-act="back">&larr; Batches</button>' : '<button data-act="new">New batch</button>') +
      `</div><div class="wrap">${this._error ? `<div class="err">${esc(this._error)}</div>` : ""}${body}</div>`;
    this.scrollTop = top;
    if (this._view === "detail" && this._current()) this._drawDetail();
    else if (this._view === "compare") this._drawCompare();
  }

  _listHtml() {
    const f = this._filter;
    const rows = this._batches
      .filter((b) => f === "all" || b.status === f)
      .sort((a, b) => {
        const k = this._sort.key;
        const va = k === "days" ? daysOf(a) : k === "abv" ? abv(a.og, gravityOf(a)) ?? -1 : a[k] ?? "";
        const vb = k === "days" ? daysOf(b) : k === "abv" ? abv(b.og, gravityOf(b)) ?? -1 : b[k] ?? "";
        return (va > vb ? 1 : va < vb ? -1 : 0) * this._sort.dir;
      });
    const counts = { all: this._batches.length };
    this._batches.forEach((b) => (counts[b.status] = (counts[b.status] || 0) + 1));
    const chip = (v, label) =>
      `<button class="chip ${f === v ? "on" : ""}" data-act="filter" data-v="${v}">${label} (${counts[v] || 0})</button>`;
    const th = (k, label) => `<th data-act="sort" data-k="${k}">${label}${this._sort.key === k ? (this._sort.dir > 0 ? " &uarr;" : " &darr;") : ""}</th>`;
    const n = this._selected.size;
    const table = rows.length
      ? `<div class="tablewrap"><table><thead><tr><th></th>${th("name", "Batch")}${th("status", "Status")}${th("start_ts", "Started")}${th("days", "Days")}${th("og", "OG")}<th>FG / now</th>${th("abv", "ABV")}</tr></thead><tbody>` +
        rows
          .map((b) => {
            const g = gravityOf(b);
            return `<tr class="row"><td><input type="checkbox" class="sel" data-id="${esc(b.id)}" ${this._selected.has(b.id) ? "checked" : ""}></td>` +
              `<td><button class="name" data-act="open" data-id="${esc(b.id)}">${esc(b.name)}</button></td>` +
              `<td><span class="badge s-${b.status}">${LABEL[b.status] || b.status}</span></td>` +
              `<td>${fmtDate(b.start_ts)}</td><td>${fmt(daysOf(b), 1)}</td><td>${fmt(b.og)}</td><td>${fmt(g)}</td>` +
              `<td>${fmt(abv(b.og, g), 1)}${abv(b.og, g) == null ? "" : "%"}</td></tr>`;
          })
          .join("") +
        "</tbody></table></div>"
      : `<div class="empty">No batches here yet. Use <b>New batch</b> to start one.</div>`;
    return `<div class="chips">${chip("all", "All")}${chip("active", "Active")}${chip("completed", "Finished")}${chip("archived", "Archived")}<span class="grow"></span>` +
      (n ? `<button data-act="clear">Clear</button>` : "") +
      `<button class="primary" data-act="compare" ${n < 2 ? "disabled" : ""}>Compare${n ? ` (${n})` : ""}</button></div>` +
      `<div class="card">${table}</div>`;
  }

  _detailHtml(b) {
    const g = gravityOf(b);
    const a = abv(b.og, g);
    const att = b.og > 1 && g != null ? ((b.og - g) / (b.og - 1)) * 100 : null;
    const s = (label, val) => `<div class="stat"><b>${val}</b><span>${label}</span></div>`;
    const btns = {
      active: `<button class="primary" data-act="finish">Finish batch</button>`,
      completed: `<button data-act="reopen">Reopen</button><button class="primary" data-act="archive">Archive</button>`,
      archived: `<button class="primary" data-act="unarchive">Unarchive</button><button class="danger" data-act="delete">Delete</button>`,
    }[b.status];
    return `<div class="chips"><h2 style="margin:0">${esc(b.name)}</h2><span class="badge s-${b.status}">${LABEL[b.status]}</span></div>` +
      `<div class="stats">${s("Original gravity", fmt(b.og))}${s(b.status === "active" ? "Gravity now" : "Final gravity", fmt(g))}` +
      `${s("ABV", a == null ? "--" : a.toFixed(1) + "%")}${s("Attenuation", att == null ? "--" : att.toFixed(0) + "%")}` +
      `${s("Days", fmt(daysOf(b), 1))}${s("Started", fmtDate(b.start_ts))}${s("Temperature", b.latest.temp == null ? "--" : fmt(b.latest.temp, 1) + "°")}` +
      `${s("Battery", b.latest.battery == null ? "--" : fmt(b.latest.battery, 0) + "%")}</div>` +
      `<div class="actions">${btns}<button data-act="export">Export CSV</button></div>` +
      `<div class="card"><h3>Details</h3><div class="form">` +
      `<label>Name<input id="f-name" value="${esc(b.name)}"></label>` +
      `<label>Original gravity<input id="f-og" type="number" step="0.001" value="${b.og ?? ""}"></label>` +
      `<label>Final gravity<input id="f-fg" type="number" step="0.001" value="${b.fg ?? ""}" ${b.status === "active" ? "disabled" : ""}></label></div>` +
      `<textarea id="f-notes" placeholder="Notes: recipe, yeast, tasting...">${esc(b.notes || "")}</textarea>` +
      `<div class="actions" style="margin:12px 0 0"><button class="primary" data-act="save">Save details</button></div></div>` +
      `<div class="charts"><div class="card"><div id="c-sg"></div></div><div class="card"><div id="c-abv"></div></div>` +
      `<div class="card"><div id="c-temp"></div></div><div class="card"><div id="c-vel"></div></div>` +
      `<div class="card"><div id="c-bat"></div></div></div>`;
  }

  _compareHtml() {
    return `<div class="chips"><h2 style="margin:0">Compare batches</h2></div>` +
      `<div class="charts"><div class="card"><div id="c-sg"></div></div><div class="card"><div id="c-abv"></div></div>` +
      `<div class="card"><div id="c-temp"></div></div></div>`;
  }

  // ---- charts ---------------------------------------------------------

  _chart(id, title, data, series, opts = {}) {
    const host = this.shadowRoot.getElementById(id);
    if (!host) return;
    if (!this._lib || !data[0] || !data[0].length) {
      host.innerHTML = `<div class="empty">No ${esc(title)} data yet</div>`;
      return;
    }
    const cs = getComputedStyle(this);
    const txt = cs.getPropertyValue("--secondary-text-color").trim() || "#999";
    const grid = "rgba(128,128,128,0.2)";
    const digits = opts.digits ?? 2;
    const time = opts.time !== false;
    const xSeries = time ? {} : { label: "Day", value: (u, v) => (v == null ? "--" : v.toFixed(1)) };
    const axis = (extra = {}) => ({ stroke: txt, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 }, ...extra });
    const u = new this._lib.uPlot(
      {
        width: Math.max(host.clientWidth, 280),
        height: 220,
        title,
        scales: { x: { time } },
        cursor: { drag: { x: true, y: false } },
        series: [
          xSeries,
          ...series.map((s) => ({
            label: s.label,
            stroke: s.color,
            width: s.width ?? 2,
            dash: s.dash,
            spanGaps: true,
            points: { show: false },
            value: (u2, v) => (v == null ? "--" : v.toFixed(digits)),
          })),
        ],
        axes: [axis(), axis({ size: 64, values: (u2, vals) => vals.map((v) => (v == null ? "" : v.toFixed(digits))) })],
      },
      data,
      host
    );
    this._charts.push(u);
  }

  _drawDetail() {
    const b = this._current();
    const S = this._series;
    const sg = S.sg;
    this._chart("c-sg", "Specific gravity", sg ? [sg.t, sg.v, sg.t.map(() => b.og)] : [[]], [
      { label: "SG", color: COLORS.sg, width: 3 },
      { label: "OG", color: COLORS.og, width: 1, dash: [6, 4] },
    ], { digits: 3 });
    this._chart("c-abv", "ABV %", sg ? [sg.t, sg.v.map((v) => abv(b.og, v))] : [[]], [{ label: "ABV", color: COLORS.abv, width: 3 }]);
    const one = (id, title, key, color, digits) =>
      this._chart(id, title, S[key] ? [S[key].t, S[key].v] : [[]], [{ label: title, color }], { digits });
    one("c-temp", "Temperature", "temp", COLORS.temp, 1);
    one("c-vel", "Gravity velocity", "velocity", COLORS.velocity, 3);
    one("c-bat", "Battery %", "battery", COLORS.battery, 0);
  }

  async _drawCompare() {
    const ids = [...this._selected].slice(0, 6);
    let results;
    try {
      results = await Promise.all(ids.map((id) => this._ws({ type: "rapt_batches/readings", batch_id: id, max_points: 800 })));
    } catch (e) {
      this._error = (e && e.message) || "Could not load readings.";
      return;
    }
    const batches = ids.map((id) => this._batches.find((b) => b.id === id));
    const build = (id, title, pick, digits) => {
      const items = [];
      results.forEach((r, i) => {
        const b = batches[i];
        const s = r.series[pick.key];
        if (b && s && s.t.length) {
          items.push({ label: b.name, color: PALETTE[i % PALETTE.length], x: s.t.map((t) => (t - b.start_ts) / 86400), y: pick.map ? s.v.map((v) => pick.map(b, v)) : s.v });
        }
      });
      if (!items.length) return this._chart(id, title, [[]], []);
      const data = this._lib.uPlot.join(items.map((it) => [it.x, it.y]));
      this._chart(id, title, data, items.map((it) => ({ label: it.label, color: it.color })), { time: false, digits });
    };
    build("c-sg", "Specific gravity", { key: "sg" }, 3);
    build("c-abv", "ABV %", { key: "sg", map: (b, v) => abv(b.og, v) }, 2);
    build("c-temp", "Temperature", { key: "temp" }, 1);
  }
}

customElements.define("rapt-batches-panel", RaptBatchesPanel);
