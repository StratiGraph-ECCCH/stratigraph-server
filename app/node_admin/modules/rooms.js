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
import { RANK, ROLE_WORD, button, bytes, chips, drawer, head, roleChip, tag, toast } from "../kit.js";
import { t } from "../i18n.js";

let filter = "active";
let query = "";
//: LE STANZE SCELTE per un'azione in blocco (31 ottobre: «voglio anche le
//: operazioni in batch su più stanze»). Sopravvive al cambio di filtro: si
//: sceglie in «Attive» e in «Implicite», e si agisce una volta.
const picked = new Set();

async function render(root) {
  const [all, storage] = await Promise.all([
    api.get("/admin/rooms"),
    api.get("/admin/storage").catch(() => ({ rooms: [] })),
  ]);
  const space = Object.fromEntries((storage.rooms || []).map((r) => [r.room_id, r]));
  //: quelle nel cestino stanno nel modulo «Cestino», non qui
  const rooms = all.filter((r) => !r.trashed_at);
  root.innerHTML = "";
  const implicit = rooms.filter((r) => r.implicit);
  const counts = {
    active: rooms.filter((r) => !r.implicit && !r.archived_at).length,
    archived: rooms.filter((r) => r.archived_at).length,
    implicit: implicit.length,
  };
  head(root, t("rooms.node.title"),
    escapeHtml(t("rooms.node.lead")));

  if (implicit.length) {
    const banner = document.createElement("div");
    banner.className = "k-banner";
    banner.innerHTML = `<span>${escapeHtml(t("rooms.implicit.note", { n: implicit.length }))}</span>`;
    banner.appendChild(button(t("rooms.implicit.delete"),
      () => void deleteMany(implicit, root), "warn"));
    root.appendChild(banner);
  }

  const bar = chips([
    ["active", t("rooms.filter.active"), counts.active],
    ["archived", t("rooms.filter.archived"), counts.archived],
    ["implicit", t("rooms.filter.implicit"), counts.implicit],
  ], filter, (k) => { filter = k; void render(root); });
  const search = document.createElement("input");
  search.type = "search";
  search.className = "k-search";
  search.placeholder = t("rooms.search");
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
    <th class="k-pick"><input type="checkbox" id="k-pick-all" aria-label="${escapeHtml(t("rooms.list.pickAll"))}"></th>
    <th>${t("rooms.col.room")}</th><th>${t("rooms.col.owner")}</th>
    <th>${t("rooms.col.people")}</th><th>${t("rooms.col.yourRole")}</th>
    <th class="num">${t("rooms.col.files")}</th><th class="num">${t("rooms.col.space")}</th>
    <th>${t("rooms.col.created")}</th></tr></thead><tbody></tbody></table>`;
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
        <td class="k-pick"><input type="checkbox" data-pick="${escapeHtml(r.room_id)}" ${picked.has(r.room_id) ? "checked" : ""} aria-label="${escapeHtml(t("rooms.list.pick") + " " + r.room_id)}"></td>
        <td class="k-title"><b>${escapeHtml(r.title || r.room_id)}</b><small>${escapeHtml(r.room_id)}</small></td>
        <td class="k-mono">${escapeHtml(r.owner || t("rooms.list.nobody"))}</td>
        <td>${people}${Object.keys(r.groups || {}).length ? ` <span class="k-faint">· ${Object.keys(r.groups).length} ${t("rooms.list.groups")}</span>` : ""}</td>
        <td>${roleChip(r.your_role)}</td>
        <td class="num">${s.assets ?? "—"}${(r.missing_refs || []).length ? " " + tag("!", "warn") : ""}</td>
        <td class="num">${bytes(s.bytes)}</td>
        <td class="k-mono">${r.archived_at ? tag(t("rooms.tag.archived")) : escapeHtml(String(r.created_at || "").slice(0, 10))}</td></tr>`;
    }).join("") || `<tr><td colspan="8" class="k-faint">${escapeHtml(t("rooms.list.none"))}</td></tr>`;
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
    batch.innerHTML = `<span><b>${chosen.length}</b> ${escapeHtml(chosen.length === 1 ? t("rooms.batch.picked.one") : t("rooms.batch.picked.many"))}</span>`;
    const acts = document.createElement("span");
    acts.className = "k-batch-acts";
    if (live.length) acts.appendChild(button(t("rooms.batch.archive", { n: live.length }),
      () => void archiveMany(live, true, root)));
    if (gone.length) acts.appendChild(button(t("rooms.batch.restore", { n: gone.length }),
      () => void archiveMany(gone, false, root)));
    acts.appendChild(button(t("rooms.batch.delete", { n: chosen.length }),
      () => void deleteMany(chosen, root), "warn"));
    acts.appendChild(button(t("rooms.batch.clear"), () => { picked.clear(); drawRows(); }));
    batch.appendChild(acts);
  }
  drawRows();
}

