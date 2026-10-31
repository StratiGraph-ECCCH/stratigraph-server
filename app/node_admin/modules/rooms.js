/**
 * MODULE · Stanze — every room on the node, as the desk of 30 October 2026 drew
 * it: filters (active · archived · implicit), one row per room, and a slide-over
 * with five tabs (people and roles · invitations · who sees the study · memory ·
 * lifecycle).
 *
 * WHO MAY DO WHAT IS NOT DECIDED HERE. Inside a room the super-administrator
 * counts for the role held there (`your_role`), and the room's own endpoints
 * answer with a 403 and a sentence when they refuse. This page only avoids
 * offering what would be refused, and says why. The node-wide acts — archive,
 * delete, and the rescue of a room nobody can manage — go to `/v1/admin/…`.
 */
import { api, confirmNamed, confirmTyped, escapeHtml, register } from "../console.js";
import { L, RANK, ROLE_WORD, button, bytes, chips, drawer, head, roleChip, tag, toast } from "../kit.js";

let filter = "active";
let query = "";
//: LE STANZE SCELTE per un'azione in blocco (31 ottobre: «voglio anche le
//: operazioni in batch su più stanze»). Sopravvive al cambio di filtro: si
//: sceglie in «Attive» e in «Implicite», e si agisce una volta.
const picked = new Set();

