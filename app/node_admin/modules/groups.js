/**
 * MODULE · Gruppi — the teams of the node (30 October 2026).
 *
 * A group is a named list of ORCIDs that can hold a role in a room, managed by
 * whoever created it (`access.py`). Creating one needs the node editor profile
 * (`people.py`). The rooms where a team holds a role are read from the rooms'
 * access lists, as `/v1/admin/rooms` projects them.
 */
import { api, confirmNamed, escapeHtml, register } from "../console.js";
import { button, drawer, head, roleChip, toast } from "../kit.js";
import { t } from "../i18n.js";

async function render(root) {
  const [groups, rooms, me] = await Promise.all([
    api.get("/groups"), api.get("/admin/rooms"), api.get("/admin/whoami"),
  ]);
  root.innerHTML = "";
  head(root, t("groups.title"),
    escapeHtml(t("groups.lead")),
    [button(t("groups.new"), () => newGroup(root), "pri")]);
  const grid = document.createElement("div");
  grid.className = "k-grid";
  grid.innerHTML = groups.map((g) => {
    const where = rooms.filter((r) => (r.groups || {})[g.id]);
    return `<div class="k-card k-click" tabindex="0" data-group="${escapeHtml(g.id)}">
      <span class="k-k">${escapeHtml(t("groups.card.managedBy") + (g.owner || "—"))}</span>
      <b>${escapeHtml(g.name || g.id)}</b>
      <span class="k-faint">${escapeHtml(t("groups.card.count", { people: g.members.length, rooms: where.length }))}</span></div>`;
  }).join("") || `<p class="k-faint">${escapeHtml(t("groups.none"))}</p>`;
  root.appendChild(grid);
  grid.querySelectorAll("[data-group]").forEach((card) => {
    const open = () => openGroup(groups.find((g) => g.id === card.dataset.group), rooms, me, root);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  });
}

async function newGroup(root) {
  const name = window.prompt(t("groups.new.prompt"));
  if (!name) return;
  const id = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
  try {
    await api.put(`/groups/${encodeURIComponent(id)}`, { id, name, members: [] });
    toast(t("groups.new.done"));
  } catch (error) { toast(error.message, "bad"); }
  await render(root);
}

function openGroup(g, rooms, me, root) {
  const mine = !me?.orcid || g.owner === me.orcid;
  drawer({
    title: g.name || g.id, subtitle: g.id,
    onClose: () => void render(root),
    tabs: [
      ["members", t("groups.tab.people"), async (body, d) => {
        body.innerHTML = `${!mine ? `<p class="k-note">${escapeHtml(t("groups.people.onlyCreator"))}</p>` : ""}
          <div class="k-list">${g.members.map((m) => `<div class="k-li"><div><b>${escapeHtml(m)}</b><small>ORCID</small></div><span data-m="${escapeHtml(m)}"></span></div>`).join("")
            || `<div class="k-li"><span class="k-faint">${escapeHtml(t("groups.people.none"))}</span></div>`}</div>
          ${mine ? `<div class="k-form"><input id="k-g-add" placeholder="ORCID"></div>` : ""}`;
        if (!mine) return;
        body.querySelectorAll("[data-m]").forEach((slot) => slot.appendChild(button(t("groups.people.remove"), async () => {
          try { await api.del(`/groups/${encodeURIComponent(g.id)}/members/${encodeURIComponent(slot.dataset.m)}`);
                g.members = g.members.filter((x) => x !== slot.dataset.m); toast(t("groups.people.removed")); }
          catch (error) { toast(error.message, "bad"); }
          d.reopen();
        }, "warn")));
        body.querySelector(".k-form").appendChild(button(t("groups.people.add"), async () => {
          const who = body.querySelector("#k-g-add").value.trim();
          if (!who) return;
          try { const out = await api.put(`/groups/${encodeURIComponent(g.id)}/members/${encodeURIComponent(who)}`); g.members = out.members; toast(t("groups.people.added")); }
          catch (error) { toast(error.message, "bad"); }
          d.reopen();
        }, "pri"));
      }],
      ["rooms", t("groups.tab.rooms"), async (body) => {
        const where = rooms.filter((r) => (r.groups || {})[g.id]);
        body.innerHTML = `<div class="k-list">${where.map((r) => `<div class="k-li"><div><b>${escapeHtml(r.title || r.room_id)}</b><small>${escapeHtml(r.room_id)}</small></div>${roleChip(r.groups[g.id])}</div>`).join("")
          || `<div class="k-li"><span class="k-faint">${escapeHtml(t("groups.rooms.none"))}</span></div>`}</div>
          <p class="k-note">${escapeHtml(t("groups.rooms.note"))}</p>`;
      }],
      ["delete", t("groups.tab.delete"), async (body, d) => {
        body.innerHTML = `<div class="k-danger"><h3>${escapeHtml(t("groups.delete.title"))}</h3>
          <p class="k-faint">${escapeHtml(t("groups.delete.why"))}</p><div data-slot></div></div>`;
        const b = button(t("groups.tab.delete"), async () => {
          if (!confirmNamed(t("groups.delete.confirm"), g.name || g.id)) return;
          try { await api.del(`/groups/${encodeURIComponent(g.id)}`); toast(t("groups.delete.done")); d.close(); }
          catch (error) { toast(error.message, "bad"); }
        }, "warn");
        b.disabled = !mine;
        body.querySelector("[data-slot]").appendChild(b);
      }],
    ],
  });
}

register({ id: "groups", title: () => t("groups.title"), render });
