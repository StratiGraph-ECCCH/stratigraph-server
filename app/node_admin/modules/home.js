/**
 * MODULE · Le tue stanze — la casa del nodo, per CHIUNQUE abbia firmato
 * (scrivania «casa del nodo», 31 ottobre 2026).
 *
 * Una riga per stanza, e su ogni riga le sue porte: EMStudio, nel browser, sul
 * telefono (il QR), EMtools. Le porte NON si scrivono qui: le dice il nodo
 * (`GET /v1/rooms/{id}/open`). Accanto a ogni
 * porta che chiede un programma installato, la strada per installarlo.
 *
 * La stanza si apre qui dentro (persone, inviti, chi vede lo studio): `#room=…`,
 * o `?room=…` dei link vecchi. Gli strumenti da installare sono una pagina loro,
 * `../tools/` (11 novembre 2026).
 */
import { api, escapeHtml, register, show } from "../console.js";
import { ROLE_WORD, button, head, toast } from "../kit.js";
import { t } from "../i18n.js";
import { openRoom } from "./rooms.js";

let home = null;    // questa sezione, per ridisegnarla quando la stanza si chiude
let operator = false;

/** La stanza nella casa: lo stesso pannello della console (persone, inviti,
 *  chi vede lo studio, ciclo di vita), con quello che il ruolo nella stanza
 *  permette — e la memoria solo all'operatore, che è chi la legge. */
function openHere(room) {
  openRoom(room, {}, null, { operator, onClose: () => { if (home) void show(home); } });
}

async function render(root) {
  const [rooms, me, op] = await Promise.all([
    api.get("/rooms"),
    api.get("/whoami").catch(() => ({})),
    api.get("/admin/whoami").catch(() => ({})),
  ]);
  operator = op?.operator === true;
  // UN INVITO (`?join=<token>`): si accetta qui, poi si apre la stanza. È il
  // link che i proprietari mandano; prima atterrava su una pagina che non lo
  // leggeva.
  const join = new URLSearchParams(location.search).get("join");
  if (join) {
    history.replaceState(null, "", location.pathname);
    try {
      const got = await api.post("/join", { token: join });
      toast(got.already_had
        ? t("home.join.already", { title: got.title })
        : t("home.join.done", { title: got.title, role: ROLE_WORD()[got.role] || got.role }));
      return render(root);
    } catch (error) { toast(error.message, "bad"); }
  }
  // UNA STANZA NELL'INDIRIZZO (`#room=…`, e i vecchi `?room=` della pagina
  // Lavorare): si apre il suo pannello, l'elenco resta sotto
  const asked = decodeURIComponent((location.hash.match(/room=([^&]+)/) || [])[1]
    || new URLSearchParams(location.search).get("room") || "");
  root.innerHTML = "";
  const actions = [];
  if (me.may_create) {
    actions.push(button(t("home.new"), () => void createRoom(root), "pri"));
  }
  head(root, t("home.title"),
    escapeHtml(t("home.lead")),
    actions);
  if (!me.may_create) {
    const p = document.createElement("p");
    p.className = "k-faint";
    p.textContent = t("home.askToCreate");
    root.appendChild(p);
  }

  const live = rooms.filter((r) => !r.archived_at);
  const gone = rooms.filter((r) => r.archived_at);
  const list = document.createElement("div");
  list.className = "h-rooms";
  root.appendChild(list);
  if (!live.length) {
    list.innerHTML = `<p class="k-faint">${escapeHtml(t("home.noRooms"))}</p>`;
  }
  for (const room of live) list.appendChild(card(room));
  const wanted = asked && rooms.find((r) => r.room_id === asked);
  if (asked) history.replaceState(null, "", location.pathname);   // una volta sola
  if (wanted) openHere(wanted);

  if (gone.length) {
    const more = document.createElement("details");
    more.className = "h-archived";
    more.innerHTML = `<summary>${escapeHtml(t("home.archived", { n: gone.length }))}</summary>
      <p>${gone.map((r) => escapeHtml(r.title || r.room_id)).join(" — ")}</p>`;
    root.appendChild(more);
  }
}

function card(room) {
  const box = document.createElement("article");
  box.className = "h-room";
  box.dataset.room = room.room_id;
  const people = (room.members || []).length + (room.owner ? 1 : 0);
  // le persone le conosce chi governa la stanza: agli altri il nodo non le
  // elenca, e «1 persona» sarebbe falso
  const knows = ["owner", "admin"].includes(room.your_role);
  box.innerHTML = `<div class="h-room-head">
      <div><a class="h-room-title" href="#room=${encodeURIComponent(room.room_id)}">${escapeHtml(room.title || room.room_id)}</a>
      <span class="h-room-line">${knows ? escapeHtml(t(people === 1 ? "home.people.one" : "home.people.many", { n: people })) : ""}${room.implicit ? " · " + escapeHtml(t("home.untitled")) : ""}</span></div>
      <span class="h-role">${escapeHtml(ROLE_WORD()[room.your_role] || room.your_role || "")}</span>
    </div>
    <div class="h-doors"><span class="h-doors-lab">${escapeHtml(t("home.openIn"))}</span></div>
    <div class="h-said" role="status"></div>`;
  void addDoors(room, box);
  box.querySelector(".h-room-title").addEventListener("click", (e) => { e.preventDefault(); openHere(room); });
  return box;
}