async function render(root) {
  const [rooms, storage] = await Promise.all([
    api.get("/admin/rooms"),
    api.get("/admin/storage").catch(() => ({ rooms: [] })),
  ]);
  const space = Object.fromEntries((storage.rooms || []).map((r) => [r.room_id, r]));
  root.innerHTML = "";
  const implicit = rooms.filter((r) => r.implicit);
  const counts = {
    active: rooms.filter((r) => !r.implicit && !r.archived_at).length,
    archived: rooms.filter((r) => r.archived_at).length,
    implicit: implicit.length,
  };
  head(root, L("Stanze del nodo", "Rooms of the node"),
    escapeHtml(L("Ogni stanza del nodo, anche quelle dove non hai un ruolo. Una stanza è la copia viva di un em.json: chi ci lavora, con quale ruolo, e chi può vedere lo studio.",
      "Every room on the node, including those where you hold no role. A room is the live copy of one em.json: who works in it, with which role, and who may see the study.")));

  if (implicit.length) {
    const banner = document.createElement("div");
    banner.className = "k-banner";
    banner.innerHTML = `<span>${escapeHtml(L(
      `${implicit.length} stanze implicite: nessuno le ha dichiarate. Di solito sono nate dai test.`,
      `${implicit.length} implicit rooms: nobody declared them. Usually tests made them.`))}</span>`;
    banner.appendChild(button(L("Elimina le implicite…", "Delete the implicit ones…"),
      () => void deleteMany(implicit, root), "warn"));
    root.appendChild(banner);
  }

  const bar = chips([
    ["active", L("Attive", "Active"), counts.active],
    ["archived", L("Archiviate", "Archived"), counts.archived],
    ["implicit", L("Implicite", "Implicit"), counts.implicit],
  ], filter, (k) => { filter = k; void render(root); });
  const search = document.createElement("input");
  search.type = "search";
  search.className = "k-search";
  search.placeholder = L("Cerca per nome o id…", "Search by name or id…");
  search.value = query;
  search.setAttribute("aria-label", search.placeholder);
  search.addEventListener("input", () => { query = search.value; drawRows(); });
  bar.append(Object.assign(document.createElement("span"), { style: "flex:1" }), search);
  root.appendChild(bar);

  const wrap = document.createElement("div");
  wrap.className = "k-tw";
  // LA BARRA DELLE AZIONI IN BLOCCO: compare quando c'è almeno una scelta
  const batch = document.createElement("div");
  batch.className = "k-banner k-batch";
  batch.hidden = true;
  root.appendChild(batch);
  wrap.innerHTML = `<table class="k-table"><thead><tr>
    <th class="k-pick"><input type="checkbox" id="k-pick-all" aria-label="${escapeHtml(L("Scegli tutte quelle elencate", "Pick every listed room"))}"></th>
    <th>${L("Stanza", "Room")}</th><th>${L("Proprietario", "Owner")}</th>
    <th>${L("Persone", "People")}</th><th>${L("Il tuo ruolo", "Your role")}</th>
    <th class="num">${L("File", "Files")}</th><th class="num">${L("Spazio", "Space")}</th>
    <th>${L("Creata", "Created")}</th></tr></thead><tbody></tbody></table>`;
  root.appendChild(wrap);
  const body = wrap.querySelector("tbody");

  function drawRows() {
    const q = query.trim().toLowerCase();
    const list = rooms
      .filter((r) => filter === "active" ? !r.implicit && !r.archived_at
        : filter === "archived" ? Boolean(r.archived_at) : r.implicit)
      .filter((r) => !q || `${r.title} ${r.room_id}`.toLowerCase().includes(q))
      .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
    body.innerHTML = list.map((r) => {
      const s = space[r.room_id] || {};
      const people = (r.members || []).length + Object.keys(r.groups || {}).length + (r.owner ? 1 : 0);
      return `<tr class="k-click" tabindex="0" data-room="${escapeHtml(r.room_id)}">
        <td class="k-pick"><input type="checkbox" data-pick="${escapeHtml(r.room_id)}" ${picked.has(r.room_id) ? "checked" : ""} aria-label="${escapeHtml(L("Scegli", "Pick") + " " + r.room_id)}"></td>
        <td class="k-title"><b>${escapeHtml(r.title || r.room_id)}</b><small>${escapeHtml(r.room_id)}</small></td>
        <td class="k-mono">${escapeHtml(r.owner || L("nessuno", "nobody"))}</td>
        <td>${people}${Object.keys(r.groups || {}).length ? ` <span class="k-faint">· ${Object.keys(r.groups).length} ${L("gruppi", "groups")}</span>` : ""}</td>
        <td>${roleChip(r.your_role)}</td>
        <td class="num">${s.assets ?? "—"}${(r.missing_refs || []).length ? " " + tag("!", "warn") : ""}</td>
        <td class="num">${bytes(s.bytes)}</td>
        <td class="k-mono">${r.archived_at ? tag(L("archiviata", "archived")) : escapeHtml(String(r.created_at || "").slice(0, 10))}</td></tr>`;
    }).join("") || `<tr><td colspan="8" class="k-faint">${escapeHtml(L("Nessuna stanza in questo elenco.", "No room in this list."))}</td></tr>`;
    body.querySelectorAll("input[data-pick]").forEach((box) => {
      box.addEventListener("click", (e) => e.stopPropagation());
      box.addEventListener("change", () => {
        if (box.checked) picked.add(box.dataset.pick); else picked.delete(box.dataset.pick);
        paintBatch();
      });
    });
    const all = wrap.querySelector("#k-pick-all");
    all.checked = list.length > 0 && list.every((r) => picked.has(r.room_id));
    all.onchange = () => {
      for (const r of list) { if (all.checked) picked.add(r.room_id); else picked.delete(r.room_id); }
      drawRows();
    };
    paintBatch();
    body.querySelectorAll("tr[data-room]").forEach((tr) => {
      const open = () => openRoom(rooms.find((r) => r.room_id === tr.dataset.room), space, root);
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    });
  }
  function paintBatch() {
    // solo le scelte che esistono ancora (una stanza eliminata altrove esce)
    for (const id of [...picked]) if (!rooms.some((r) => r.room_id === id)) picked.delete(id);
    const chosen = rooms.filter((r) => picked.has(r.room_id));
    batch.hidden = !chosen.length;
    if (!chosen.length) { batch.innerHTML = ""; return; }
    const live = chosen.filter((r) => !r.archived_at && !r.implicit);
    const gone = chosen.filter((r) => r.archived_at);
    batch.innerHTML = `<span><b>${chosen.length}</b> ${escapeHtml(L(chosen.length === 1 ? "stanza scelta" : "stanze scelte", chosen.length === 1 ? "room picked" : "rooms picked"))}</span>`;
    const acts = document.createElement("span");
    acts.className = "k-batch-acts";
    if (live.length) acts.appendChild(button(L(`Archivia (${live.length})`, `Archive (${live.length})`),
      () => void archiveMany(live, true, root)));
    if (gone.length) acts.appendChild(button(L(`Riapri (${gone.length})`, `Restore (${gone.length})`),
      () => void archiveMany(gone, false, root)));
    acts.appendChild(button(L(`Elimina (${chosen.length})…`, `Delete (${chosen.length})…`),
      () => void deleteMany(chosen, root), "warn"));
    acts.appendChild(button(L("Togli la scelta", "Clear"), () => { picked.clear(); drawRows(); }));
    batch.appendChild(acts);
  }
  drawRows();
}

