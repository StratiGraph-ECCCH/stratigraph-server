/**
 * MODULE · Cestino — le stanze e i file tolti negli ultimi 30 giorni
 * (E.D., 31 ottobre 2026: «cestino e soglia sul blocco»; fatto il 6 novembre).
 *
 * Togliere una stanza o un file mette nel cestino: da qui si riprendono, com'erano,
 * fino alla data scritta accanto; dopo, il nodo li elimina da sé. «Elimina ora»
 * è il secondo gesto, per chi non vuole aspettare: chiede il nome scritto.
 * Solo per l'operatore del nodo (`GET /v1/admin/trash`).
 */
import { api, confirmTyped, escapeHtml, register } from "../console.js";
import { bytes, button, head, shortRef, toast } from "../kit.js";
import { t } from "../i18n.js";

const day = (iso) => (iso ? String(iso).slice(0, 10) : "—");

async function render(root) {
  const trash = await api.get("/admin/trash");
  root.innerHTML = "";
  head(root, t("trash.title"),
    escapeHtml(t("trash.lead", { days: trash.days, rooms: trash.bulk_rooms, size: bytes(trash.bulk_bytes) })));

  const rooms = document.createElement("section");
  rooms.innerHTML = `<h3>${escapeHtml(t("trash.rooms.title"))} (${trash.rooms.length})</h3>
    <div class="k-tw"><table class="k-table"><thead><tr>
      <th>${t("trash.col.room")}</th><th>${t("trash.col.since")}</th>
      <th>${t("trash.col.by")}</th><th>${t("trash.col.purgeRoom")}</th><th></th></tr></thead>
    <tbody>${trash.rooms.map((r) => `<tr>
      <td><strong>${escapeHtml(r.title || r.room_id)}</strong> <span class="k-faint k-mono">${escapeHtml(r.room_id)}</span></td>
      <td>${day(r.trashed_at)}</td><td class="k-mono">${escapeHtml(r.trashed_by || "—")}</td>
      <td>${day(r.purge_after)}</td>
      <td class="k-acts" data-room="${escapeHtml(r.room_id)}"></td></tr>`).join("")
      || `<tr><td colspan="5" class="k-faint">${escapeHtml(t("trash.rooms.none"))}</td></tr>`}</tbody></table></div>`;
  root.appendChild(rooms);
  rooms.querySelectorAll("[data-room]").forEach((slot) => {
    const id = slot.dataset.room;
    slot.appendChild(button(t("trash.takeBack"), async () => {
      try { await api.post(`/rooms/${encodeURIComponent(id)}/restore`); toast(t("trash.rooms.takenBack")); }
      catch (error) { toast(error.message, "bad"); }
      await render(root);
    }, "pri"));
    slot.appendChild(button(t("trash.rooms.deleteNow"), async () => {
      if (!confirmTyped(t("trash.rooms.deleteNow.confirm"), id)) return;
      try { await api.del(`/rooms/${encodeURIComponent(id)}`, { confirm: id, for_good: true }); toast(t("trash.rooms.deleted")); }
      catch (error) { toast(error.message, "bad"); }
      await render(root);
    }, "warn"));
  });

  const files = document.createElement("section");
  files.innerHTML = `<h3>${escapeHtml(t("trash.files.title"))} (${trash.assets.length} · ${bytes(trash.assets.reduce((n, a) => n + (a.size || 0), 0))})</h3>
    <div class="k-tw"><table class="k-table"><thead><tr>
      <th>${t("trash.col.file")}</th><th class="num">${t("trash.col.size")}</th><th>${t("trash.col.type")}</th>
      <th>${t("trash.col.since")}</th><th>${t("trash.col.purgeFile")}</th><th></th></tr></thead>
    <tbody>${trash.assets.map((a) => `<tr>
      <td class="k-mono" title="${escapeHtml(a.ref)}">${escapeHtml(shortRef(a.ref))}</td>
      <td class="num">${bytes(a.size)}</td><td>${escapeHtml(a.media_type || "—")}</td>
      <td>${day(a.trashed_at)}</td><td>${day(a.purge_after)}</td>
      <td class="k-acts" data-ref="${escapeHtml(a.ref)}"></td></tr>`).join("")
      || `<tr><td colspan="6" class="k-faint">${escapeHtml(t("trash.files.none"))}</td></tr>`}</tbody></table></div>`;
  root.appendChild(files);
  files.querySelectorAll("[data-ref]").forEach((slot) => {
    const ref = slot.dataset.ref;
    slot.appendChild(button(t("trash.takeBack"), async () => {
      try { await api.post(`/admin/assets/${encodeURIComponent(ref)}/restore`); toast(t("trash.files.takenBack")); }
      catch (error) { toast(error.message, "bad"); }
      await render(root);
    }, "pri"));
    slot.appendChild(button(t("trash.files.removeNow"), async () => {
      if (!confirmTyped(t("trash.files.removeNow.confirm"), t("trash.files.removeNow.word"))) return;
      try { await api.del(`/admin/assets/${encodeURIComponent(ref)}?for_good=true`); toast(t("trash.files.removed")); }
      catch (error) { toast(error.message, "bad"); }
      await render(root);
    }, "warn"));
  });
}

register({ id: "trash", title: () => t("trash.title"), render });