/** UNA PER VOLTA ERA LENTO E MUTO (31 ottobre: 36 stanze, ~0,4 s l'una, e
 *  nessun segno di vita — la seconda volta si è premuto di nuovo). Sei alla
 *  volta, e un contatore che dice a che punto si è. */
export async function inPool(list, work, say) {
  const POOL = 6;
  let next = 0, done = 0;
  const refused = [];
  const note = document.createElement("div");
  note.className = "k-banner k-progress";
  note.setAttribute("role", "status");
  document.querySelector(".k-batch, .k-banner")?.before(note);
  note.scrollIntoView?.({ block: "nearest" });
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
    ? t("rooms.archive.confirm", { n })
    : t("rooms.restore.confirm", { n });
  if (!confirmTyped(what, archived ? t("rooms.archive.word") : t("rooms.restore.word"))) return;
  const { done, refused } = await inPool(list,
    (r) => api.post(`/admin/rooms/${encodeURIComponent(r.room_id)}/archive`,
                    { archived, confirm_room_id: r.room_id }),
    (d, n) => archived ? t("rooms.archive.progress", { d, n })
                       : t("rooms.restore.progress", { d, n }));
  for (const r of list) picked.delete(r.room_id);
  toast((archived ? t("rooms.archive.done", { done })
                  : t("rooms.restore.done", { done }))
        + (refused.length ? " " + t("rooms.batch.refused", { n: refused.length }) : ""),
        refused.length ? "bad" : "");
  if (refused.length) console.warn(refused.join("\n"));
  await render(root);
}

async function deleteMany(list, root) {
  const n = list.length;
  const names = list.slice(0, 8).map((r) => r.room_id).join(", ") + (n > 8 ? ` … (+${n - 8})` : "");
  //: IL CESTINO (6 nov 2026): togliere mette nel cestino per trenta giorni,
  //: da cui si riprende; oltre la soglia sul blocco la parola cambia e il
  //: nodo riceve la conferma esplicita (`bulk=true`)
  const limit = await bulkRooms();
  const bulk = n > limit;
  const word = bulk ? t("rooms.trash.bulkWord", { n }) : t("rooms.trash.word");
  if (!confirmTyped(bulk
    ? t("rooms.trash.bulkConfirm", { n, names, limit })
    : t("rooms.trash.confirm", { n, names }), word)) return;
  const q = bulk ? "?bulk=true" : "";
  const { done, refused } = await inPool(list,
    (r) => api.del(`/rooms/${encodeURIComponent(r.room_id)}${q}`, { confirm: r.room_id }),
    (d, n) => t("rooms.trash.progress", { d, n }));
  for (const r of list) picked.delete(r.room_id);
  toast(t("rooms.trash.done", { done }) + (refused.length ? " " + t("rooms.batch.refused", { n: refused.length }) : ""),
    refused.length ? "bad" : "");
  if (refused.length) console.warn(refused.join("\n"));
  await render(root);
}