/** UNA PER VOLTA ERA LENTO E MUTO (31 ottobre: 36 stanze, ~0,4 s l'una, e
 *  nessun segno di vita — la seconda volta si è premuto di nuovo). Sei alla
 *  volta, e un contatore che dice a che punto si è. */
async function inPool(list, work, say) {
  const POOL = 6;
  let next = 0, done = 0;
  const refused = [];
  const note = document.createElement("div");
  note.className = "k-banner k-progress";
  note.setAttribute("role", "status");
  document.querySelector(".k-batch, .k-banner")?.before(note);
  const paint = () => { note.textContent = say(done, list.length); };
  paint();
  document.querySelectorAll(".k-batch button, .k-banner button").forEach((b) => { b.disabled = true; });
  async function lane() {
    while (next < list.length) {
      const r = list[next++];
      try { await work(r); } catch (error) { refused.push(`${r.room_id}: ${error.message}`); }
      done++;
      paint();
    }
  }
  await Promise.all(Array.from({ length: Math.min(POOL, list.length) }, lane));
  note.remove();
  return { done: list.length - refused.length, refused };
}

/** Archiviare (o riaprire) più stanze: un segno, mai una cancellazione. Le
 *  implicite non si archiviano — non hanno un registro su cui scrivere il segno —
 *  e per questo la barra non le offre. */
async function archiveMany(list, archived, root) {
  const n = list.length;
  const what = archived
    ? L(`l'archiviazione di ${n} stanze: restano leggibili, nessuno ci scrive più`,
        `archiving ${n} rooms: they stay readable, nobody writes in them`)
    : L(`la riapertura di ${n} stanze`, `restoring ${n} rooms`);
  if (!confirmTyped(what, archived ? L("ARCHIVIA", "ARCHIVE") : L("RIAPRI", "RESTORE"))) return;
  const { done, refused } = await inPool(list,
    (r) => api.post(`/admin/rooms/${encodeURIComponent(r.room_id)}/archive`,
                    { archived, confirm_room_id: r.room_id }),
    (d, n) => archived ? L(`Archivio… ${d} di ${n}`, `Archiving… ${d} of ${n}`)
                       : L(`Riapro… ${d} di ${n}`, `Restoring… ${d} of ${n}`));
  for (const r of list) picked.delete(r.room_id);
  toast((archived ? L(`${done} stanze archiviate.`, `${done} rooms archived.`)
                  : L(`${done} stanze riaperte.`, `${done} rooms restored.`))
        + (refused.length ? " " + L(`${refused.length} rifiutate.`, `${refused.length} refused.`) : ""),
        refused.length ? "bad" : "");
  if (refused.length) console.warn(refused.join("\n"));
  await render(root);
}

