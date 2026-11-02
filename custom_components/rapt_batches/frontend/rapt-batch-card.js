// <rapt-batch-card>: one batch's summary and charts on a dashboard.
import { CARD_STYLE, CHART_LABEL, COLORS, LABEL, PANEL_PATH, abv, daysOf, drawChart, esc, fmt, liveValue, loadLib, navigate, pickBatch } from "./rapt-card-shared.js";

const CHART_KEYS = ["sg", "abv", "temp", "velocity", "battery"];

class RaptBatchCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._charts = [];
    this._batches = [];
    this._series = {};
    this._lastStats = "";
    this.shadowRoot.addEventListener("click", (e) => {
      if (e.target.closest("[data-open]")) navigate(PANEL_PATH);
    });
  }

  static getConfigElement() {
    return document.createElement("rapt-batch-card-editor");
  }
  static getStubConfig() {
    return { batch: "active", charts: ["sg", "abv", "temp"] };
  }

  setConfig(config) {
    this._config = { batch: "active", compact: false, charts: ["sg", "abv", "temp"], ...config };
    this._load(true);
  }
  getCardSize() {
    return this._config && this._config.compact ? 3 : 6;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._load();
    else this._updateStats();
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
      if (w > 0) c.setSize({ width: w, height: this._config.compact ? 140 : 200 });
    });
  }

  async _load(force = false) {
    if (!this._hass || !this._config) return;
    if (this._loading) {
      if (force) this._again = true; // the config changed mid-load: run once more after
      return;
    }
    this._loading = true;
    try {
      this._lib = this._lib || (await loadLib());
      this._batches = (await this._hass.callWS({ type: "rapt_batches/list" })).batches;
      this._batch = pickBatch(this._batches, this._config.batch);
      this._series = this._batch
        ? (await this._hass.callWS({ type: "rapt_batches/readings", batch_id: this._batch.id, max_points: 600 })).series
        : {};
      this._error = null;
    } catch (e) {
      this._error = (e && e.message) || "Could not load the batch.";
    }
    this._loading = false;
    this._render();
    if (this._again) {
      this._again = false;
      this._load();
    }
  }

  _statsHtml() {
    const b = this._batch;
    const live = (k) => (b.status === "active" ? liveValue(this._hass, b, k) : b.latest[k]);
    const sg = b.status === "active" ? live("sg") : b.fg ?? b.latest.sg;
    const a = abv(b.og, sg);
    const att = b.og > 1 && sg != null ? ((b.og - sg) / (b.og - 1)) * 100 : null;
    const s = (label, val) => `<div class="stat"><b>${val}</b><span>${label}</span></div>`;
    const items = [
      s("ABV", a == null ? "--" : a.toFixed(1) + "%"),
      s(b.status === "active" ? "Gravity" : "Final gravity", fmt(sg)),
      s("Days", fmt(daysOf(b), 1)),
    ];
    if (!this._config.compact) {
      items.splice(1, 0, s("Original gravity", fmt(b.og)));
      items.push(s("Attenuation", att == null ? "--" : att.toFixed(0) + "%"));
      const t = live("temp");
      items.push(s("Temperature", t == null ? "--" : fmt(t, 1) + "°"));
    }
    return items.join("");
  }

  _updateStats() {
    const el = this.shadowRoot.getElementById("stats");
    if (!el || !this._batch) return;
    const html = this._statsHtml();
    if (html !== this._lastStats) {
      this._lastStats = html;
      el.innerHTML = html;
    }
  }

  _render() {
    this._destroy();
    const b = this._batch;
    let body;
    if (this._error) body = `<div class="empty">${esc(this._error)}</div>`;
    else if (!b) {
      const sel = this._config.batch;
      body = `<div class="empty">${!sel || sel === "active" ? "No active batch right now." : "Batch not found."}</div>`;
    } else {
      const keys = (this._config.charts || []).filter((k) => CHART_KEYS.includes(k));
      this._lastStats = this._statsHtml();
      body =
        `<div class="head" data-open title="Open the library"><h2>${esc(this._config.title || b.name)}</h2>` +
        `<span class="badge s-${b.status}">${LABEL[b.status]}</span></div>` +
        `<div class="stats" id="stats">${this._lastStats}</div>` +
        (this._config.compact ? "" : keys.map((k) => `<div class="chart" id="c-${k}"></div>`).join(""));
    }
    this.shadowRoot.innerHTML = `<style>${CARD_STYLE}${this._lib ? this._lib.css : ""}</style><ha-card>${body}</ha-card>`;
    if (b && !this._error && !this._config.compact) this._draw(b);
  }

  _draw(b) {
    const S = this._series;
    const height = 200;
    const host = (k) => this.shadowRoot.getElementById("c-" + k);
    const add = (c) => c && this._charts.push(c);
    for (const k of (this._config.charts || []).filter((x) => CHART_KEYS.includes(x))) {
      const el = host(k);
      if (!el) continue;
      if (k === "sg") {
        const sg = S.sg;
        add(drawChart(this._lib, el, CHART_LABEL.sg, sg ? [sg.t, sg.v, sg.t.map(() => b.og)] : [[]],
          [{ label: "SG", color: COLORS.sg, width: 3 }, { label: "OG", color: COLORS.og, width: 1, dash: [6, 4] }], { digits: 3, height }));
      } else if (k === "abv") {
        const sg = S.sg;
        add(drawChart(this._lib, el, CHART_LABEL.abv, sg ? [sg.t, sg.v.map((v) => abv(b.og, v))] : [[]],
          [{ label: "ABV", color: COLORS.abv, width: 3 }], { digits: 2, height }));
      } else {
        const s = S[k];
        add(drawChart(this._lib, el, CHART_LABEL[k], s ? [s.t, s.v] : [[]], [{ label: CHART_LABEL[k], color: COLORS[k] }],
          { digits: k === "velocity" ? 3 : k === "battery" ? 0 : 1, height }));
      }
    }
  }
}

class RaptBatchCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._fetch();
  }

  async _fetch() {
    try {
      const r = await this._hass.callWS({ type: "rapt_batches/list" });
      this._opts = r.batches
        .sort((a, b) => b.start_ts - a.start_ts)
        .map((b) => ({ value: b.id, label: `${b.name} (${LABEL[b.status]})` }));
    } catch (e) {
      this._opts = [];
    }
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (e) => {
        this._config = e.detail.value;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    const labels = { title: "Title (optional)", batch: "Batch", charts: "Charts", compact: "Compact (numbers only)" };
    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.computeLabel = (s) => labels[s.name] || s.name;
    this._form.schema = [
      { name: "title", selector: { text: {} } },
      {
        name: "batch",
        selector: {
          select: {
            mode: "dropdown",
            options: [{ value: "active", label: "Current active batch" }, { value: "latest", label: "Most recent batch" }, ...(this._opts || [])],
          },
        },
      },
      { name: "charts", selector: { select: { multiple: true, mode: "list", options: CHART_KEYS.map((k) => ({ value: k, label: CHART_LABEL[k] })) } } },
      { name: "compact", selector: { boolean: {} } },
    ];
  }
}

customElements.define("rapt-batch-card", RaptBatchCard);
customElements.define("rapt-batch-card-editor", RaptBatchCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "rapt-batch-card",
  name: "RAPT Batch",
  description: "Summary and charts for one fermentation batch from the RAPT Batch Library.",
});
