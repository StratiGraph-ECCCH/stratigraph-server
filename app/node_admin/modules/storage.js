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
import { button, bytes, chips, head, shortRef, tag, toast } from "../kit.js";
import { t } from "../i18n.js";
import { inPool } from "./rooms.js";

let state = "all";
let roomFilter = "";
let byFilter = "";

async function render(root) {
  const report = await api.get("/admin/storage");
  root.innerHTML = "";
  head(root, t("storage.title"),
    escapeHtml(t("storage.lead")));

  const total = (report.rooms || []).reduce((s, r) => s + (r.bytes || 0), 0);
  const trouble = (report.rooms || []).filter((r) => (r.missing_refs || []).length || (r.missing || []).length);
  const cards = document.createElement("div");
  cards.className = "k-grid";
  cards.innerHTML = `
    <div class="k-card"><span class="k-k">${escapeHtml(t("storage.stat.files"))}</span><span class="k-faint">${escapeHtml(report.asset_store)}</span></div>
    <div class="k-card"><span class="k-k">${escapeHtml(t("storage.stat.documents"))}</span><span class="k-faint">${escapeHtml(report.snapshot_store)}</span></div>
    <div class="k-card"><span class="k-k">${escapeHtml(t("storage.stat.cited"))}</span><span class="k-big">${bytes(total)}</span></div>
    <div class="k-card"><span class="k-k">${escapeHtml(t("storage.stat.toSort"))}</span><span class="k-big">${trouble.length + (report.blocked_returns || []).length}</span>
      <span class="k-faint">${escapeHtml(t("storage.stat.toSort.hint"))}</span></div>`;
  root.appendChild(cards);

  for (const b of report.blocked_returns || []) {
    const note = document.createElement("p");
    note.className = "k-note bad";
    note.textContent = t("storage.blocked", { room: b.room_id, graph: b.graph, takenBy: b.taken_by });
    root.appendChild(note);
  }

  // ── space per room ────────────────────────────────────────────────────────
  const rooms = (report.rooms || []).filter((r) => r.assets || r.bytes).sort((a, b) => (b.bytes || 0) - (a.bytes || 0));
  const max = Math.max(1, ...rooms.map((r) => r.bytes || 0));
  const bars = document.createElement("section");
  bars.innerHTML = `<h2 style="margin:22px 0 10px">${escapeHtml(t("storage.perRoom.title"))}</h2>
    <div class="k-bars">${rooms.map((r) => `<div class="k-brow"><span class="nm" title="${escapeHtml(r.room_id)}">${escapeHtml(r.room_id)}${r.archived_at ? " " + tag(t("storage.perRoom.archived")) : ""}</span>
      <span class="k-track"><i style="width:${Math.max(r.bytes ? 1 : 0, (r.bytes || 0) / max * 100)}%"></i></span>
      <span class="num k-mono" style="text-align:right">${bytes(r.bytes)}</span></div>`).join("")
      || `<p class="k-faint">${escapeHtml(t("storage.perRoom.none"))}</p>`}</div>`;
  root.appendChild(bars);

  // ── the bucket, file by file ──────────────────────────────────────────────
  const files = document.createElement("section");
  files.innerHTML = `<h2 style="margin:24px 0 10px">${escapeHtml(t("storage.bucket.title"))}</h2>`;
  root.appendChild(files);
  const bar = chips([["all", t("storage.filter.all")], ["in_use", t("storage.filter.inUse")], ["orphan", t("storage.filter.orphans")], ["missing", t("storage.filter.missing")]],
    state, (k) => { state = k; void drawFiles(); });
  const roomSel = document.createElement("select");
  roomSel.className = "k-search";
  roomSel.setAttribute("aria-label", t("storage.filter.room"));
  roomSel.innerHTML = `<option value="">${escapeHtml(t("storage.filter.everyRoom"))}</option>`
    + (report.rooms || []).map((r) => `<option value="${escapeHtml(r.room_id)}" ${r.room_id === roomFilter ? "selected" : ""}>${escapeHtml(r.room_id)}</option>`).join("");
  roomSel.addEventListener("change", () => { roomFilter = roomSel.value; void drawFiles(); });
  const bySel = document.createElement("input");
  bySel.className = "k-search";
  bySel.placeholder = t("storage.filter.by");
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
      batch.innerHTML = `<span><b>${n}</b> ${escapeHtml(n === 1 ? t("storage.batch.picked.one") : t("storage.batch.picked.many"))} · ${bytes(total)}</span>`;
      const acts = document.createElement("span");
      acts.className = "k-batch-acts";
      acts.appendChild(button(t("storage.batch.trash", { n }), () => void removeMany(total), "warn"));
      acts.appendChild(button(t("storage.batch.clear"), () => { picked.clear(); void drawFiles(); }));
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
    //: IL CESTINO (6 nov 2026): i file vanno nel cestino per 30 giorni; oltre
    //: la soglia sul blocco (5 GB) la parola cambia e il nodo riceve `bulk`
    let limit = 5 * 1024 ** 3;
    try { limit = (await api.get("/admin/trash")).bulk_bytes || limit; } catch { /* la soglia di sempre */ }
    const bulk = total > limit;
    if (!confirmTyped(bulk
      ? t("storage.trash.bulkConfirm", { n: refs.length, size: bytes(total), limit: bytes(limit) })
      : t("storage.trash.confirm", { n: refs.length, size: bytes(total) }),
      bulk ? t("storage.trash.bulkWord", { n: refs.length }) : t("storage.trash.word"))) return;
    const q = bulk ? "?bulk=true" : "";
    const { done, refused } = await inPool(refs.map((ref) => ({ room_id: shortRef(ref), ref })),
      (x) => api.del(`/admin/assets/${encodeURIComponent(x.ref)}${q}`),
      (d, n) => t("storage.trash.progress", { d, n }));
    picked.clear();
    toast(t("storage.trash.done", { done })
          + (refused.length ? " " + t("storage.trash.refused", { n: refused.length }) : ""),
          refused.length ? "bad" : "");
    if (refused.length) console.warn(refused.join("\n"));
    await drawFiles();
  }

  async function drawFiles() {
    bar.querySelectorAll(".k-chip").forEach((c, i) => c.setAttribute("aria-pressed", String(["all", "in_use", "orphan", "missing"][i] === state)));
    out.innerHTML = `<p class="k-faint">${escapeHtml(t("storage.asking"))}</p>`;
    const q = new URLSearchParams({ limit: "300" });
    if (state !== "all") q.set("state", state);
    if (roomFilter) q.set("room", roomFilter);
    if (byFilter) q.set("by", byFilter);
    let list;
    try { list = await api.get(`/admin/assets?${q}`); }
    catch (error) { out.innerHTML = `<p class="k-note bad">${escapeHtml(error.message)}</p>`; return; }
    out.innerHTML = `<p class="k-faint">${escapeHtml(t("storage.list.summary", { n: list.matched, size: bytes(list.bytes), from: list.listed_from }))}
      ${list.truncated ? " · " + escapeHtml(t("storage.list.truncated")) : ""}</p>
      <div class="k-banner k-batch" hidden></div>
      <div class="k-tw"><table class="k-table"><thead><tr><th class="k-pick">${orphansIn(list).length ? `<input type="checkbox" id="k-pick-orphans" aria-label="${escapeHtml(t("storage.list.pickAll"))}">` : ""}</th><th>${t("storage.col.file")}</th><th class="num">${t("storage.col.size")}</th>
        <th>${t("storage.col.rooms")}</th><th>${t("storage.col.via")}</th><th>${t("storage.col.by")}</th><th></th></tr></thead>
      <tbody>${list.assets.map((a) => `<tr>
        <td class="k-pick">${a.state === "orphan" ? `<input type="checkbox" data-pick-ref="${escapeHtml(a.ref)}" ${picked.has(a.ref) ? "checked" : ""} aria-label="${escapeHtml(t("storage.list.pick") + " " + shortRef(a.ref))}">` : ""}</td>
        <td class="k-mono" title="${escapeHtml(a.ref)}">${escapeHtml(shortRef(a.ref))}</td>
        <td class="num">${bytes(a.size)}</td>
        <td>${a.rooms.length ? escapeHtml(a.rooms.join(", ")) : '<span class="k-faint">—</span>'}</td>
        <td>${escapeHtml(a.home || "—")}</td>
        <td class="k-mono">${escapeHtml(a.uploaded_by.join(", ") || "—")}</td>
        <td>${a.state === "orphan" ? `<span data-forget="${escapeHtml(a.ref)}"></span>` : a.state === "trash" ? tag(t("storage.state.trashed")) : a.state === "missing" ? tag(t("storage.state.missing"), "warn") : tag(t("storage.state.inUse"), "ok")}</td></tr>`).join("")
        || `<tr><td colspan="7" class="k-faint">${escapeHtml(t("storage.list.none"))}</td></tr>`}</tbody></table></div>
      <p class="k-note">${escapeHtml(t("storage.list.note"))}</p>`;
    wirePicks(list);
    out.querySelectorAll("[data-forget]").forEach((slot) => slot.appendChild(button(t("storage.trash.one"), async () => {
      const ref = slot.dataset.forget;
      try {
        const done = await api.del(`/admin/assets/${encodeURIComponent(ref)}`);
        toast(done.in_trash ? t("storage.trash.one.done") : t("storage.trash.one.nothing"));
      } catch (error) { toast(error.message, "bad"); }
      await drawFiles();
    }, "warn")));
  }
  await drawFiles();
  void confirmNamed;
}

register({ id: "storage", title: () => t("storage.title"), render });