async function deleteMany(list, root) {
  const n = list.length;
  const word = L("ELIMINA", "DELETE");
  const implicitOnly = list.every((r) => r.implicit);
  const names = list.slice(0, 8).map((r) => r.room_id).join(", ") + (n > 8 ? ` … (+${n - 8})` : "");
  if (!confirmTyped(implicitOnly
    ? L(`l'eliminazione di ${n} stanze implicite, con i loro em.json e tutte le revisioni`,
        `deleting ${n} implicit rooms, with their em.json and every revision`)
    : L(`l'eliminazione DEFINITIVA di ${n} stanze (${names}), con i loro em.json, le revisioni, i membri e gli inviti. Non si può annullare`,
        `the PERMANENT deletion of ${n} rooms (${names}), with their em.json, revisions, members and invitations. It cannot be undone`), word)) return;
  const { done, refused } = await inPool(list,
    (r) => api.del(`/rooms/${encodeURIComponent(r.room_id)}`, { confirm: r.room_id }),
    (d, n) => L(`Elimino… ${d} di ${n}`, `Deleting… ${d} of ${n}`));
  for (const r of list) picked.delete(r.room_id);
  toast(L(`${done} stanze eliminate.`, `${done} rooms deleted.`) + (refused.length ? " " + L(`${refused.length} rifiutate.`, `${refused.length} refused.`) : ""),
    refused.length ? "bad" : "");
  if (refused.length) console.warn(refused.join("\n"));
  await render(root);
}

export function openRoom(room, space, root, { operator = true, onClose = null } = {}) {
  const manage = ["owner", "admin"].includes(room.your_role);
  drawer({
    title: room.title || room.room_id,
    subtitle: room.room_id,
    chips: [room.archived_at ? tag(L("archiviata", "archived")) : "",
            room.implicit ? tag(L("implicita", "implicit"), "warn") : "",
            `<span class="k-faint">${escapeHtml(L("il tuo ruolo:", "your role:"))}</span>`, roleChip(room.your_role)].join(" "),
    onClose: onClose || (() => void render(root)),
    tabs: [
      ["people", L("Persone e ruoli", "People and roles"), (b, d) => tabPeople(b, d, room, manage)],
      ["invites", L("Inviti", "Invitations"), (b, d) => tabInvites(b, d, room, manage)],
      ["vis", L("Chi vede lo studio", "Who sees the study"), (b, d) => tabVisibility(b, d, room, manage)],
      operator ? ["mem", L("Memoria", "Memory"), (b) => tabMemory(b, room, space[room.room_id] || {})] : null,
      (operator || manage) ? ["life", L("Ciclo di vita", "Lifecycle"), (b, d) => tabLife(b, d, room, operator)] : null,
    ].filter(Boolean),
  });
}

