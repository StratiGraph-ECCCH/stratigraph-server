/**
 * LA VETRINA, composta da `/v1/node` e da niente altro (11 novembre 2026).
 *
 * Una riga per servizio che il nodo DICHIARA fra gli `offers`: la sua
 * etichetta, che cosa fa (`what`, la frase del nodo), e il suo stato come il
 * nodo lo dichiara. Nessun nome di servizio è scritto in questo file: il
 * dizionario può tradurre l'etichetta e la frase di un servizio che conosce
 * (`offer.<name>`, `offer.<name>.what`) e ricade sulle parole del nodo per uno
 * che non conosce — così un servizio nuovo compare tradotto quando qualcuno lo
 * traduce, e compare comunque il giorno che il nodo lo annuncia.
 *
 * Un servizio «not configured» e senza indirizzo non è un servizio di QUESTO
 * nodo, ed è l'unico che non si disegna. Uno che non risponde si disegna, con
 * il suo stato: una vetrina che dice «lo studio non risponde» è esattamente ciò
 * che serve vedere durante una dimostrazione.
 */
import { LOCALE, mountPicker, t } from "../home/i18n.js";

//: `/em/` → `/em/v1`; `/` → `/v1`
const BASE = window.location.pathname.replace(/\/(index\.html)?$/, "") + "/v1";
const ABSENT = "not configured";

const $ = (id) => document.getElementById(id);

/** Il dizionario quando ce l'ha, le parole del nodo altrimenti: `t()` torna la
 *  chiave quando non traduce, e il confronto con la chiave è l'unico modo di
 *  saperlo (la stessa regola di `bar.js`). */
function said(key, fallback) {
  const text = t(key);
  return text && text !== key ? text : (fallback || "");
}

let node = null;

function offerRow(offer) {
  const li = document.createElement("li");
  li.className = "v-offer";
  li.dataset.offer = offer.name || "";
  const head = document.createElement("div");
  head.className = "v-offer-head";
  const name = document.createElement(offer.url ? "a" : "span");
  name.className = "v-offer-name";
  name.textContent = said(`offer.${offer.name}`, offer.label || offer.name);
  //: COME LO DICE IL NODO, con la barra finale sui percorsi: `node_services`
  //: la toglie, e misurato l'11 novembre sullo stack vivo `/em/studio` dà 404
  //: (Caddy instrada `/em/studio/*`), `/chat` e `/catalog` 308. Tutte le facce
  //: di questo nodo sono cartelle; la console fa lo stesso per StratiField e
  //: per lo studio. Un indirizzo assoluto resta com'è.
  if (offer.url) name.href = /^\/[^/]/.test(offer.url) && !offer.url.endsWith("/")
    ? `${offer.url}/` : offer.url;
  head.appendChild(name);
  if (offer.state && offer.state !== ABSENT) {
    const state = document.createElement("span");
    state.className = "v-state";
    state.dataset.state = offer.state;
    state.textContent = said(`vetrina.state.${offer.state}`, offer.state);
    head.appendChild(state);
  }
  const what = document.createElement("p");
  what.className = "v-offer-what";
  what.textContent = said(`offer.${offer.name}.what`, offer.what);
  li.append(head, what);
  return li;
}

function render() {
  document.documentElement.lang = LOCALE;
  document.title = `StratiGraph Server · ${t("vetrina.sub")}`;
  $("app-sub").textContent = t("vetrina.sub");
  $("v-tools").textContent = t("vetrina.tools");
  $("v-signin").textContent = t("vetrina.signin");
  $("v-services-title").textContent = t("vetrina.services");
  $("v-invite-text").textContent = t("vetrina.invite");
  $("v-invite").textContent = t("vetrina.signin");
  $("v-lead").textContent = t("vetrina.lead");
  const list = $("v-offers");
  list.replaceChildren();
  if (!node) {
    const li = document.createElement("li");
    li.className = "k-faint";
    li.textContent = t("vetrina.silent");
    list.appendChild(li);
    $("v-facts").textContent = "";
    return;
  }
  const kind = said(`vetrina.kind.${node.kind}`, node.kind);
  $("v-title").textContent = t("vetrina.title", { kind });
  const speaks = Object.entries(node.speaks || {})
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${k} ${v}`).join(" · ");
  const auth = node.auth === "dev-no-auth" ? t("node.auth.off") : t("node.auth.on");
  $("v-facts").textContent = [`stratigraph-server ${node.version}`, speaks, auth]
    .filter(Boolean).join("  ·  ");
  const offers = (node.offers || []).filter((o) => o.state !== ABSENT || o.url);
  for (const offer of offers) list.appendChild(offerRow(offer));
  if (!offers.length) {
    const li = document.createElement("li");
    li.className = "k-faint";
    li.textContent = t("vetrina.none");
    list.appendChild(li);
  }
}

mountPicker($("lang"), render);
try {
  const answer = await fetch(`${BASE}/node`, { headers: { Accept: "application/json" } });
  node = answer.ok ? await answer.json() : null;
} catch { node = null; }
render();
