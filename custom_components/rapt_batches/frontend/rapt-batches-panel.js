// RAPT Batches: "Brewing" sidebar panel. Plain web component, no build step.
// Charts use the bundled uPlot (MIT) from this folder, so nothing is loaded from the internet.

import { MULTI_CSS, createMultiChart } from "./rapt-multichart.js";

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
.name{font-weight:500}
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
tr.row{cursor:pointer}
.src{display:block;width:100%;text-align:left;margin:0 0 8px;border-radius:12px;padding:10px 14px}
.src span{color:var(--secondary-text-color);font-size:12px}
.dialog label{margin-bottom:12px}
.dialog label input{margin-bottom:0}
.errtext{color:var(--error-color,#db4437);margin:0 0 12px}
.dialog input[type=file]{padding:10px}
.overlay{position:fixed;inset:0;z-index:10;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;padding:16px}
.dialog{background:var(--card-background-color);color:var(--primary-text-color);border-radius:16px;padding:20px 24px;max-width:420px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,.4)}
.dialog h3{margin:0 0 8px;font-size:18px;font-weight:500}
.dialog p{margin:0 0 16px;color:var(--secondary-text-color);line-height:1.4}
.dialog input{width:100%;margin-bottom:16px}
.dialog .btns{display:flex;justify-content:flex-end;gap:8px}
.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:11;padding:10px 20px;border-radius:24px;background:#323232;color:#fff;box-shadow:0 4px 16px rgba(0,0,0,.4);max-width:90%}
.toast.err{background:var(--error-color,#db4437)}
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
    try {
      this._layout = localStorage.getItem("rapt_batches_layout") || "combined";
    } catch (e) {
      this._layout = "combined";
    }
    this._mcState = null;
    this._modal = null;
    this._imp = null;
    this._toastMsg = null;
    this._title = "Brewing Library";
    this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
    this.shadowRoot.addEventListener("change", (e) => this._onChange(e));
    this.shadowRoot.addEventListener("input", (e) => {
      const t = e.target;
      if (this._imp && t.dataset && t.dataset.imp) this._imp[t.dataset.imp] = t.value;
    });
    this.shadowRoot.addEventListener("keydown", (e) => {
      if (!this._modal) return;
      if (e.key === "Enter") this._closeModal(true);
      else if (e.key === "Escape") this._closeModal(false);
    });
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
  set panel(p) {
    const title = (p && p.config && p.config.title) || "Brewing Library";
    if (title !== this._title) {
      this._title = title;
      if (this._ready) this._render();
    }
  }
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
    if (this._modal || this._imp) return;
    if (this._view === "list") this._refresh();
    else if (this._view === "detail" && this._current()?.status === "active" && !this._editing()) {
      this._refresh().then(() => this._openDetail(this._detailId));
    }
  }

  _editing() {
    if (this._modal || this._imp) return true;
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
    if (t.id === "imp-file") {
      this._impFile(t.files && t.files[0]);
      return;
    }
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
    if (e.target.closest(".selcell")) return; // ticking a checkbox must not open the row
    const act = t.dataset.act;
    if (act === "modal-bg") {
      if (e.target === t) this._closeModal(false);
      return;
    }
    if (act === "modal-ok") return this._closeModal(true);
    if (act === "modal-cancel") return this._closeModal(false);
    if (act === "imp-bg") {
      if (e.target === t) {
        this._imp = null;
        this._render();
      }
      return;
    }
    if (act === "imp-cancel") {
      this._imp = null;
      this._render();
      return;
    }
    if (act === "imp-back") {
      this._imp.step = this._imp.step === 3 ? 2 : 1;
      this._imp.error = null;
      this._render();
      return;
    }
    if (act === "imp-source") {
      const src = this._imp.sources.find((x) => x.id === t.dataset.id);
      Object.assign(this._imp, { step: 2, source: src, error: null, busy: false });
      this._render();
      return;
    }
    if (act === "imp-go") return this._impGo();
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
        const b = this._current();
        const r = await this._ask({
          title: "Finish batch",
          body: `Stop recording ${b.name}. Enter the final gravity you measured, or leave it blank to use the latest reading (${fmt(b.latest.sg)}).`,
          input: { label: "Final gravity", type: "number", step: "0.001", placeholder: fmt(b.latest.sg) },
          confirm: "Finish batch",
        });
        if (!r.ok) return;
        const v = (r.value || "").trim();
        const fg = v === "" ? null : parseFloat(v);
        if (fg !== null && Number.isNaN(fg)) return this._toast("That is not a valid gravity.", "err");
        await this._action(id, "finish", { fg }, "Batch finished");
        break;
      }
      case "reopen":
        await this._action(id, "reopen", {}, "Batch reopened. Recording has resumed.");
        break;
      case "archive": {
        const r = await this._ask({
          title: "Archive batch",
          body: "It moves off the integration page and stays in this library. You can unarchive it any time.",
          confirm: "Archive",
        });
        if (r.ok) await this._action(id, "archive", {}, "Batch archived");
        break;
      }
      case "unarchive":
        await this._action(id, "unarchive", {}, "Batch moved back to Finished");
        break;
      case "delete": {
        const r = await this._ask({
          title: "Delete batch",
          body: "This permanently deletes the batch and all of its readings. It cannot be undone.",
          confirm: "Delete",
          danger: true,
        });
        if (r.ok && (await this._action(id, "delete", {}, "Batch deleted"))) this._view = "list";
        break;
      }
      case "save":
        await this._save(t);
        break;
      case "export":
        await this._export(id);
        break;
      case "import":
        await this._impOpen();
        break;
      case "layout":
        this._layout = t.dataset.v;
        try {
          localStorage.setItem("rapt_batches_layout", this._layout);
        } catch (e) {
          /* not remembered */
        }
        this._render();
        break;
    }
  }

  async _action(id, action, extra = {}, okMsg = "Done") {
    try {
      await this._ws({ type: "rapt_batches/action", batch_id: id, action, ...extra });
    } catch (e) {
      this._toast((e && e.message) || "That did not work.", "err");
      return false;
    }
    this._toast(okMsg);
    await this._retryRefresh();
    return true;
  }

  async _save(btn) {
    const q = (s) => this.shadowRoot.querySelector(s);
    const num = (el) => (el && el.value.trim() !== "" ? parseFloat(el.value) : null);
    const msg = { type: "rapt_batches/update", batch_id: this._detailId, name: q("#f-name").value.trim(), notes: q("#f-notes").value };
    const og = num(q("#f-og"));
    const fg = num(q("#f-fg"));
    if (og !== null) msg.og = og;
    if (fg !== null && !q("#f-fg").disabled) msg.fg = fg;
    btn.disabled = true;
    btn.textContent = "Saving...";
    try {
      await this._ws(msg);
    } catch (e) {
      this._toast((e && e.message) || "Could not save.", "err");
      btn.disabled = false;
      btn.textContent = "Save details";
      return;
    }
    this._toast("Details saved");
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
      this._toast("Export downloaded");
    } catch (e) {
      this._toast((e && e.message) || "Export failed.", "err");
    }
  }

  // ---- import ------------------------------------------------------------

  async _impOpen() {
    try {
      const r = await this._ws({ type: "rapt_batches/import_sources" });
      this._imp = { step: 1, sources: r.sources, error: null };
    } catch (e) {
      return this._toast((e && e.message) || "Could not start the import.", "err");
    }
    this._render();
  }

  async _impFile(file) {
    const m = this._imp;
    if (!m || !file) return;
    m.busy = true;
    m.error = null;
    this._render();
    try {
      const text = await file.text();
      const p = await this._ws({ type: "rapt_batches/import_preview", source: m.source.id, text });
      Object.assign(m, { text, preview: p, name: file.name.replace(/\.[^.]+$/, ""), og: p.og_guess, fg: p.fg_guess, step: 3 });
    } catch (e) {
      m.error = (e && e.message) || "Could not read that file.";
    }
    m.busy = false;
    this._render();
  }

  async _impGo() {
    const m = this._imp;
    const name = String(m.name ?? "").trim();
    const og = parseFloat(m.og);
    const fg = m.fg === "" || m.fg == null ? null : parseFloat(m.fg);
    const fail = (msg) => {
      m.error = msg;
      this._render();
    };
    if (!name) return fail("Give the batch a name.");
    if (Number.isNaN(og)) return fail("Enter the original gravity.");
    if (fg !== null && Number.isNaN(fg)) return fail("Final gravity is not a number.");
    m.busy = true;
    m.error = null;
    this._render();
    try {
      const r = await this._ws({ type: "rapt_batches/import", source: m.source.id, text: m.text, name, og, fg });
      this._imp = null;
      this._toast("Batch imported. It is in the Archived list.");
      await this._refresh();
      await this._openDetail(r.id);
    } catch (e) {
      m.busy = false;
      fail((e && e.message) || "Import failed.");
    }
  }

  _importHtml() {
    const m = this._imp;
    if (!m) return "";
    const err = m.error ? `<p class="errtext">${esc(m.error)}</p>` : "";
    let inner;
    if (m.step === 1) {
      inner = `<h3>Import a batch</h3><p>Where is the data from?</p>` +
        m.sources.map((x) => `<button class="src" data-act="imp-source" data-id="${esc(x.id)}"><b>${esc(x.label)}</b><br><span>${esc(x.description)}</span></button>`).join("") +
        err + `<div class="btns"><button data-act="imp-cancel">Cancel</button></div>`;
    } else if (m.step === 2) {
      inner = `<h3>${esc(m.source.label)}</h3><p>${esc(m.source.help)}</p>` +
        `<input type="file" id="imp-file" accept="${esc(m.source.accept)}" ${m.busy ? "disabled" : ""}>` +
        (m.busy ? `<p>Reading file...</p>` : "") + err +
        `<div class="btns"><button data-act="imp-back">Back</button><button data-act="imp-cancel">Cancel</button></div>`;
    } else {
      const p = m.preview;
      inner = `<h3>Import ${esc(m.source.label)}</h3>` +
        `<p>${p.readings} readings from ${fmtDate(p.start_ts)} to ${fmtDate(p.end_ts)}.</p>` +
        (p.dropped + p.trimmed ? `<p style="font-size:13px">${p.dropped + p.trimmed} readings were left out because they look wrong. This is usually the Pill being out of the fermenter at the end of a batch.</p>` : "") +
        (p.skipped ? `<p style="font-size:13px">${p.skipped} rows could not be read and were skipped.</p>` : "") +
        `<label>Batch name<input data-imp="name" value="${esc(m.name)}"></label>` +
        `<label>Original gravity<input data-imp="og" type="number" step="0.001" value="${esc(m.og)}"></label>` +
        `<label>Final gravity<input data-imp="fg" type="number" step="0.001" value="${esc(m.fg)}"></label>` +
        `<p style="font-size:12px">Suggested OG is the highest reading in the first day and FG the median of the last 12 hours. Change them if you measured different values.</p>` +
        err + `<div class="btns"><button data-act="imp-back" ${m.busy ? "disabled" : ""}>Back</button>` +
        `<button class="primary" data-act="imp-go" ${m.busy ? "disabled" : ""}>${m.busy ? "Importing..." : "Import"}</button></div>`;
    }
    return `<div class="overlay" data-act="imp-bg"><div class="dialog" role="dialog">${inner}</div></div>`;
  }

  // ---- dialogs and toasts ----------------------------------------------

  _ask(opts) {
    return new Promise((resolve) => {
      this._modal = { ...opts, resolve };
      this._render();
    });
  }

  _closeModal(ok) {
    const m = this._modal;
    if (!m) return;
    const el = this.shadowRoot.getElementById("m-input");
    const value = el ? el.value : "";
    this._modal = null;
    this._render();
    m.resolve({ ok, value });
  }

  _modalHtml() {
    const m = this._modal;
    if (!m) return "";
    const i = m.input;
    return `<div class="overlay" data-act="modal-bg"><div class="dialog" role="dialog">` +
      `<h3>${esc(m.title)}</h3><p>${esc(m.body)}</p>` +
      (i ? `<input id="m-input" type="${i.type || "text"}" step="${i.step || ""}" placeholder="${esc(i.placeholder || "")}" aria-label="${esc(i.label || "")}">` : "") +
      `<div class="btns"><button data-act="modal-cancel">Cancel</button>` +
      `<button class="${m.danger ? "danger" : "primary"}" data-act="modal-ok">${esc(m.confirm || "OK")}</button></div></div></div>`;
  }

  _toast(msg, kind = "ok") {
    this._toastMsg = { msg, kind };
    this._showToast();
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      this._toastMsg = null;
      this._showToast();
    }, 3000);
  }

  _showToast() {
    const old = this.shadowRoot.querySelector(".toast");
    if (old) old.remove();
    if (!this._toastMsg) return;
    const d = document.createElement("div");
    d.className = "toast" + (this._toastMsg.kind === "err" ? " err" : "");
    d.textContent = this._toastMsg.msg;
    this.shadowRoot.appendChild(d);
  }

  // ---- rendering ------------------------------------------------------

  _destroyCharts() {
    this._charts.forEach((c) => {
      // Keep the chart's toggles and zoom so a refresh does not undo them.
      if (c.getState) this._mcState = { id: c.batchId, ...c.getState() };
      c.destroy();
    });
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
      `<style>${STYLE}${MULTI_CSS}${this._lib ? this._lib.css : ""}</style>` +
      `<div class="bar">${this._narrow ? '<button class="icon" data-act="menu" title="Menu">&#9776;</button>' : ""}` +
      `<h1>${esc(this._title)}</h1>` +
      (showBack ? '<button data-act="back">&larr; Batches</button>' : '<button data-act="new">New batch</button>') +
      `</div><div class="wrap">${this._error ? `<div class="err">${esc(this._error)}</div>` : ""}${body}</div>${this._modalHtml()}${this._importHtml()}`;
    this.scrollTop = top;
    this._showToast();
    if (this._modal) {
      const inp = this.shadowRoot.getElementById("m-input");
      if (inp) inp.focus();
    }
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
            return `<tr class="row" data-act="open" data-id="${esc(b.id)}"><td class="selcell"><input type="checkbox" class="sel" data-id="${esc(b.id)}" ${this._selected.has(b.id) ? "checked" : ""}></td>` +
              `<td><span class="name">${esc(b.name)}</span></td>` +
              `<td><span class="badge s-${b.status}">${LABEL[b.status] || b.status}</span></td>` +
              `<td>${fmtDate(b.start_ts)}</td><td>${fmt(daysOf(b), 1)}</td><td>${fmt(b.og)}</td><td>${fmt(g)}</td>` +
              `<td>${fmt(abv(b.og, g), 1)}${abv(b.og, g) == null ? "" : "%"}</td></tr>`;
          })
          .join("") +
        "</tbody></table></div>"
      : `<div class="empty">No batches here yet. Use <b>New batch</b> to start one.</div>`;
    return `<div class="chips">${chip("all", "All")}${chip("active", "Active")}${chip("completed", "Finished")}${chip("archived", "Archived")}<span class="grow"></span>` +
      (n ? `<button data-act="clear">Clear</button>` : "") + `<button data-act="import">Import</button>` +
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
      completed: `${b.can_record === false ? "" : '<button data-act="reopen">Reopen</button>'}<button class="primary" data-act="archive">Archive</button>`,
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
      `<div class="chips"><button class="chip ${this._layout === "combined" ? "on" : ""}" data-act="layout" data-v="combined">Combined chart</button>` +
      `<button class="chip ${this._layout === "combined" ? "" : "on"}" data-act="layout" data-v="separate">Separate charts</button></div>` +
      (this._layout === "combined"
        ? `<div class="card"><div id="c-multi"></div></div>`
        : `<div class="charts"><div class="card"><div id="c-sg"></div></div><div class="card"><div id="c-abv"></div></div>` +
          `<div class="card"><div id="c-temp"></div></div><div class="card"><div id="c-vel"></div></div>` +
          `<div class="card"><div id="c-bat"></div></div></div>`);
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
    if (this._layout === "combined") {
      const host = this.shadowRoot.getElementById("c-multi");
      if (host && this._lib) {
        const prev = this._mcState && this._mcState.id === this._detailId ? this._mcState : null;
        const mc = createMultiChart(this._lib, host, {
          series: S,
          og: b.og,
          height: 320,
          storageKey: "rapt_batches_chart",
          state: prev ? { enabled: prev.enabled, zoom: prev.zoom } : null,
        });
        mc.batchId = this._detailId;
        this._charts.push(mc);
      }
      return;
    }
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