async function tabPeople(body, drawerCtl, room, manage) {
  const id = encodeURIComponent(room.room_id);
  let members = null;
  try { members = await api.get(`/rooms/${id}/members`); } catch { members = null; }
  const owner = members?.owner ?? room.owner;
  const rows = [];
  if (owner) rows.push({ kind: "p", id: owner, role: "owner" });
  for (const m of members?.members || room.members || []) if (m.orcid !== owner) rows.push({ kind: "p", id: m.orcid, role: m.role });
  const grants = members ? Object.fromEntries((members.groups || []).map((g) => [g.group_id, g.role])) : (room.groups || {});
  for (const [gid, role] of Object.entries(grants)) {
    rows.push({ kind: "g", id: gid, role });
  }
  const mine = room.your_role;
  const canSet = (current, wanted) => mine === "owner" || (mine === "admin" && RANK[current] <= RANK.editor && RANK[wanted] <= RANK.editor);
  body.innerHTML = `
    ${!manage ? `<p class="k-note">${escapeHtml(L(
      "Dentro una stanza conti per il ruolo che hai lì. Per cambiare le persone serve essere proprietario o amministratore di questa stanza.",
      "Inside a room you count for the role you hold there. Changing its people needs owner or admin in this room."))}</p>` : ""}
    <div class="k-list">${rows.map((x) => {
      const choices = ["admin", "editor", "viewer"].filter((r) => canSet(x.role, r));
      const sel = x.role !== "owner" && manage && choices.length && canSet(x.role, x.role)
        ? `<select data-who="${escapeHtml(x.kind + ":" + x.id)}" aria-label="${escapeHtml(x.id)}">${choices.map((r) =>
            `<option value="${r}" ${r === x.role ? "selected" : ""}>${escapeHtml(ROLE_WORD()[r])}</option>`).join("")}
            <option value="">${escapeHtml(L("togli dalla stanza", "remove from the room"))}</option></select>`
        : roleChip(x.role);
      return `<div class="k-li"><div><b>${escapeHtml(x.kind === "g" ? L("gruppo ", "group ") + x.id : x.id)}</b>
        <small>${escapeHtml(x.kind === "g" ? L("una squadra", "a team") : "ORCID")}</small></div>${sel}</div>`;
    }).join("") || `<div class="k-li"><span class="k-faint">${escapeHtml(L("Nessuno ha ancora un ruolo qui.", "Nobody holds a role here yet."))}</span></div>`}</div>
    ${manage ? `<div class="k-form"><input id="k-add" placeholder="${escapeHtml(L("ORCID o id di un gruppo", "ORCID or a group id"))}">
      <select id="k-add-role">${["admin", "editor", "viewer"].filter((r) => canSet("viewer", r)).map((r) =>
        `<option value="${r}" ${r === "editor" ? "selected" : ""}>${escapeHtml(ROLE_WORD()[r])}</option>`).join("")}</select></div>` : ""}
    <p class="k-note">${escapeHtml(L(
      "Vale il ruolo più alto fra quelli di una persona: il suo e quelli dei gruppi. Il proprietario gestisce gli amministratori; un amministratore gestisce editor e lettori.",
      "The highest role a person holds counts: their own and their groups'. The owner manages admins; an admin manages editors and readers."))}</p>`;
  body.querySelectorAll("select[data-who]").forEach((sel) => sel.addEventListener("change", async () => {
    const [kind, who] = sel.dataset.who.split(":");
    const path = kind === "g" ? `/rooms/${id}/groups/${encodeURIComponent(who)}` : `/rooms/${id}/members/${encodeURIComponent(who)}`;
    try {
      if (!sel.value) await api.del(path); else await api.put(path, { role: sel.value });
      toast(sel.value ? L(`Ora è ${ROLE_WORD()[sel.value]}.`, `Now ${ROLE_WORD()[sel.value]}.`) : L("Tolto dalla stanza.", "Removed from the room."));
    } catch (error) { toast(error.message, "bad"); }
    drawerCtl.reopen();
  }));
  if (manage) {
    const form = body.querySelector(".k-form");
    form.appendChild(button(L("Aggiungi", "Add"), async () => {
      const who = body.querySelector("#k-add").value.trim();
      const role = body.querySelector("#k-add-role").value;
      if (!who) return;
      const isOrcid = /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/i.test(who);
      const path = isOrcid ? `/rooms/${id}/members/${encodeURIComponent(who)}` : `/rooms/${id}/groups/${encodeURIComponent(who)}`;
      try { await api.put(path, { role }); toast(L("Aggiunto.", "Added.")); }
      catch (error) { toast(error.message, "bad"); }
      drawerCtl.reopen();
    }, "pri"));
  }
}

//: l'ultimo link creato: il nodo ne tiene solo l'impronta, quindi si mostra
//: UNA volta, subito, invece di sparire con il ridisegno del pannello
let lastLink = null;

