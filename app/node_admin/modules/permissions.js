/**
 * MODULE · Permessi — who may do what, room by room, at a glance (30 Oct 2026).
 *
 * People (or groups) down, active rooms across. A cell is the EFFECTIVE role —
 * the highest of owner, a direct grant and every group grant, the rule
 * `access.py` writes — and a dashed border says it comes from a group. Read
 * only: roles are changed from the room, by whoever manages it.
 */
import { api, escapeHtml, register } from "../console.js";
import { L, ROLE_WORD, effective } from "../kit.js";

let rowsAre = "people";
const LETTER = () => ({ owner: L("P", "O"), admin: "A", editor: "E", viewer: L("L", "R") });

async function render(root) {
  const [rooms, groupList, people] = await Promise.all([
    api.get("/admin/rooms"), api.get("/groups"), api.get("/admin/people").catch(() => ({ people: [] })),
  ]);
  const groups = Object.fromEntries(groupList.map((g) => [g.id, g]));
  const names = Object.fromEntries((people.people || []).map((p) => [p.orcid, p.name]));
  const active = rooms.filter((r) => !r.implicit && !r.archived_at);
  const everybody = [...new Set(active.flatMap((r) => [r.owner, ...(r.members || []).map((m) => m.orcid),
    ...Object.keys(r.groups || {}).flatMap((g) => groups[g]?.members || [])]).values())].filter(Boolean).sort();
  root.innerHTML = `
    <div class="k-head"><div><h1>${escapeHtml(L("Permessi", "Permissions"))}</h1>
      <p class="k-lead">${escapeHtml(L("Chi può fare cosa nelle stanze attive. Il bordo tratteggiato dice che il ruolo arriva da un gruppo. I ruoli si cambiano dalla stanza.",
        "Who may do what in the active rooms. A dashed border says the role comes from a group. Roles are changed from the room."))}</p></div>
      <div class="k-bar"><button class="k-chip" data-rows="people" aria-pressed="${rowsAre === "people"}">${escapeHtml(L("Persone", "People"))}</button>
        <button class="k-chip" data-rows="groups" aria-pressed="${rowsAre === "groups"}">${escapeHtml(L("Gruppi", "Groups"))}</button></div></div>
    <div class="k-legend">${["owner", "admin", "editor", "viewer"].map((r) => `<span><span class="k-cell ${r}">${LETTER()[r]}</span>${escapeHtml(ROLE_WORD()[r])}</span>`).join("")}
      <span><span class="k-cell editor via">E</span>${escapeHtml(L("tramite gruppo", "through a group"))}</span></div>`;
  root.querySelectorAll("[data-rows]").forEach((b) => b.addEventListener("click", () => { rowsAre = b.dataset.rows; void render(root); }));
  if (!active.length) { root.insertAdjacentHTML("beforeend", `<p class="k-faint">${escapeHtml(L("Nessuna stanza attiva.", "No active room."))}</p>`); return; }
  const rows = rowsAre === "groups"
    ? groupList.map((g) => ({ id: g.id, name: g.name || g.id, sub: L(`${g.members.length} persone`, `${g.members.length} people`), group: true }))
    : everybody.map((o) => ({ id: o, name: names[o] || o, sub: names[o] ? o : "ORCID" }));
  const cell = (row, room) => {
    let role = null, via = null;
    if (row.group) role = (room.groups || {})[row.id] || null;
    else { const e = effective(row.id, room, groups); if (e) { role = e.role; via = e.via; } }
    const title = `${row.name} — ${room.title || room.room_id}: ${role ? ROLE_WORD()[role] + (via ? ` (${L("tramite", "through")} ${via})` : "") : L("nessun ruolo", "no role")}`;
    return `<td><span class="k-cell ${role || ""}${via ? " via" : ""}" title="${escapeHtml(title)}">${role ? LETTER()[role] : "·"}</span></td>`;
  };
  const box = document.createElement("div");
  box.className = "k-mx";
  box.innerHTML = `<table><thead><tr><th class="who">${escapeHtml(rowsAre === "groups" ? L("Gruppo", "Group") : L("Persona", "Person"))}</th>
    ${active.map((r) => `<th class="rot" title="${escapeHtml(r.title || r.room_id)}"><span>${escapeHtml(r.title || r.room_id)}</span></th>`).join("")}</tr></thead>
    <tbody>${rows.map((row) => `<tr><td class="who k-title"><b>${escapeHtml(row.name)}</b><small>${escapeHtml(row.sub)}</small></td>${active.map((r) => cell(row, r)).join("")}</tr>`).join("")
      || `<tr><td class="who k-faint">${escapeHtml(L("Nessuno.", "Nobody."))}</td></tr>`}</tbody></table>`;
  root.appendChild(box);
}

register({ id: "permissions", title: L("Permessi", "Permissions"), render });
