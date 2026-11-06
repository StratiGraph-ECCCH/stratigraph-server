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
import { L, bytes, button, head, shortRef, toast } from "../kit.js";

const day = (iso) => (iso ? String(iso).slice(0, 10) : "—");

async function render(root) {
  const trash = await api.get("/admin/trash");
  root.innerHTML = "";
  head(root, L("Cestino", "Trash"),
    escapeHtml(L(`Le stanze e i file tolti di recente. Si riprendono com'erano per ${trash.days} giorni; poi il nodo li elimina da sé. Oltre ${trash.bulk_rooms} stanze o ${bytes(trash.bulk_bytes)} in un'ora, il nodo chiede una conferma in più.`,
      `Rooms and files removed recently. They come back as they were for ${trash.days} days; then the node deletes them on its own. Over ${trash.bulk_rooms} rooms or ${bytes(trash.bulk_bytes)} in an hour, the node asks for one more confirmation.`)));

  const rooms = document.createElement("section");
  rooms.innerHTML = `<h3>${escapeHtml(L("Stanze", "Rooms"))} (${trash.rooms.length})</h3>
    <div class="k-tw"><table class="k-table"><thead><tr>
      <th>${L("Stanza", "Room")}</th><th>${L("Nel cestino dal", "In the trash since")}</th>
      <th>${L("Tolta da", "Removed by")}</th><th>${L("Il nodo la elimina il", "The node deletes it on")}</th><th></th></tr></thead>
    <tbody>${trash.rooms.map((r) => `<tr>
      <td><strong>${escapeHtml(r.title || r.room_id)}</strong> <span class="k-faint k-mono">${escapeHtml(r.room_id)}</span></td>
      <td>${day(r.trashed_at)}</td><td class="k-mono">${escapeHtml(r.trashed_by || "—")}</td>
      <td>${day(r.purge_after)}</td>
      <td class="k-acts" data-room="${escapeHtml(r.room_id)}"></td></tr>`).join("")
      || `<tr><td colspan="5" class="k-faint">${escapeHtml(L("Nessuna stanza nel cestino.", "No room in the trash."))}</td></tr>`}</tbody></table></div>`;
  root.appendChild(rooms);
  rooms.querySelectorAll("[data-room]").forEach((slot) => {
    const id = slot.dataset.room;
    slot.appendChild(button(L("Riprendi", "Take back"), async () => {
      try { await api.post(`/rooms/${encodeURIComponent(id)}/restore`); toast(L("Stanza ripresa, com'era.", "Room taken back, as it was.")); }
      catch (error) { toast(error.message, "bad"); }
      await render(root);
    }, "pri"));
    slot.appendChild(button(L("Elimina ora…", "Delete now…"), async () => {
      if (!confirmTyped(L("l'eliminazione definitiva, adesso, della stanza: em.json, revisioni, membri e inviti non tornano", "deleting the room for good, now: em.json, revisions, members and invitations do not come back"), id)) return;
      try { await api.del(`/rooms/${encodeURIComponent(id)}`, { confirm: id, for_good: true }); toast(L("Stanza eliminata.", "Room deleted.")); }
      catch (error) { toast(error.message, "bad"); }
      await render(root);
    }, "warn"));
  });

  const files = document.createElement("section");
  files.innerHTML = `<h3>${escapeHtml(L("File", "Files"))} (${trash.assets.length} · ${bytes(trash.assets.reduce((n, a) => n + (a.size || 0), 0))})</h3>
    <div class="k-tw"><table class="k-table"><thead><tr>
      <th>${L("File", "File")}</th><th class="num">${L("Dimensione", "Size")}</th><th>${L("Tipo", "Type")}</th>
      <th>${L("Nel cestino dal", "In the trash since")}</th><th>${L("Il nodo lo toglie il", "The node removes it on")}</th><th></th></tr></thead>
    <tbody>${trash.assets.map((a) => `<tr>
      <td class="k-mono" title="${escapeHtml(a.ref)}">${escapeHtml(shortRef(a.ref))}</td>
      <td class="num">${bytes(a.size)}</td><td>${escapeHtml(a.media_type || "—")}</td>
      <td>${day(a.trashed_at)}</td><td>${day(a.purge_after)}</td>
      <td class="k-acts" data-ref="${escapeHtml(a.ref)}"></td></tr>`).join("")
      || `<tr><td colspan="6" class="k-faint">${escapeHtml(L("Nessun file nel cestino.", "No file in the trash."))}</td></tr>`}</tbody></table></div>`;
  root.appendChild(files);
  files.querySelectorAll("[data-ref]").forEach((slot) => {
    const ref = slot.dataset.ref;
    slot.appendChild(button(L("Riprendi", "Take back"), async () => {
      try { await api.post(`/admin/assets/${encodeURIComponent(ref)}/restore`); toast(L("File ripreso.", "File taken back.")); }
      catch (error) { toast(error.message, "bad"); }
      await render(root);
    }, "pri"));
    slot.appendChild(button(L("Togli ora…", "Remove now…"), async () => {
      if (!confirmTyped(L("la rimozione definitiva, adesso, di questi byte, che non tornano", "removing these bytes for good, now: they do not come back"), L("TOGLI", "REMOVE"))) return;
      try { await api.del(`/admin/assets/${encodeURIComponent(ref)}?for_good=true`); toast(L("Tolto dal bucket.", "Removed from the bucket.")); }
      catch (error) { toast(error.message, "bad"); }
      await render(root);
    }, "warn"));
  });
}

register({ id: "trash", title: L("Cestino", "Trash"), render });