async function tabInvites(body, drawerCtl, room, manage) {
  const id = encodeURIComponent(room.room_id);
  if (!manage) {
    body.innerHTML = `<p class="k-note">${escapeHtml(L("Gli inviti li vedono e li creano proprietario e amministratori della stanza.",
      "The room's owner and admins see and create invitations."))}</p>`;
    return;
  }
  const links = await api.get(`/rooms/${id}/invites`);
  body.innerHTML = `<div class="k-list">${(links || []).map((v) => `<div class="k-li"><div>
      <b>${escapeHtml(L("Link da ", "Link for ") + (ROLE_WORD()[v.role] || v.role))}</b>
      <small>${escapeHtml([v.created_at && String(v.created_at).slice(0, 10),
        v.expires_at && L("scade ", "expires ") + new Date(v.expires_at * 1000).toISOString().slice(0, 10),
        L(`usato ${v.uses || 0} volte`, `used ${v.uses || 0} times`), v.state].filter(Boolean).join(" · "))}</small></div>
      <span data-inv="${v.state === "live" ? escapeHtml(v.token_id) : ""}">${v.state === "live" ? "" : tag(v.state === "revoked" ? L("revocato", "revoked") : L("scaduto", "expired"))}</span></div>`).join("")
    || `<div class="k-li"><span class="k-faint">${escapeHtml(L("Nessun link di invito.", "No invitation link."))}</span></div>`}</div>
    <div class="k-form"><select id="k-inv-role"><option value="editor">${escapeHtml(ROLE_WORD().editor)}</option><option value="viewer">${escapeHtml(ROLE_WORD().viewer)}</option></select>
    <select id="k-inv-days"><option value="1">1 ${L("giorno", "day")}</option><option value="7" selected>7 ${L("giorni", "days")}</option><option value="30">30 ${L("giorni", "days")}</option></select></div>
    ${lastLink && lastLink.room === room.room_id ? `<p class="k-note"><b>${escapeHtml(L("Il link, da mandare adesso (non si potrà rivedere):", "The link, to send now (it cannot be shown again):"))}</b><br><code class="k-link">${escapeHtml(lastLink.url)}</code></p>` : ""}
    <p class="k-note">${escapeHtml(L("Il link apre la porta, l'ORCID dice chi è entrato, il ruolo viene dal link. Un link non autentica nessuno.",
      "The link opens the door, the ORCID says who came in, the role comes from the link. A link authenticates nobody."))}</p>`;
  if (lastLink && lastLink.room === room.room_id) lastLink = null;   // mostrato
  body.querySelectorAll("[data-inv]").forEach((slot) => {
    const tokenId = slot.dataset.inv;
    if (!tokenId) return;
    slot.appendChild(button(L("Revoca", "Revoke"), async () => {
      try { await api.del(`/rooms/${id}/invites/${encodeURIComponent(tokenId)}`); toast(L("Link revocato.", "Link revoked.")); }
      catch (error) { toast(error.message, "bad"); }
      drawerCtl.reopen();
    }, "warn"));
  });
  body.querySelector(".k-form").appendChild(button(L("Crea link", "Create link"), async () => {
    const days = Number(body.querySelector("#k-inv-days").value);
    try {
      const made = await api.post(`/rooms/${id}/invites`, { role: body.querySelector("#k-inv-role").value, ttl_seconds: days * 86400 });
      // l'invito porta alla CASA del nodo, che lo accetta e apre la stanza
      const door = new URL(window.location.pathname, window.location.href);
      if (made.token) door.searchParams.set("join", made.token);
      const text = made.token ? door.toString() : "";
      if (text) { try { await navigator.clipboard.writeText(text); } catch { /* shown below */ } }
      lastLink = text ? { room: room.room_id, url: text } : null;
      toast(L("Link creato e copiato.", "Link created and copied."));
    } catch (error) { toast(error.message, "bad"); }
    drawerCtl.reopen();
  }, "pri"));
}

