/**
 * LA PAGINA DEGLI STRUMENTI — `/tools/` (E.D., 11 novembre 2026).
 *
 * Il contenuto è quello di `node_admin/modules/tools.js` (30 ottobre), promosso
 * da sezione della casa a pagina: due schede, EMStudio ed EMtools, ciascuna con
 * i suoi passi e il suo pulsante. I requisiti di EMtools vengono dalla sua guida
 * d'installazione (1.5): Blender 4.4 o successivo; sui Mac Intel 4.4 o 4.5,
 * perché Blender 5 non li supporta; le dipendenze si installano da sole.
 *
 * Gli indirizzi li dice il nodo (`/v1/node` → `tools`), mai questa pagina —
 * tranne quello di Blender, che non è del progetto.
 *
 * IL NODO DA CAMPO (`kind: field`). E.D.: «ha senso avere documentazione locale
 * per il nodo fcn, ma bastano i pdf». Un posto per quei PDF sul nodo oggi NON
 * esiste (misurato l'11 novembre: nessun `.pdf` nel repository, nessuna
 * `EM_TOOLS_*` nel compose), e questa pagina non lo inventa: quando il nodo è da
 * campo e la guida che dichiara è un indirizzo esterno, la pagina dice che è
 * online. Il giorno che il nodo servirà i suoi PDF basterà che `/v1/node` li
 * dichiari (`EM_TOOLS_*_MANUAL`), e questa pagina li mostrerà senza cambiare.
 */
import { LOCALE, mountPicker, t } from "../home/i18n.js";
import { mountBar } from "../home/bar.js";

const BLENDER = "https://www.blender.org/download/";
//: `/em/tools/` → `/em/v1`; `/tools/` → `/v1`
const BASE = window.location.pathname.replace(/\/tools(\/.*)?$/, "") + "/v1";

const escapeHtml = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function read(path) {
  const answer = await fetch(BASE + path, { headers: { Accept: "application/json" } });
  if (!answer.ok) throw new Error(`${answer.status} ${path}`);
  return answer.json();
}

let node = null;

function isOnline(href) {
  return /^https?:\/\//i.test(href || "") && new URL(href, location.href).origin !== location.origin;
}

function render() {
  const root = document.getElementById("tools");
  const by = Object.fromEntries(((node && node.tools) || []).map((x) => [x.name, x]));
  const ems = by.emstudio || {};
  const emt = by.blender || {};
  const field = node?.kind === "field";
  const link = (href, text, kind = "") => href
    ? `<a class="k-btn ${kind}" href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(text)}</a>` : "";
  const step = (n, title, body, extra = "") => `<li class="t-step"><span class="t-n">${n}</span><div>
      <b>${escapeHtml(title)}</b><p>${escapeHtml(body)}</p>${extra}</div></li>`;
  const manual = (href, text) => {
    if (!href) return "";
    const note = field && isOnline(href) ? ` <span class="k-faint">· ${escapeHtml(t("tools.manual.online"))}</span>` : "";
    return `<p class="k-faint"><a href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(text)}</a>${note}</p>`;
  };
  root.innerHTML = `
    <div class="k-head"><div><h1>${escapeHtml(t("tools.title"))}</h1>
      <p class="k-lead">${escapeHtml(t("tools.lead"))}</p></div></div>
    <div class="t-grid">
      <section class="t-card"><h2>EMStudio</h2><ol>
        ${step(1, t("tools.ems.1.title"), t("tools.ems.1.body"), link(ems.download, t("tools.ems.download"), "pri"))}
        ${step(2, t("tools.ems.2.title"), t("tools.ems.2.body"))}
        ${step(3, t("tools.ems.3.title"), t("tools.ems.3.body"))}
      </ol>${manual(ems.manual, t("tools.ems.manual"))}</section>
      <section class="t-card"><h2>${escapeHtml(t("tools.emt.title"))}</h2><ol>
        ${step(1, t("tools.emt.1.title"), t("tools.emt.1.body"), link(BLENDER, t("tools.emt.blender")))}
        ${step(2, t("tools.emt.2.title"), t("tools.emt.2.body"), link(emt.download, t("tools.emt.install"), "pri"))}
        ${step(3, t("tools.emt.3.title"), t("tools.emt.3.body"))}
      </ol>${manual(emt.manual, t("tools.emt.manual"))}</section>
    </div>`;
}

function paint() {
  document.documentElement.lang = LOCALE;
  document.title = `StratiGraph · ${t("tools.sub")}`;
  document.getElementById("app-sub").textContent = t("tools.sub");
  document.getElementById("back-door").textContent = t("go.back");
  render();
}

let redrawBar = async () => {};
mountPicker(document.getElementById("lang"), () => { paint(); void redrawBar(false); });
node = await read("/node").catch(() => null);
paint();
redrawBar = await mountBar(document.getElementById("node-bar"), { read, operator: false, t });
