/**
 * MODULE · Memoria e bucket — where the bytes are (rewritten 30 October 2026,
 * the desk E.D. approved).
 *
 * Three things on one page: what the node holds (stores, orphans, knots), the
 * space of each room in BYTES (no longer only a count of files), and the bucket
 * FILE BY FILE — size, the rooms that cite a file, where it came in and who
 * brought it, and whether nobody cites it any more.
 *
 * The rule of the old page stands, refined: the object store is not addressed
 * from here. The file list is the node's answer (`GET /v1/admin/assets`), asked
 * on demand and capped; no presigned URL, no second door to the bytes. Removing
 * one is still one file at a time, its digest TYPED (decided 7 October 2026),
 * and the node re-checks who references it when asked.
 */
import { api, confirmNamed, confirmTyped, escapeHtml, register } from "../console.js";
import { L, button, bytes, chips, head, shortRef, tag, toast } from "../kit.js";
import { inPool } from "./rooms.js";

let state = "all";
let roomFilter = "";
let byFilter = "";

async function render(root) {
  const report = await api.get("/admin/storage");
  root.innerHTML = "";
  head(root, L("Memoria e bucket", "Memory and bucket"),
    escapeHtml(L("Dove stanno i byte: i file nel bucket, i documenti nello store delle revisioni. Lo spazio di una stanza conta i file che il suo grafo cita.",
      "Where the bytes are: files in the bucket, documents in the revisions store. A room's space counts the files its graph cites.")));

  const total = (report.rooms || []).reduce((s, r) => s + (r.bytes || 0), 0);
  const trouble = (report.rooms || []).filter((r) => (r.missing_refs || []).length || (r.missing || []).length);
  const cards = document.createElement("div");
  cards.className = "k-grid";
  cards.innerHTML = `
    <div class="k-card"><span class="k-k">${escapeHtml(L("File", "Files"))}</span><span class="k-faint">${escapeHtml(report.asset_store)}</span></div>
    <div class="k-card"><span class="k-k">${escapeHtml(L("Documenti", "Documents"))}</span><span class="k-faint">${escapeHtml(report.snapshot_store)}</span></div>
    <div class="k-card"><span class="k-k">${escapeHtml(L("Spazio citato dalle stanze", "Space cited by the rooms"))}</span><span class="k-big">${bytes(total)}</span></div>
    <div class="k-card"><span class="k-k">${escapeHtml(L("Da sistemare", "To sort out"))}</span><span class="k-big">${trouble.length + (report.blocked_returns || []).length}</span>
      <span class="k-faint">${escapeHtml(L("contenitori o file mancanti, stanze che non possono tornare", "missing containers or files, rooms that cannot come back"))}</span></div>`;
  root.appendChild(cards);

  for (const b of report.blocked_returns || []) {
    const note = document.createElement("p");
    note.className = "k-note bad";
    note.textContent = L(`${b.room_id} è archiviata e non può tornare: il suo grafo ${b.graph} adesso è vivo in ${b.taken_by}.`,
      `${b.room_id} is archived and cannot come back: its graph ${b.graph} is now live in ${b.taken_by}.`);
    root.appendChild(note);
  }

  // ── space per room ────────────────────────────────────────────────────────
  const rooms = (report.rooms || []).filter((r) => r.assets || r.bytes).sort((a, b) => (b.bytes || 0) - (a.bytes || 0));
  const max = Math.max(1, ...rooms.map((r) => r.bytes || 0));
  const bars = document.createElement("section");
  bars.innerHTML = `<h2 style="margin:22px 0 10px">${escapeHtml(L("Spazio per stanza", "Space per room"))}</h2>
    <div class="k-bars">${rooms.map((r) => `<div class="k-brow"><span class="nm" title="${escapeHtml(r.room_id)}">${escapeHtml(r.room_id)}${r.archived_at ? " " + tag(L("arch.", "arch.")) : ""}</span>
      <span class="k-track"><i style="width:${Math.max(r.bytes ? 1 : 0, (r.bytes || 0) / max * 100)}%"></i></span>
      <span class="num k-mono" style="text-align:right">${bytes(r.bytes)}</span></div>`).join("")
      || `<p class="k-faint">${escapeHtml(L("Nessuna stanza cita file.", "No room cites files."))}</p>`}</div>`;
  root.appendChild(bars);

  // ── the bucket, file by file ──────────────────────────────────────────────
  const files = document.createElement("section");
  files.innerHTML = `<h2 style="margin:24px 0 10px">${escapeHtml(L("Il bucket, file per file", "The bucket, file by file"))}</h2>`;
  root.appendChild(files);
  const bar = chips([["all", L("Tutti", "All")], ["in_use", L("In uso", "In use")], ["orphan", L("Orfani", "Orphans")], ["missing", L("Mancanti", "Missing")]],
    state, (k) => { state = k; void drawFiles(); });
  const roomSel = document.createElement("select");
  roomSel.className = "k-search";
  roomSel.setAttribute("aria-label", L("Stanza", "Room"));
  roomSel.innerHTML = `<option value="">${escapeHtml(L("tutte le stanze", "every room"))}</option>`
    + (report.rooms || []).map((r) => `<option value="${escapeHtml(r.room_id)}" ${r.room_id === roomFilter ? "selected" : ""}>${escapeHtml(r.room_id)}</option>`).join("");
  roomSel.addEventListener("change", () => { roomFilter = roomSel.value; void drawFiles(); });
  const bySel = document.createElement("input");
  bySel.className = "k-search";
  bySel.placeholder = L("caricato da (ORCID)", "uploaded by (ORCID)");
  bySel.value = byFilter;
  bySel.addEventListener("change", () => { byFilter = bySel.value.trim(); void drawFiles(); });
  bar.append(roomSel, bySel);
  files.appendChild(bar);
  const out = document.createElement("div");
  files.appendChild(out);

  //: GLI ORFANI SCELTI per toglierli insieme (31 ott 2026, E.D.: «per
  //: cancellare in batch sarebbe importante poterci mettere mano»). Solo
  //: orfani: un file citato da una stanza non ha la casella.
  const picked = new Map();   // ref → size
  const orphansIn = (list) => list.assets.filter((a) => a.state === "orphan");

  function wirePicks(list) {
    const batch = out.querySelector(".k-batch");
    const paint = () => {
      const n = picked.size;
      batch.hidden = !n;
      if (!n) { batch.innerHTML = ""; return; }
      const total = [...picked.values()].reduce((x, y) => x + (y || 0), 0);
      batch.innerHTML = `<span><b>${n}</b> ${escapeHtml(L(n === 1 ? "orfano scelto" : "orfani scelti", n === 1 ? "orphan picked" : "orphans picked"))} · ${bytes(total)}</span>`;
      const acts = document.createElement("span");
      acts.className = "k-batch-acts";
      acts.appendChild(button(L(`Togli (${n})…`, `Remove (${n})…`), () => void removeMany(total), "warn"));
      acts.appendChild(button(L("Togli la scelta", "Clear"), () => { picked.clear(); void drawFiles(); }));
      batch.appendChild(acts);
    };
    out.querySelectorAll("input[data-pick-ref]").forEach((box) => box.addEventListener("change", () => {
      const a = list.assets.find((x) => x.ref === box.dataset.pickRef);
      if (box.checked) picked.set(a.ref, a.size); else picked.delete(a.ref);
      paint();
    }));
    const all = out.querySelector("#k-pick-orphans");
    if (all) {
      all.checked = orphansIn(list).every((a) => picked.has(a.ref));
      all.addEventListener("change", () => {
        for (const a of orphansIn(list)) { if (all.checked) picked.set(a.ref, a.size); else picked.delete(a.ref); }
        out.querySelectorAll("input[data-pick-ref]").forEach((b) => { b.checked = picked.has(b.dataset.pickRef); });
        paint();
      });
    }
    paint();
  }

  async function removeMany(total) {
    const refs = [...picked.keys()];
    if (!confirmTyped(L(`la rimozione di ${refs.length} file orfani (${bytes(total)}): i byte non tornano`,
                        `removing ${refs.length} orphan files (${bytes(total)}): the bytes do not come back`),
                      L("TOGLI", "REMOVE"))) return;
    const { done, refused } = await inPool(refs.map((ref) => ({ room_id: shortRef(ref), ref })),
      (x) => api.del(`/admin/assets/${encodeURIComponent(x.ref)}`),
      (d, n) => L(`Tolgo… ${d} di ${n}`, `Removing… ${d} of ${n}`));
    picked.clear();
    toast(L(`${done} file tolti dal bucket.`, `${done} files removed from the bucket.`)
          + (refused.length ? " " + L(`${refused.length} rifiutati: qualcuno li cita.`, `${refused.length} refused: something cites them.`) : ""),
          refused.length ? "bad" : "");
    if (refused.length) console.warn(refused.join("\n"));
    await drawFiles();
  }

  async function drawFiles() {
    bar.querySelectorAll(".k-chip").forEach((c, i) => c.setAttribute("aria-pressed", String(["all", "in_use", "orphan", "missing"][i] === state)));
    out.innerHTML = `<p class="k-faint">${escapeHtml(L("Chiedo al nodo…", "Asking the node…"))}</p>`;
    const q = new URLSearchParams({ limit: "300" });
    if (state !== "all") q.set("state", state);
    if (roomFilter) q.set("room", roomFilter);
    if (byFilter) q.set("by", byFilter);
    let list;
    try { list = await api.get(`/admin/assets?${q}`); }
    catch (error) { out.innerHTML = `<p class="k-note bad">${escapeHtml(error.message)}</p>`; return; }
    out.innerHTML = `<p class="k-faint">${escapeHtml(L(`${list.matched} file · ${bytes(list.bytes)} · dal ${list.listed_from}`, `${list.matched} files · ${bytes(list.bytes)} · from the ${list.listed_from}`))}
      ${list.truncated ? " · " + escapeHtml(L("elenco interrotto al limite: non tutti i file sono qui", "listing stopped at the cap: not every file is here")) : ""}</p>
      <div class="k-banner k-batch" hidden></div>
      <div class="k-tw"><table class="k-table"><thead><tr><th class="k-pick">${orphansIn(list).length ? `<input type="checkbox" id="k-pick-orphans" aria-label="${escapeHtml(L("Scegli tutti gli orfani elencati", "Pick every listed orphan"))}">` : ""}</th><th>${L("File", "File")}</th><th class="num">${L("Dimensione", "Size")}</th>
        <th>${L("Stanze che lo citano", "Rooms citing it")}</th><th>${L("Entrato da", "Came in through")}</th><th>${L("Caricato da", "Uploaded by")}</th><th></th></tr></thead>
      <tbody>${list.assets.map((a) => `<tr>
        <td class="k-pick">${a.state === "orphan" ? `<input type="checkbox" data-pick-ref="${escapeHtml(a.ref)}" ${picked.has(a.ref) ? "checked" : ""} aria-label="${escapeHtml(L("Scegli", "Pick") + " " + shortRef(a.ref))}">` : ""}</td>
        <td class="k-mono" title="${escapeHtml(a.ref)}">${escapeHtml(shortRef(a.ref))}</td>
        <td class="num">${bytes(a.size)}</td>
        <td>${a.rooms.length ? escapeHtml(a.rooms.join(", ")) : '<span class="k-faint">—</span>'}</td>
        <td>${escapeHtml(a.home || "—")}</td>
        <td class="k-mono">${escapeHtml(a.uploaded_by.join(", ") || "—")}</td>
        <td>${a.state === "orphan" ? `<span data-forget="${escapeHtml(a.ref)}"></span>` : a.state === "missing" ? tag(L("mancante", "missing"), "warn") : tag(L("in uso", "in use"), "ok")}</td></tr>`).join("")
        || `<tr><td colspan="7" class="k-faint">${escapeHtml(L("Nessun file.", "No file."))}</td></tr>`}</tbody></table></div>
      <p class="k-note">${escapeHtml(L("Un file orfano è nel bucket ma nessuna stanza lo cita. Si toglie uno alla volta scrivendone l'impronta, oppure se ne spuntano molti e si tolgono insieme: per ognuno il nodo ricontrolla chi lo usa e rifiuta se qualcuno lo cita.",
        "An orphan file is in the bucket but no room cites it. Remove one by typing its digest, or tick many and remove them together: for each the node re-checks who uses it and refuses if anybody does."))}</p>`;
    wirePicks(list);
    out.querySelectorAll("[data-forget]").forEach((slot) => slot.appendChild(button(L("Togli…", "Remove…"), async () => {
      const ref = slot.dataset.forget;
      if (!confirmTyped(L("la rimozione di questi byte, che non tornano", "removing these bytes, which do not come back"), ref)) return;
      try {
        const done = await api.del(`/admin/assets/${encodeURIComponent(ref)}`);
        toast(done.removed ? L("Tolto dal bucket.", "Removed from the bucket.") : L("Non c'era niente da togliere.", "There was nothing to remove."));
      } catch (error) { toast(error.message, "bad"); }
      await drawFiles();
    }, "warn")));
  }
  await drawFiles();
  void confirmNamed;
}

register({ id: "storage", title: L("Memoria e bucket", "Memory and bucket"), render });