async function tabVisibility(body, drawerCtl, room, manage) {
  const id = encodeURIComponent(room.room_id);
  let access = null;
  try { access = await api.get(`/rooms/${id}/study-access`); } catch (error) { access = null; }
  if (!access) {
    body.innerHTML = `<p class="k-note">${escapeHtml(L("Chi vede lo studio lo leggono soltanto le persone con un ruolo nella stanza.",
      "Only people with a role in the room read who sees the study."))}</p>`;
    return;
  }
  const vis = access.visibility || "restricted";
  const emb = access.embargo || "";
  const word = vis === "public" ? L("Pubblico", "Public") : L("Riservato", "Restricted");
  if (!manage) {
    // READ-ONLY, said as a sentence: a set of disabled radio buttons looks like
    // something one could press (E.D., 30 Oct 2026, on the desk).
    body.innerHTML = `<div class="k-card"><span class="k-k">${escapeHtml(L("Adesso", "Now"))}</span>
      <b>${escapeHtml(word)}</b>${emb ? `<span>${escapeHtml(L("embargo fino al ", "embargo until ") + String(emb).slice(0, 10))}</span>` : ""}</div>
      <p class="k-note">${escapeHtml(L("Lo decide chi amministra la stanza: il proprietario o un amministratore.",
        "It is decided by whoever manages the room: the owner or an admin."))}</p>`;
    return;
  }
  body.innerHTML = `<div class="k-list">
    <label class="k-li"><span><b>${escapeHtml(L("Pubblico", "Public"))}</b><small>${escapeHtml(L("chiunque lo legge, anche senza accedere", "anyone reads it, even without signing in"))}</small></span><input type="radio" name="k-vis" value="public" ${vis === "public" ? "checked" : ""}></label>
    <label class="k-li"><span><b>${escapeHtml(L("Riservato", "Restricted"))}</b><small>${escapeHtml(L("solo chi ha un ruolo nella stanza, dopo l'accesso", "only people with a role in the room, signed in"))}</small></span><input type="radio" name="k-vis" value="restricted" ${vis !== "public" ? "checked" : ""}></label></div>
    <div class="k-form"><label for="k-emb">${escapeHtml(L("Embargo fino al", "Embargo until"))}</label><input id="k-emb" type="date" value="${escapeHtml(String(emb).slice(0, 10))}" style="flex:0 0 auto"></div>
    <p class="k-note">${escapeHtml(L("Finché la data non arriva lo studio resta riservato, qualunque sia la scelta sopra.",
      "Until the date the study stays restricted, whatever the choice above."))}</p>`;
  body.appendChild(button(L("Salva", "Save"), async () => {
    const visibility = body.querySelector('input[name="k-vis"]:checked').value;
    const date = body.querySelector("#k-emb").value;
    try { await api.put(`/rooms/${id}/study-access`, { visibility, embargo: date || null }); toast(L("Salvato.", "Saved.")); }
    catch (error) { toast(error.message, "bad"); }
    drawerCtl.reopen();
  }, "pri"));
}

function tabMemory(body, room, s) {
  body.innerHTML = `<div class="k-grid">
    <div class="k-card"><span class="k-k">${escapeHtml(L("File", "Files"))}</span><span class="k-big">${s.assets ?? "—"}</span>
      <span class="k-faint">${escapeHtml((s.missing || []).length ? L(`${s.missing.length} non nel bucket`, `${s.missing.length} not in the bucket`) : L("tutti presenti", "all present"))}</span></div>
    <div class="k-card"><span class="k-k">${escapeHtml(L("Spazio", "Space"))}</span><span class="k-big">${bytes(s.bytes)}</span>
      <span class="k-faint">${escapeHtml(L("un file in due stanze conta in entrambe", "a file in two rooms counts in both"))}</span></div></div>
    ${(room.missing_refs || []).length ? `<p class="k-note bad">${escapeHtml(L("Il grafo cita un em.json che lo store non ha: ", "The graph names an em.json the store does not hold: ") + room.missing_refs.join(", "))}</p>` : ""}
    <p class="k-note">${escapeHtml(L("I file sono nominati dal loro contenuto: lo stesso file in due stanze occupa spazio una volta sola nel bucket. Il dettaglio file per file è in «Memoria e bucket».",
      "Files are named by their content: the same file in two rooms takes space once in the bucket. File by file, see «Memory and bucket»."))}</p>`;
}