/** La soglia del nodo, chiesta una volta: 20 se il nodo non risponde. */
let _bulkRooms = 0;
async function bulkRooms() {
  if (!_bulkRooms) {
    try { _bulkRooms = (await api.get("/admin/trash")).bulk_rooms || 20; }
    catch { _bulkRooms = 20; }
  }
  return _bulkRooms;
}

export function openRoom(room, space, root, { operator = true, onClose = null } = {}) {
  const manage = ["owner", "admin"].includes(room.your_role);
  drawer({
    title: room.title || room.room_id,
    subtitle: room.room_id,
    chips: [room.archived_at ? tag(t("rooms.tag.archived")) : "",
            room.implicit ? tag(t("rooms.tag.implicit"), "warn") : "",
            `<span class="k-faint">${escapeHtml(t("rooms.drawer.yourRole"))}</span>`, roleChip(room.your_role)].join(" "),
    onClose: onClose || (() => void render(root)),
    tabs: [
      ["people", t("rooms.tab.people"), (b, d) => tabPeople(b, d, room, manage)],
      ["invites", t("rooms.tab.invites"), (b, d) => tabInvites(b, d, room, manage)],
      ["vis", t("rooms.tab.visibility"), (b, d) => tabVisibility(b, d, room, manage)],
      operator ? ["mem", t("rooms.tab.memory"), (b) => tabMemory(b, room, space[room.room_id] || {})] : null,
      (operator || manage) ? ["life", t("rooms.tab.lifecycle"), (b, d) => tabLife(b, d, room, operator)] : null,
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
    ${!manage ? `<p class="k-note">${escapeHtml(t("rooms.people.lead"))}</p>` : ""}
    <div class="k-list">${rows.map((x) => {
      const choices = ["admin", "editor", "viewer"].filter((r) => canSet(x.role, r));
      const sel = x.role !== "owner" && manage && choices.length && canSet(x.role, x.role)
        ? `<select data-who="${escapeHtml(x.kind + ":" + x.id)}" aria-label="${escapeHtml(x.id)}">${choices.map((r) =>
            `<option value="${r}" ${r === x.role ? "selected" : ""}>${escapeHtml(ROLE_WORD()[r])}</option>`).join("")}
            <option value="">${escapeHtml(t("rooms.people.remove"))}</option></select>`
        : roleChip(x.role);
      return `<div class="k-li"><div><b>${escapeHtml(x.kind === "g" ? t("rooms.people.group") + x.id : x.id)}</b>
        <small>${escapeHtml(x.kind === "g" ? t("rooms.people.team") : "ORCID")}</small></div>${sel}</div>`;
    }).join("") || `<div class="k-li"><span class="k-faint">${escapeHtml(t("rooms.people.none"))}</span></div>`}</div>
    ${manage ? `<div class="k-form"><input id="k-add" placeholder="${escapeHtml(t("rooms.people.placeholder"))}">
      <select id="k-add-role">${["admin", "editor", "viewer"].filter((r) => canSet("viewer", r)).map((r) =>
        `<option value="${r}" ${r === "editor" ? "selected" : ""}>${escapeHtml(ROLE_WORD()[r])}</option>`).join("")}</select></div>` : ""}
    <p class="k-note">${escapeHtml(t("rooms.people.rule"))}</p>`;
  body.querySelectorAll("select[data-who]").forEach((sel) => sel.addEventListener("change", async () => {
    const [kind, who] = sel.dataset.who.split(":");
    const path = kind === "g" ? `/rooms/${id}/groups/${encodeURIComponent(who)}` : `/rooms/${id}/members/${encodeURIComponent(who)}`;
    try {
      if (!sel.value) await api.del(path); else await api.put(path, { role: sel.value });
      toast(sel.value ? t("rooms.people.now", { role: ROLE_WORD()[sel.value] }) : t("rooms.people.removed"));
    } catch (error) { toast(error.message, "bad"); }
    drawerCtl.reopen();
  }));
  if (manage) {
    const form = body.querySelector(".k-form");
    form.appendChild(button(t("rooms.people.add"), async () => {
      const who = body.querySelector("#k-add").value.trim();
      const role = body.querySelector("#k-add-role").value;
      if (!who) return;
      const isOrcid = /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/i.test(who);
      const path = isOrcid ? `/rooms/${id}/members/${encodeURIComponent(who)}` : `/rooms/${id}/groups/${encodeURIComponent(who)}`;
      try { await api.put(path, { role }); toast(t("rooms.people.added")); }
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
    body.innerHTML = `<p class="k-note">${escapeHtml(t("rooms.invites.who"))}</p>`;
    return;
  }
  const links = await api.get(`/rooms/${id}/invites`);
  body.innerHTML = `<div class="k-list">${(links || []).map((v) => `<div class="k-li"><div>
      <b>${escapeHtml(t("rooms.invites.linkFor") + (ROLE_WORD()[v.role] || v.role))}</b>
      <small>${escapeHtml([v.created_at && String(v.created_at).slice(0, 10),
        v.expires_at && t("rooms.invites.expires") + new Date(v.expires_at * 1000).toISOString().slice(0, 10),
        t("rooms.invites.used", { n: v.uses || 0 }), v.state].filter(Boolean).join(" · "))}</small></div>
      <span data-inv="${v.state === "live" ? escapeHtml(v.token_id) : ""}">${v.state === "live" ? "" : tag(v.state === "revoked" ? t("rooms.invites.revoked") : t("rooms.invites.expired"))}</span></div>`).join("")
    || `<div class="k-li"><span class="k-faint">${escapeHtml(t("rooms.invites.none"))}</span></div>`}</div>
    <div class="k-form"><select id="k-inv-role"><option value="editor">${escapeHtml(ROLE_WORD().editor)}</option><option value="viewer">${escapeHtml(ROLE_WORD().viewer)}</option></select>
    <select id="k-inv-days"><option value="1">1 ${t("rooms.invites.day")}</option><option value="7" selected>7 ${t("rooms.invites.days")}</option><option value="30">30 ${t("rooms.invites.days")}</option></select></div>
    ${lastLink && lastLink.room === room.room_id ? `<p class="k-note"><b>${escapeHtml(t("rooms.invites.sendNow"))}</b><br><code class="k-link">${escapeHtml(lastLink.url)}</code></p>` : ""}
    <p class="k-note">${escapeHtml(t("rooms.invites.rule"))}</p>`;
  if (lastLink && lastLink.room === room.room_id) lastLink = null;   // mostrato
  body.querySelectorAll("[data-inv]").forEach((slot) => {
    const tokenId = slot.dataset.inv;
    if (!tokenId) return;
    slot.appendChild(button(t("rooms.invites.revoke"), async () => {
      try { await api.del(`/rooms/${id}/invites/${encodeURIComponent(tokenId)}`); toast(t("rooms.invites.revokedDone")); }
      catch (error) { toast(error.message, "bad"); }
      drawerCtl.reopen();
    }, "warn"));
  });
  body.querySelector(".k-form").appendChild(button(t("rooms.invites.create"), async () => {
    const days = Number(body.querySelector("#k-inv-days").value);
    try {
      const made = await api.post(`/rooms/${id}/invites`, { role: body.querySelector("#k-inv-role").value, ttl_seconds: days * 86400 });
      // l'invito porta alla CASA del nodo, che lo accetta e apre la stanza
      const door = new URL(window.location.pathname, window.location.href);
      if (made.token) door.searchParams.set("join", made.token);
      const text = made.token ? door.toString() : "";
      if (text) { try { await navigator.clipboard.writeText(text); } catch { /* shown below */ } }
      lastLink = text ? { room: room.room_id, url: text } : null;
      toast(t("rooms.invites.created"));
    } catch (error) { toast(error.message, "bad"); }
    drawerCtl.reopen();
  }, "pri"));
}

async function tabVisibility(body, drawerCtl, room, manage) {
  const id = encodeURIComponent(room.room_id);
  let access = null;
  try { access = await api.get(`/rooms/${id}/study-access`); } catch (error) { access = null; }
  if (!access) {
    body.innerHTML = `<p class="k-note">${escapeHtml(t("rooms.visibility.onlyMembers"))}</p>`;
    return;
  }
  const vis = access.visibility || "restricted";
  const emb = access.embargo || "";
  const word = vis === "public" ? t("rooms.visibility.public") : t("rooms.visibility.restricted");
  if (!manage) {
    // READ-ONLY, said as a sentence: a set of disabled radio buttons looks like
    // something one could press (E.D., 30 Oct 2026, on the desk).
    body.innerHTML = `<div class="k-card"><span class="k-k">${escapeHtml(t("rooms.visibility.now"))}</span>
      <b>${escapeHtml(word)}</b>${emb ? `<span>${escapeHtml(t("rooms.visibility.embargoUntil") + String(emb).slice(0, 10))}</span>` : ""}</div>
      <p class="k-note">${escapeHtml(t("rooms.visibility.whoDecides"))}</p>`;
    return;
  }
  body.innerHTML = `<div class="k-list">
    <label class="k-li"><span><b>${escapeHtml(t("rooms.visibility.public"))}</b><small>${escapeHtml(t("rooms.visibility.public.hint"))}</small></span><input type="radio" name="k-vis" value="public" ${vis === "public" ? "checked" : ""}></label>
    <label class="k-li"><span><b>${escapeHtml(t("rooms.visibility.restricted"))}</b><small>${escapeHtml(t("rooms.visibility.restricted.hint"))}</small></span><input type="radio" name="k-vis" value="restricted" ${vis !== "public" ? "checked" : ""}></label></div>
    <div class="k-form"><label for="k-emb">${escapeHtml(t("rooms.visibility.embargo"))}</label><input id="k-emb" type="date" value="${escapeHtml(String(emb).slice(0, 10))}" style="flex:0 0 auto"></div>
    <p class="k-note">${escapeHtml(t("rooms.visibility.embargo.hint"))}</p>`;
  body.appendChild(button(t("rooms.visibility.save"), async () => {
    const visibility = body.querySelector('input[name="k-vis"]:checked').value;
    const date = body.querySelector("#k-emb").value;
    try { await api.put(`/rooms/${id}/study-access`, { visibility, embargo: date || null }); toast(t("rooms.visibility.saved")); }
    catch (error) { toast(error.message, "bad"); }
    drawerCtl.reopen();
  }, "pri"));
}

function tabMemory(body, room, s) {
  body.innerHTML = `<div class="k-grid">
    <div class="k-card"><span class="k-k">${escapeHtml(t("rooms.memory.files"))}</span><span class="k-big">${s.assets ?? "—"}</span>
      <span class="k-faint">${escapeHtml((s.missing || []).length ? t("rooms.memory.missing", { n: s.missing.length }) : t("rooms.memory.allPresent"))}</span></div>
    <div class="k-card"><span class="k-k">${escapeHtml(t("rooms.memory.space"))}</span><span class="k-big">${bytes(s.bytes)}</span>
      <span class="k-faint">${escapeHtml(t("rooms.memory.spaceHint"))}</span></div></div>
    ${(room.missing_refs || []).length ? `<p class="k-note bad">${escapeHtml(t("rooms.memory.noDocument") + room.missing_refs.join(", "))}</p>` : ""}
    <p class="k-note">${escapeHtml(t("rooms.memory.note"))}</p>`;
}

async function tabLife(body, drawerCtl, room, operator = true) {
  const id = encodeURIComponent(room.room_id);
  const owner = room.your_role === "owner";
  body.innerHTML = `
    <div class="k-danger"><h3>${escapeHtml(room.archived_at ? t("rooms.life.bringBack.title") : t("rooms.life.archive.title"))}</h3>
      <p class="k-faint">${escapeHtml(room.archived_at ? t("rooms.life.bringBack.why")
        : t("rooms.life.archive.why"))}</p>
      <div data-slot="archive"></div></div>
    ${operator ? `<div class="k-danger"><h3>${escapeHtml(t("rooms.life.rescue.title"))}</h3>
      <p class="k-faint">${escapeHtml(t("rooms.life.rescue.why"))}</p>
      <div class="k-form" data-slot="rescue"><input id="k-new-owner" placeholder="ORCID"></div></div>`
    : owner ? `<div class="k-danger"><h3>${escapeHtml(t("rooms.life.handOver.title"))}</h3>
      <p class="k-faint">${escapeHtml(t("rooms.life.handOver.why"))}</p>
      <div class="k-form" data-slot="transfer"><input id="k-new-owner" placeholder="ORCID"></div></div>` : ""}
    <div class="k-danger"><h3>${escapeHtml(t("rooms.life.trash.title"))}</h3>
      <p class="k-faint">${escapeHtml(t("rooms.life.trash.why"))}</p>
      <div data-slot="delete"></div></div>`;
  if (!operator && !owner) body.querySelector('[data-slot="delete"]').closest(".k-danger").remove();
  body.querySelector('[data-slot="archive"]').appendChild(button(room.archived_at ? t("rooms.life.bringBack") : t("rooms.life.archive"), async () => {
    if (!confirmNamed(room.archived_at ? t("rooms.life.bringBack.confirm") : t("rooms.life.archive.confirm"), room.room_id)) return;
    try {
      // l'operatore archivia qualunque stanza; chi la governa, la sua
      if (operator) await api.post(`/admin/rooms/${id}/archive`, { archived: !room.archived_at, confirm_room_id: room.room_id });
      else await api.post(`/rooms/${id}/archive`, { archived: !room.archived_at });
      toast(room.archived_at ? t("rooms.life.bringBack.done") : t("rooms.life.archive.done"));
      drawerCtl.close();
    } catch (error) { toast(error.message, "bad"); }
  }));
  body.querySelector('[data-slot="transfer"]')?.appendChild(button(t("rooms.life.handOver"), async () => {
    const orcid = body.querySelector("#k-new-owner").value.trim();
    if (!orcid) return;
    if (!confirmNamed(t("rooms.life.handOver.confirm"), room.room_id)) return;
    try { await api.put(`/rooms/${id}/members/${encodeURIComponent(orcid)}`, { role: "owner" }); toast(t("rooms.life.handOver.done")); drawerCtl.close(); }
    catch (error) { toast(error.message, "bad"); }
  }));
  body.querySelector('[data-slot="rescue"]')?.appendChild(button(t("rooms.life.handOver"), async () => {
    const orcid = body.querySelector("#k-new-owner").value.trim();
    if (!orcid) return;
    try { await api.put(`/admin/rooms/${id}/owner`, { orcid }); toast(t("rooms.life.handOver.done")); drawerCtl.close(); }
    catch (error) { toast(error.message, "bad"); }
  }));
  body.querySelector('[data-slot="delete"]')?.appendChild(button(t("rooms.life.trash"), async () => {
    if (!confirmNamed(t("rooms.life.trash.confirm"), room.room_id)) return;
    try {
      await api.del(`/rooms/${id}`, { confirm: room.room_id });
      toast(t("rooms.life.trash.done"));
      drawerCtl.close();
    } catch (error) { toast(error.message, "bad"); }
  }, "warn"));
}

register({ id: "rooms", title: () => t("rooms.nav"), render });
