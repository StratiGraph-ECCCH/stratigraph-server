/**
 * MODULE · Gruppi — the teams of the node (30 October 2026).
 *
 * A group is a named list of ORCIDs that can hold a role in a room, managed by
 * whoever created it (`access.py`). Creating one needs the node editor profile
 * (`people.py`). The rooms where a team holds a role are read from the rooms'
 * access lists, as `/v1/admin/rooms` projects them.
 */
import { api, confirmNamed, escapeHtml, register } from "../console.js";
import { L, button, drawer, head, roleChip, toast } from "../kit.js";

async function render(root) {
  const [groups, rooms, me] = await Promise.all([
    api.get("/groups"), api.get("/admin/rooms"), api.get("/admin/whoami"),
  ]);
  root.innerHTML = "";
  head(root, L("Gruppi", "Groups"),
    escapeHtml(L("Un gruppo è una squadra: gli dai un ruolo in una stanza una volta sola, invece di aggiungere ogni persona in ogni stanza. Lo gestisce chi lo ha creato.",
      "A group is a team: it gets a role in a room once, instead of adding every person to every room. Whoever created it manages it.")),
    [button(L("Nuovo gruppo", "New group"), () => newGroup(root), "pri")]);
  const grid = document.createElement("div");
  grid.className = "k-grid";
  grid.innerHTML = groups.map((g) => {
    const where = rooms.filter((r) => (r.groups || {})[g.id]);
    return `<div class="k-card k-click" tabindex="0" data-group="${escapeHtml(g.id)}">
      <span class="k-k">${escapeHtml(L("gestito da ", "managed by ") + (g.owner || "—"))}</span>
      <b>${escapeHtml(g.name || g.id)}</b>
      <span class="k-faint">${escapeHtml(L(`${g.members.length} persone · ruolo in ${where.length} stanze`, `${g.members.length} people · a role in ${where.length} rooms`))}</span></div>`;
  }).join("") || `<p class="k-faint">${escapeHtml(L("Nessun gruppo su questo nodo.", "No group on this node."))}</p>`;
  root.appendChild(grid);
  grid.querySelectorAll("[data-group]").forEach((card) => {
    const open = () => openGroup(groups.find((g) => g.id === card.dataset.group), rooms, me, root);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  });
}

async function newGroup(root) {
  const name = window.prompt(L("Il nome del gruppo", "The group's name"));
  if (!name) return;
  const id = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
  try {
    await api.put(`/groups/${encodeURIComponent(id)}`, { id, name, members: [] });
    toast(L("Gruppo creato: lo gestisci tu.", "Group created: you manage it."));
  } catch (error) { toast(error.message, "bad"); }
  await render(root);
}

function openGroup(g, rooms, me, root) {
  const mine = !me?.orcid || g.owner === me.orcid;
  drawer({
    title: g.name || g.id, subtitle: g.id,
    onClose: () => void render(root),
    tabs: [
      ["members", L("Persone", "People"), async (body, d) => {
        body.innerHTML = `${!mine ? `<p class="k-note">${escapeHtml(L("Solo chi ha creato il gruppo cambia chi ne fa parte.", "Only the group's creator changes who is in it."))}</p>` : ""}
          <div class="k-list">${g.members.map((m) => `<div class="k-li"><div><b>${escapeHtml(m)}</b><small>ORCID</small></div><span data-m="${escapeHtml(m)}"></span></div>`).join("")
            || `<div class="k-li"><span class="k-faint">${escapeHtml(L("Nessuno ancora.", "Nobody yet."))}</span></div>`}</div>
          ${mine ? `<div class="k-form"><input id="k-g-add" placeholder="ORCID"></div>` : ""}`;
        if (!mine) return;
        body.querySelectorAll("[data-m]").forEach((slot) => slot.appendChild(button(L("Togli", "Remove"), async () => {
          try { await api.del(`/groups/${encodeURIComponent(g.id)}/members/${encodeURIComponent(slot.dataset.m)}`);
                g.members = g.members.filter((x) => x !== slot.dataset.m); toast(L("Tolto dalla squadra.", "Removed from the team.")); }
          catch (error) { toast(error.message, "bad"); }
          d.reopen();
        }, "warn")));
        body.querySelector(".k-form").appendChild(button(L("Aggiungi", "Add"), async () => {
          const who = body.querySelector("#k-g-add").value.trim();
          if (!who) return;
          try { const out = await api.put(`/groups/${encodeURIComponent(g.id)}/members/${encodeURIComponent(who)}`); g.members = out.members; toast(L("Aggiunto.", "Added.")); }
          catch (error) { toast(error.message, "bad"); }
          d.reopen();
        }, "pri"));
      }],
      ["rooms", L("Stanze", "Rooms"), async (body) => {
        const where = rooms.filter((r) => (r.groups || {})[g.id]);
        body.innerHTML = `<div class="k-list">${where.map((r) => `<div class="k-li"><div><b>${escapeHtml(r.title || r.room_id)}</b><small>${escapeHtml(r.room_id)}</small></div>${roleChip(r.groups[g.id])}</div>`).join("")
          || `<div class="k-li"><span class="k-faint">${escapeHtml(L("Nessuna stanza ancora.", "No room yet."))}</span></div>`}</div>
          <p class="k-note">${escapeHtml(L("Il ruolo si dà dalla stanza, in «Persone e ruoli». Togliere qualcuno dal gruppo gli toglie solo i ruoli che aveva tramite il gruppo.",
            "The role is given from the room, in «People and roles». Removing somebody from the group removes only the roles they held through it."))}</p>`;
      }],
      ["delete", L("Elimina", "Delete"), async (body, d) => {
        body.innerHTML = `<div class="k-danger"><h3>${escapeHtml(L("Elimina il gruppo", "Delete the group"))}</h3>
          <p class="k-faint">${escapeHtml(L("I ruoli dati al gruppo nelle stanze smettono di valere.", "The roles given to the group in rooms stop counting."))}</p><div data-slot></div></div>`;
        const b = button(L("Elimina", "Delete"), async () => {
          if (!confirmNamed(L("l'eliminazione del gruppo", "deleting the group"), g.name || g.id)) return;
          try { await api.del(`/groups/${encodeURIComponent(g.id)}`); toast(L("Gruppo eliminato.", "Group deleted.")); d.close(); }
          catch (error) { toast(error.message, "bad"); }
        }, "warn");
        b.disabled = !mine;
        body.querySelector("[data-slot]").appendChild(b);
      }],
    ],
  });
}

register({ id: "groups", title: L("Gruppi", "Groups"), render });
