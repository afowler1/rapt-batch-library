// <rapt-library-card>: a compact list of batches. Tapping it opens the library.
import { CARD_STYLE, LABEL, PANEL_PATH, abv, batchOptions, daysOf, defineEditor, esc, fmt, fmtDate, liveValue, navigate, registerCard } from "./rapt-card-shared.js";

const STYLE = CARD_STYLE + `
h2.title{margin:0 0 4px;font-size:18px;font-weight:500}
.row{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center;padding:10px 0;border-top:1px solid var(--divider-color);cursor:pointer}
.row.first{border-top:none}
.row b{font-weight:500;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row small{color:var(--secondary-text-color)}
.abv{font-size:18px;font-weight:500;min-width:56px;text-align:right}
.more{padding:8px 0 4px;text-align:center;color:var(--primary-color);cursor:pointer;font-size:13px}
`;
const FILTERS = [
  { value: "all", label: "All batches" },
  { value: "active", label: "Active only" },
  { value: "completed", label: "Finished only" },
  { value: "archived", label: "Archived only" },
];

class RaptLibraryCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._batches = [];
    this._html = "";
    this.shadowRoot.addEventListener("click", (e) => {
      if (e.target.closest("[data-open]")) navigate(PANEL_PATH);
    });
  }
  static getConfigElement() {
    return document.createElement("rapt-library-card-editor");
  }
  static getStubConfig() {
    return { filter: "all", limit: 5 };
  }
  setConfig(config) {
    this._config = { filter: "all", limit: 5, title: "Brewing library", ...config };
    this._render();
    this._load();
  }
  getCardSize() {
    return 1 + Math.min(this._config ? this._config.limit : 5, 10);
  }
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._load();
    else this._render(); // live ABV for active batches; skipped when nothing changed
  }
  connectedCallback() {
    this._timer = setInterval(() => this._load(), 60000);
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
    const cfg = this._config;
    const rows = this._batches
      .filter((b) => cfg.filter === "all" || b.status === cfg.filter)
      .sort((a, b) => (b.status === "active") - (a.status === "active") || b.start_ts - a.start_ts);
    const shown = rows.slice(0, Math.max(1, cfg.limit));
    let body;
    if (this._error) body = `<div class="empty">${esc(this._error)}</div>`;
    else if (!rows.length) body = `<div class="empty">No batches to show yet.</div>`;
    else {
      body =
        shown
          .map((b, i) => {
            const sg = b.status === "active" ? liveValue(this._hass, b, "sg") : b.fg ?? b.latest.sg;
            const a = abv(b.og, sg);
            return `<div class="row ${i === 0 ? "first" : ""}" data-open><div><b>${esc(b.name)}</b>` +
              `<small>${fmtDate(b.start_ts)} · ${fmt(daysOf(b), 1)} d</small></div>` +
              `<span class="badge s-${b.status}">${LABEL[b.status]}</span>` +
              `<span class="abv">${a == null ? "--" : a.toFixed(1) + "%"}</span></div>`;
          })
          .join("") +
        (rows.length > shown.length ? `<div class="more" data-open>${rows.length - shown.length} more in the library</div>` : "");
    }
    const html = `<ha-card><h2 class="title" data-open style="cursor:pointer">${esc(cfg.title)}</h2>${body}</ha-card>`;
    if (html !== this._html) {
      this._html = html;
      this.shadowRoot.innerHTML = `<style>${STYLE}</style>${html}`;
    }
  }
}

defineEditor(
  "rapt-library-card-editor",
  { title: "Title", filter: "Show", limit: "Number of batches" },
  () => [
    { name: "title", selector: { text: {} } },
    { name: "filter", selector: { select: { mode: "dropdown", options: FILTERS } } },
    { name: "limit", selector: { number: { min: 1, max: 20, mode: "box" } } },
  ]
);
customElements.define("rapt-library-card", RaptLibraryCard);
registerCard("rapt-library-card", "RAPT Library", "A compact list of your fermentation batches.");