async function tabLife(body, drawerCtl, room, operator = true) {
  const id = encodeURIComponent(room.room_id);
  const owner = room.your_role === "owner";
  body.innerHTML = `
    <div class="k-danger"><h3>${escapeHtml(room.archived_at ? L("Riapri la stanza", "Bring the room back") : L("Archivia la stanza", "Archive the room"))}</h3>
      <p class="k-faint">${escapeHtml(room.archived_at ? L("Torna fra le attive e si può di nuovo scrivere.", "It returns among the active rooms and can be written again.")
        : L("Resta leggibile e citabile, ma nessuno ci scrive più. Si riapre quando serve.", "It stays readable and citable; nobody writes in it. It can be brought back."))}</p>
      <div data-slot="archive"></div></div>
    ${operator ? `<div class="k-danger"><h3>${escapeHtml(L("Un nuovo proprietario", "A new owner"))}</h3>
      <p class="k-faint">${escapeHtml(L("Solo per una stanza che non ha più nessuno che la gestisca: il proprietario non è più sul nodo e non resta un amministratore. Il passaggio resta nel registro del nodo.",
        "Only for a room nobody can manage any more: the owner has left the node and no admin remains. The act is written to the node's log."))}</p>
      <div class="k-form" data-slot="rescue"><input id="k-new-owner" placeholder="ORCID"></div></div>`
    : owner ? `<div class="k-danger"><h3>${escapeHtml(L("Passa la stanza", "Hand the room over"))}</h3>
      <p class="k-faint">${escapeHtml(L("Il nuovo proprietario gestisce anche gli amministratori. Tu resti amministratore.",
        "The new owner also manages the admins. You stay an admin."))}</p>
      <div class="k-form" data-slot="transfer"><input id="k-new-owner" placeholder="ORCID"></div></div>` : ""}
    <div class="k-danger"><h3>${escapeHtml(L("Elimina la stanza", "Delete the room"))}</h3>
      <p class="k-faint">${escapeHtml(L("Toglie la stanza e il suo em.json con tutte le revisioni, il registro delle operazioni, membri e inviti. I file restano nel bucket e, se nessun'altra stanza li cita, diventano orfani. Non si elimina mentre qualcuno è dentro.",
        "Removes the room and its em.json with every revision, the operations log, members and invitations. Files stay in the bucket and become orphans if no other room cites them. Refused while somebody is connected."))}</p>
      <div data-slot="delete"></div></div>`;
  if (!operator && !owner) body.querySelector('[data-slot="delete"]').closest(".k-danger").remove();
  body.querySelector('[data-slot="archive"]').appendChild(button(room.archived_at ? L("Riapri", "Bring back") : L("Archivia", "Archive"), async () => {
    if (!confirmNamed(room.archived_at ? L("la riapertura", "bringing back") : L("l'archiviazione", "archiving"), room.room_id)) return;
    try {
      // l'operatore archivia qualunque stanza; chi la governa, la sua
      if (operator) await api.post(`/admin/rooms/${id}/archive`, { archived: !room.archived_at, confirm_room_id: room.room_id });
      else await api.post(`/rooms/${id}/archive`, { archived: !room.archived_at });
      toast(room.archived_at ? L("Riaperta.", "Brought back.") : L("Archiviata.", "Archived."));
      drawerCtl.close();
    } catch (error) { toast(error.message, "bad"); }
  }));
  body.querySelector('[data-slot="transfer"]')?.appendChild(button(L("Passa", "Hand over"), async () => {
    const orcid = body.querySelector("#k-new-owner").value.trim();
    if (!orcid) return;
    if (!confirmNamed(L("il passaggio della proprietà", "handing the room over"), room.room_id)) return;
    try { await api.put(`/rooms/${id}/members/${encodeURIComponent(orcid)}`, { role: "owner" }); toast(L("Nuovo proprietario.", "New owner.")); drawerCtl.close(); }
    catch (error) { toast(error.message, "bad"); }
  }));
  body.querySelector('[data-slot="rescue"]')?.appendChild(button(L("Passa", "Hand over"), async () => {
    const orcid = body.querySelector("#k-new-owner").value.trim();
    if (!orcid) return;
    try { await api.put(`/admin/rooms/${id}/owner`, { orcid }); toast(L("Nuovo proprietario.", "New owner.")); drawerCtl.close(); }
    catch (error) { toast(error.message, "bad"); }
  }));
  body.querySelector('[data-slot="delete"]')?.appendChild(button(L("Elimina…", "Delete…"), async () => {
    if (!confirmTyped(L("l'eliminazione definitiva della stanza", "deleting the room for good"), room.room_id)) return;
    try { await api.del(`/rooms/${id}`, { confirm: room.room_id }); toast(L("Stanza eliminata.", "Room deleted.")); drawerCtl.close(); }
    catch (error) { toast(error.message, "bad"); }
  }, "warn"));
}

register({ id: "rooms", title: L("Stanze", "Rooms"), render });
