// <rapt-compare-card>: overlay several batches by day since each one started.
import { CARD_STYLE, CHART_LABEL, PALETTE, abv, batchOptions, defineEditor, drawChart, esc, loadLib, pickBatch, registerCard } from "./rapt-card-shared.js";

const KEYS = ["sg", "abv", "temp"];

class RaptCompareCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._charts = [];
    this._cache = {};
  }
  static getConfigElement() {
    return document.createElement("rapt-compare-card-editor");
  }
  static getStubConfig() {
    return { charts: ["sg", "abv"] };
  }
  setConfig(config) {
    this._config = { charts: ["sg", "abv"], title: "Compare batches", ...config };
    this._load(true);
  }
  getCardSize() {
    return 3 + 3 * (this._config ? this._config.charts.length : 2);
  }
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._load();
  }
  connectedCallback() {
    this._timer = setInterval(() => this._load(), 60000);
    if (typeof ResizeObserver !== "undefined") {
      this._ro = new ResizeObserver(() => this._resize());
      this._ro.observe(this);
    }
    this._load();
  }
  disconnectedCallback() {
    clearInterval(this._timer);
    if (this._ro) this._ro.disconnect();
    this._destroy();
  }
  _destroy() {
    this._charts.forEach((c) => c.destroy());
    this._charts = [];
  }
  _resize() {
    this._charts.forEach((c) => {
      const w = c.root.parentElement ? c.root.parentElement.clientWidth : 0;
      if (w > 0) c.setSize({ width: w, height: 200 });
    });
  }

  async _load(force = false) {
    if (!this._hass || !this._config) return;
    if (this._loading) {
      if (force) this._again = true;
      return;
    }
    this._loading = true;
    try {
      this._lib = this._lib || (await loadLib());
      const all = (await this._hass.callWS({ type: "rapt_batches/list" })).batches;
      const wanted = this._config.batches && this._config.batches.length ? this._config.batches : null;
      let picked = wanted
        ? wanted.map((sel) => pickBatch(all, sel)).filter(Boolean)
        : [...all].sort((a, b) => b.start_ts - a.start_ts).slice(0, 2);
      picked = [...new Set(picked)].slice(0, 6);
      for (const b of picked) {
        // Finished batches never change, so fetch their readings once.
        if (b.status === "active" || !this._cache[b.id]) {
          this._cache[b.id] = (await this._hass.callWS({ type: "rapt_batches/readings", batch_id: b.id, max_points: 600 })).series;
        }
      }
      this._picked = picked;
      this._total = all.length;
      this._error = null;
    } catch (e) {
      this._error = (e && e.message) || "Could not load the batches.";
    }
    this._loading = false;
    this._render();
    if (this._again) {
      this._again = false;
      this._load();
    }
  }

  _render() {
    this._destroy();
    const keys = this._config.charts.filter((k) => KEYS.includes(k));
    let body;
    if (this._error) body = `<div class="empty">${esc(this._error)}</div>`;
    else if (!this._picked || this._picked.length < 2)
      body = `<div class="empty">${this._total ? "Choose at least two batches in the card editor." : "No batches to compare yet."}</div>`;
    else body = keys.map((k) => `<div class="chart" id="c-${k}"></div>`).join("");
    this.shadowRoot.innerHTML = `<style>${CARD_STYLE}h2.title{margin:0 0 4px;font-size:18px;font-weight:500}</style>` +
      `<ha-card><h2 class="title">${esc(this._config.title)}</h2>${body}</ha-card>`;
    if (!this._error && this._picked && this._picked.length >= 2) this._draw(keys);
  }

  _draw(keys) {
    const batches = this._picked;
    const digits = { sg: 3, abv: 2, temp: 1 };
    for (const k of keys) {
      const host = this.shadowRoot.getElementById("c-" + k);
      const items = [];
      batches.forEach((b, i) => {
        const s = (this._cache[b.id] || {})[k === "abv" ? "sg" : k];
        if (!s || !s.t.length) return;
        items.push({
          label: b.name,
          color: PALETTE[i % PALETTE.length],
          x: s.t.map((t) => (t - b.start_ts) / 86400),
          y: k === "abv" ? s.v.map((v) => abv(b.og, v)) : s.v,
        });
      });
      if (!items.length) {
        host.innerHTML = `<div class="empty">No ${esc(CHART_LABEL[k])} data yet</div>`;
        continue;
      }
      const data = this._lib.uPlot.join(items.map((it) => [it.x, it.y]));
      const chart = drawChart(this._lib, host, CHART_LABEL[k] + " by day", data, items.map((it) => ({ label: it.label, color: it.color })), { time: false, digits: digits[k] });
      if (chart) this._charts.push(chart);
    }
  }
}

defineEditor(
  "rapt-compare-card-editor",
  { title: "Title", batches: "Batches to compare (2 to 6; empty = the two most recent)", charts: "Charts" },
  (batches) => [
    { name: "title", selector: { text: {} } },
    { name: "batches", selector: { select: { multiple: true, mode: "list", options: batchOptions(batches) } } },
    { name: "charts", selector: { select: { multiple: true, mode: "list", options: KEYS.map((k) => ({ value: k, label: CHART_LABEL[k] })) } } },
  ]
);
customElements.define("rapt-compare-card", RaptCompareCard);
registerCard("rapt-compare-card", "RAPT Compare", "Overlay two or more batches by day to compare how they fermented.");
