// <rapt-stats-card>: totals and averages across your batches.
import { CARD_STYLE, abv, daysOf, defineEditor, esc, fmt, navigate, PANEL_PATH, registerCard } from "./rapt-card-shared.js";

const PERIODS = [
  { value: "all", label: "All time" },
  { value: "year", label: "This calendar year" },
  { value: "90d", label: "Last 90 days" },
];
const avg = (xs) => (xs.length ? xs.reduce((a, c) => a + c, 0) / xs.length : null);

export function computeStats(batches, period, now = new Date()) {
  const inPeriod = (b) =>
    period === "year" ? new Date(b.start_ts * 1000).getFullYear() === now.getFullYear()
      : period === "90d" ? b.start_ts >= now.getTime() / 1000 - 90 * 86400
      : true;
  const rows = batches.filter(inPeriod);
  // Averages use finished and archived batches that have both an OG and an FG.
  const done = rows.filter((b) => b.status !== "active" && b.og != null && b.fg != null);
  const abvs = done.map((b) => ({ b, abv: abv(b.og, b.fg) }));
  const strongest = abvs.reduce((best, x) => (!best || x.abv > best.abv ? x : best), null);
  return {
    total: rows.length,
    active: rows.filter((b) => b.status === "active").length,
    avgAbv: avg(abvs.map((x) => x.abv)),
    strongest,
    avgAtt: avg(done.filter((b) => b.og > 1).map((b) => ((b.og - b.fg) / (b.og - 1)) * 100)),
    avgDays: avg(done.map((b) => daysOf(b))),
  };
}

class RaptStatsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._batches = [];
    this.shadowRoot.addEventListener("click", (e) => {
      if (e.target.closest("[data-open]")) navigate(PANEL_PATH);
    });
  }
  static getConfigElement() {
    return document.createElement("rapt-stats-card-editor");
  }
  static getStubConfig() {
    return { period: "all" };
  }
  setConfig(config) {
    this._config = { period: "all", title: "Brewing stats", ...config };
    this._render();
    this._load();
  }
  getCardSize() {
    return 3;
  }
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._load();
  }
  connectedCallback() {
    this._timer = setInterval(() => this._load(), 120000);
    this._load();
  }
  disconnectedCallback() {
    clearInterval(this._timer);
  }

  async _load() {
    if (!this._hass || !this._config) return;
    try {
      this._batches = (await this._hass.callWS({ type: "rapt_batches/list" })).batches;
      this._error = null;
    } catch (e) {
      this._error = (e && e.message) || "Could not load batches.";
    }
    this._render();
  }

  _render() {
    if (!this._config) return;
    const s = computeStats(this._batches, this._config.period);
    const stat = (label, val, sub = "") => `<div class="stat"><b>${val}</b><span>${label}${sub ? `<br>${esc(sub)}` : ""}</span></div>`;
    let body;
    if (this._error) body = `<div class="empty">${esc(this._error)}</div>`;
    else if (!s.total) body = `<div class="empty">No batches in this period yet.</div>`;
    else
      body = `<div class="stats">` +
        stat("Batches", s.total, s.active ? `${s.active} brewing now` : "") +
        stat("Average ABV", s.avgAbv == null ? "--" : s.avgAbv.toFixed(1) + "%") +
        stat("Strongest", s.strongest ? s.strongest.abv.toFixed(1) + "%" : "--", s.strongest ? s.strongest.b.name : "") +
        stat("Average attenuation", s.avgAtt == null ? "--" : s.avgAtt.toFixed(0) + "%") +
        stat("Average days", s.avgDays == null ? "--" : fmt(s.avgDays, 1)) +
        `</div>`;
    this.shadowRoot.innerHTML = `<style>${CARD_STYLE}h2.title{margin:0 0 8px;font-size:18px;font-weight:500;cursor:pointer}.stat span{display:block}</style>` +
      `<ha-card><h2 class="title" data-open>${esc(this._config.title)}</h2>${body}</ha-card>`;
  }
}

defineEditor("rapt-stats-card-editor", { title: "Title", period: "Period" }, () => [
  { name: "title", selector: { text: {} } },
  { name: "period", selector: { select: { mode: "dropdown", options: PERIODS } } },
]);
customElements.define("rapt-stats-card", RaptStatsCard);
registerCard("rapt-stats-card", "RAPT Stats", "Totals and averages across your fermentation batches.");
