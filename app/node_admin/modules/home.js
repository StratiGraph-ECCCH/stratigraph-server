/**
 * MODULE · Le tue stanze — la casa del nodo, per CHIUNQUE abbia firmato
 * (scrivania «casa del nodo», 31 ottobre 2026).
 *
 * Una riga per stanza, e su ogni riga le sue porte: EMStudio, nel browser, sul
 * telefono (il QR), EMtools. Le porte NON si scrivono qui: le dice il nodo
 * (`GET /v1/rooms/{id}/open`), come in `rooms_ui/rooms.js`. Accanto a ogni
 * porta che chiede un programma installato, la strada per installarlo.
 *
 * Dove finisce una stanza (persone, inviti, chi vede lo studio) è ancora la
 * pagina della stanza: `../work/?room=…`. Il secondo passo la porta qui dentro.
 */
import { api, escapeHtml, register, show } from "../console.js";
import { L, ROLE_WORD, button, head, toast } from "../kit.js";
import { openRoom } from "./rooms.js";

let tools = null;   // il modulo Strumenti, per i link «installa»
let home = null;    // questa sezione, per ridisegnarla quando la stanza si chiude
let operator = false;

/** La stanza nella casa: lo stesso pannello della console (persone, inviti,
 *  chi vede lo studio, ciclo di vita), con quello che il ruolo nella stanza
 *  permette — e la memoria solo all'operatore, che è chi la legge. */
function openHere(room) {
  openRoom(room, {}, null, { operator, onClose: () => { if (home) void show(home); } });
}
export function setToolsModule(m) { tools = m; }

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
        ? L(`Eri già nella stanza «${got.title}».`, `You were already in «${got.title}».`)
        : L(`Sei entrato nella stanza «${got.title}» come ${ROLE_WORD()[got.role] || got.role}.`,
            `You joined «${got.title}» as ${ROLE_WORD()[got.role] || got.role}.`));
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
    actions.push(button(L("Nuova stanza", "New room"), () => void createRoom(root), "pri"));
  }
  head(root, L("Le tue stanze", "Your rooms"),
    escapeHtml(L("Dove stai lavorando adesso. Apri una stanza nello strumento che hai davanti.",
                 "Where you are working now. Open a room in the tool in front of you.")),
    actions);
  if (!me.may_create) {
    const p = document.createElement("p");
    p.className = "k-faint";
    p.textContent = L("Per aprire una stanza nuova chiedi a chi gestisce il nodo.",
                      "To open a new room, ask whoever runs this node.");
    root.appendChild(p);
  }

  const live = rooms.filter((r) => !r.archived_at);
  const gone = rooms.filter((r) => r.archived_at);
  const list = document.createElement("div");
  list.className = "h-rooms";
  root.appendChild(list);
  if (!live.length) {
    list.innerHTML = `<p class="k-faint">${escapeHtml(L(
      "Non hai ancora un ruolo in nessuna stanza di questo nodo.",
      "You hold no role in any room of this node yet."))}</p>`;
  }
  for (const room of live) list.appendChild(card(room));
  const wanted = asked && rooms.find((r) => r.room_id === asked);
  if (asked) history.replaceState(null, "", location.pathname);   // una volta sola
  if (wanted) openHere(wanted);

  if (gone.length) {
    const more = document.createElement("details");
    more.className = "h-archived";
    more.innerHTML = `<summary>${escapeHtml(L(`Archiviate · ${gone.length}`, `Archived · ${gone.length}`))}</summary>
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
      <span class="h-room-line">${knows ? escapeHtml(L(`${people} ${people === 1 ? "persona" : "persone"}`, `${people} ${people === 1 ? "person" : "people"}`)) : ""}${room.implicit ? " · " + escapeHtml(L("ancora senza titolo", "no title yet")) : ""}</span></div>
      <span class="h-role">${escapeHtml(ROLE_WORD()[room.your_role] || room.your_role || "")}</span>
    </div>
    <div class="h-doors"><span class="h-doors-lab">${escapeHtml(L("Apri in", "Open in"))}</span></div>
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
  catch { said.textContent = L("Le porte di questa stanza non rispondono.", "This room's doors do not answer."); return; }
  const t = doors.tools || {};
  const ems = t.emstudio || {};
  const blend = t.blender || {};
  const field = t.chatbot || {};
  if (ems.scheme) row.appendChild(button("EMStudio", () => openApp(ems.scheme, said)));
  if (ems.browser) row.appendChild(button(L("Nel browser", "In the browser"),
    () => window.open(new URL(ems.browser, location.href).href, "_blank", "noopener")));
  if (field.browser) row.appendChild(button(L("Sul telefono", "On the phone"),
    () => void showQr(box, new URL(field.browser, location.href).href)));
  if (blend.paste) row.appendChild(button("EMtools", () => void copyForBlender(blend.paste, said)));
  const spacer = document.createElement("span");
  spacer.className = "h-grow";
  row.appendChild(spacer);
  const share = document.createElement("a");
  share.href = `#room=${encodeURIComponent(room.room_id)}`;
  share.textContent = L("Persone e condivisione", "People and sharing");
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
    said.append(L("Non si è aperto niente? Forse EMStudio non è installato su questo computer. ",
                  "Nothing opened? EMStudio may not be installed on this computer. "));
    said.appendChild(installLink(L("Installa EMStudio", "Install EMStudio")));
  }, 2000);
}

async function copyForBlender(link, said) {
  said.innerHTML = "";
  try {
    await navigator.clipboard.writeText(link);
    said.append(L("Link copiato. In Blender: EMtools › Apri una stanza da un link, e incolla. ",
                  "Link copied. In Blender: EMtools › Open room from link, and paste. "));
  } catch {
    said.append(L("Copia questo link e incollalo in Blender: ", "Copy this link and paste it in Blender: "), link, " ");
  }
  said.appendChild(installLink(L("Prima volta? Installa Blender ed EMtools", "First time? Install Blender and EMtools")));
}

function installLink(text) {
  const a = document.createElement("a");
  a.href = "#tools";
  a.textContent = text;
  a.addEventListener("click", (e) => { e.preventDefault(); if (tools) void show(tools); });
  return a;
}

let qrLoading = null;
function loadQr() {
  if (window.qrcode) return Promise.resolve(window.qrcode);
  qrLoading = qrLoading || new Promise((ok, no) => {
    const s = document.createElement("script");
    s.src = new URL("../../rooms/vendor/qrcode-generator-1.4.4.js", import.meta.url).href;
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
    img.querySelector("svg")?.setAttribute("aria-label", L("QR che apre StratiField in questa stanza", "QR code that opens StratiField in this room"));
    holder.appendChild(img);
  } catch { /* senza QR resta il link */ }
  const p = document.createElement("p");
  p.className = "k-faint";
  p.textContent = L("Inquadralo con la fotocamera del telefono: StratiField si apre in questa stanza.",
                    "Frame it with the phone's camera: StratiField opens in this room.");
  const code = document.createElement("code");
  code.textContent = url;
  holder.append(p, code);
  box.appendChild(holder);
}

async function createRoom(root) {
  const title = (window.prompt(L("Il nome della stanza nuova", "The new room's name")) || "").trim();
  if (!title) return;
  const room_id = title.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || `room-${Date.now().toString(36)}`;
  try { await api.post("/rooms", { room_id, title }); }
  catch (error) { toast(error.message, "bad"); return; }
  toast(L(`Stanza «${title}» creata: ne sei proprietario.`, `Room «${title}» created: you own it.`));
  await render(root);
}

home = register({ id: "home", title: L("Le tue stanze", "Your rooms"), render, everyone: true, order: 0 });