async function addDoors(room, box) {
  const row = box.querySelector(".h-doors");
  const said = box.querySelector(".h-said");
  let doors;
  try { doors = await api.get(`/rooms/${encodeURIComponent(room.room_id)}/open`); }
  catch { said.textContent = t("home.doors.silent"); return; }
  const t = doors.tools || {};
  const ems = t.emstudio || {};
  const blend = t.blender || {};
  const field = t.chatbot || {};
  if (ems.scheme) row.appendChild(button("EMStudio", () => openApp(ems.scheme, said)));
  if (ems.browser) row.appendChild(button(t("home.door.browser"),
    () => window.open(new URL(ems.browser, location.href).href, "_blank", "noopener")));
  if (field.browser) row.appendChild(button(t("home.door.phone"),
    () => void showQr(box, new URL(field.browser, location.href).href)));
  if (blend.paste) row.appendChild(button("EMtools", () => void copyForBlender(blend.paste, said)));
  const spacer = document.createElement("span");
  spacer.className = "h-grow";
  row.appendChild(spacer);
  const share = document.createElement("a");
  share.href = `#room=${encodeURIComponent(room.room_id)}`;
  share.textContent = t("home.share");
  share.addEventListener("click", (e) => { e.preventDefault(); openHere(room); });
  row.appendChild(share);
}

/** L'app installata, e se non si apre niente la strada per installarla.
 *  Una pagina non può sapere se EMStudio c'è: lo capisce dal fatto che la
 *  finestra non ha perso il fuoco entro due secondi. */
function openApp(scheme, said) {
  let left = false;
  const away = () => { left = true; };
  window.addEventListener("blur", away, { once: true });
  window.location.href = scheme;
  window.setTimeout(() => {
    window.removeEventListener("blur", away);
    if (left) return;
    said.innerHTML = "";
    said.append(t("home.app.nothing") + " ");
    said.appendChild(installLink(t("home.install.emstudio")));
  }, 2000);
}

async function copyForBlender(link, said) {
  said.innerHTML = "";
  try {
    await navigator.clipboard.writeText(link);
    said.append(t("home.blender.copied") + " ");
  } catch {
    said.append(t("home.blender.copy") + " ", link, " ");
  }
  said.appendChild(installLink(t("home.install.blender")));
}

/** La strada per installare: la pagina degli strumenti, per indirizzo. Da
 *  `/em/home/` è `/em/tools/` — relativo, perché il prefisso è del proxy. */
function installLink(text) {
  const a = document.createElement("a");
  a.href = "../tools/";
  a.textContent = text;
  return a;
}

let qrLoading = null;
function loadQr() {
  if (window.qrcode) return Promise.resolve(window.qrcode);
  qrLoading = qrLoading || new Promise((ok, no) => {
    const s = document.createElement("script");
    //: `app/vendor/`, montata su `/vendor` (11 novembre 2026): da
    //: `/em/home/modules/home.js` sono due cartelle in su
    s.src = new URL("../../vendor/qrcode-generator-1.4.4.js", import.meta.url).href;
    s.onload = () => ok(window.qrcode);
    s.onerror = () => { qrLoading = null; no(new Error("qr")); };
    document.head.append(s);
  });
  return qrLoading;
}

async function showQr(box, url) {
  const old = box.querySelector(".qr-box");
  if (old) { old.remove(); return; }
  const holder = document.createElement("div");
  holder.className = "qr-box";
  try {
    const make = await loadQr();
    const qr = make(0, "M"); qr.addData(url, "Byte"); qr.make();
    const img = document.createElement("div");
    img.className = "qr";
    img.innerHTML = qr.createSvgTag({ cellSize: 5, margin: 3, scalable: true });
    img.querySelector("svg")?.setAttribute("aria-label", t("home.qr.label"));
    holder.appendChild(img);
  } catch { /* senza QR resta il link */ }
  const p = document.createElement("p");
  p.className = "k-faint";
  p.textContent = t("home.qr.how");
  const code = document.createElement("code");
  code.textContent = url;
  holder.append(p, code);
  box.appendChild(holder);
}

async function createRoom(root) {
  const title = (window.prompt(t("home.new.prompt")) || "").trim();
  if (!title) return;
  const room_id = title.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || `room-${Date.now().toString(36)}`;
  try { await api.post("/rooms", { room_id, title }); }
  catch (error) { toast(error.message, "bad"); return; }
  toast(t("home.new.done", { title }));
  await render(root);
}

home = register({ id: "home", title: () => t("home.title"), render, everyone: true, order: 0 });
