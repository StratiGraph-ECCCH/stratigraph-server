/**
 * MODULE · Trasferimenti — people between the field node and the central one
 * (E.D., 30 October 2026; the rules are in `app/transfer.py`).
 *
 * Four things, in the order a node manager meets them: this node's key (to put
 * on the other node's trust list), the trust list, a package to send, a package
 * received. Passwords never travel; a package is accepted only from a trusted
 * node; profiles travel as proposals, confirmed here one by one.
 */
import { api, confirmNamed, escapeHtml, register } from "../console.js";
import { L, PROFILE_WORD, button, head, profileChip, tag, toast } from "../kit.js";

async function render(root) {
  const [me, trusted, rooms] = await Promise.all([
    api.get("/admin/node-key"), api.get("/admin/trusted-nodes"), api.get("/admin/rooms"),
  ]);
  root.innerHTML = "";
  head(root, L("Trasferimenti di persone", "People transfers"),
    escapeHtml(L("Le persone fra il nodo da campo e il nodo centrale. Le password non viaggiano mai: chi arriva riceve qui una password temporanea nuova. Un pacchetto si accetta solo da un nodo di fiducia, e i profili arrivano come proposte da confermare.",
      "People between the field node and the central node. Passwords never travel: whoever arrives gets a new temporary password here. A package is accepted only from a trusted node, and profiles arrive as proposals to confirm.")));

  // ── 1 · this node ─────────────────────────────────────────────────────────
  const mine = document.createElement("section");
  mine.innerHTML = `<h2>${escapeHtml(L("Questo nodo", "This node"))}</h2>
    <div class="k-card"><span class="k-k">${escapeHtml(me.node)}</span>
      <span>${escapeHtml(L("impronta della chiave: ", "key fingerprint: "))}<b class="k-mono">${escapeHtml(me.fingerprint)}</b></span>
      <span class="k-mono k-faint" style="overflow-wrap:anywhere">${escapeHtml(me.public_key)}</span><div data-slot></div></div>
    <p class="k-note">${escapeHtml(L("Questa chiave va nella lista di fiducia dell'altro nodo, una volta. Al telefono basta confrontare l'impronta.",
      "This key goes on the other node's trust list, once. On the phone, comparing the fingerprint is enough."))}</p>`;
  mine.querySelector("[data-slot]").appendChild(button(L("Copia la chiave", "Copy the key"), async () => {
    try { await navigator.clipboard.writeText(me.public_key); toast(L("Chiave copiata.", "Key copied.")); }
    catch { toast(L("Seleziona la chiave e copiala a mano.", "Select the key and copy it by hand."), "bad"); }
  }));
  root.appendChild(mine);

  // ── 2 · the trust list ────────────────────────────────────────────────────
  const trust = document.createElement("section");
  const names = Object.keys(trusted);
  trust.innerHTML = `<h2 style="margin-top:22px">${escapeHtml(L("Nodi di fiducia", "Trusted nodes"))}</h2>
    <div class="k-list">${names.map((n) => `<div class="k-li"><div><b>${escapeHtml(n)}</b>
      <small>${escapeHtml(trusted[n].fingerprint)} · ${escapeHtml(String(trusted[n].added_at || "").slice(0, 10))}</small></div><span data-n="${escapeHtml(n)}"></span></div>`).join("")
      || `<div class="k-li"><span class="k-faint">${escapeHtml(L("Ancora nessuno.", "None yet."))}</span></div>`}</div>
    <div class="k-form" style="margin-top:8px"><input id="k-t-name" placeholder="${escapeHtml(L("nome del nodo (come lo dichiara lui)", "node name (as it declares itself)"))}">
      <input id="k-t-key" placeholder="${escapeHtml(L("chiave pubblica", "public key"))}"></div>`;
  trust.querySelectorAll("[data-n]").forEach((slot) => slot.appendChild(button(L("Togli", "Remove"), async () => {
    if (!confirmNamed(L("la rimozione dalla lista di fiducia", "removing from the trust list"), slot.dataset.n)) return;
    try { await api.del(`/admin/trusted-nodes/${encodeURIComponent(slot.dataset.n)}`); toast(L("Tolto dalla lista.", "Removed.")); }
    catch (error) { toast(error.message, "bad"); }
    await render(root);
  }, "warn")));
  trust.querySelector(".k-form").appendChild(button(L("Aggiungi", "Add"), async () => {
    const name = trust.querySelector("#k-t-name").value.trim();
    const key = trust.querySelector("#k-t-key").value.trim();
    if (!name || !key) return;
    try {
      const entry = await api.put(`/admin/trusted-nodes/${encodeURIComponent(name)}`, { public_key: key });
      toast(L(`Di fiducia. Impronta ${entry.fingerprint}: confrontala con l'altro nodo.`, `Trusted. Fingerprint ${entry.fingerprint}: compare it with the other node.`));
    } catch (error) { toast(error.message, "bad"); }
    await render(root);
  }, "pri"));
  root.appendChild(trust);

  // ── 3 · a package to send ─────────────────────────────────────────────────
  const send = document.createElement("section");
  const active = rooms.filter((r) => !r.implicit && !r.archived_at);
  send.innerHTML = `<h2 style="margin-top:22px">${escapeHtml(L("Prepara un pacchetto", "Prepare a package"))}</h2>
    <p class="k-faint">${escapeHtml(L("Viaggiano le persone delle stanze scelte: proprietari, membri e chi è nelle squadre con un ruolo lì. Più chi aggiungi a mano.",
      "The people of the chosen rooms travel: owners, members and the teams with a role there. Plus whoever you add by hand."))}</p>
    <div class="k-list">${active.map((r) => `<label class="k-li"><span><b>${escapeHtml(r.title || r.room_id)}</b><small>${escapeHtml(r.room_id)}</small></span>
      <input type="checkbox" value="${escapeHtml(r.room_id)}"></label>`).join("") || `<div class="k-li"><span class="k-faint">—</span></div>`}</div>
    <div class="k-form" style="margin-top:8px"><input id="k-x-more" placeholder="${escapeHtml(L("altri ORCID, separati da virgola", "other ORCIDs, comma-separated"))}"></div>`;
  send.querySelector(".k-form").appendChild(button(L("Crea il pacchetto", "Make the package"), async () => {
    const chosen = [...send.querySelectorAll('input[type="checkbox"]:checked')].map((c) => c.value);
    const more = send.querySelector("#k-x-more").value.split(",").map((s) => s.trim()).filter(Boolean);
    if (!chosen.length && !more.length) { toast(L("Scegli almeno una stanza o una persona.", "Choose at least one room or person."), "bad"); return; }
    try {
      const pkg = await api.post("/admin/people-transfer/export", { rooms: chosen, people: more });
      const blob = new Blob([JSON.stringify(pkg, null, 1)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `persone-${me.node.replace(/[^a-z0-9.-]+/gi, "_")}-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a); a.click(); a.remove();
      toast(L(`Pacchetto firmato: ${pkg.people.length} persone. Portalo all'altro nodo.`, `Signed package: ${pkg.people.length} people. Take it to the other node.`));
    } catch (error) { toast(error.message, "bad"); }
  }, "pri"));
  root.appendChild(send);

  // ── 4 · a package received ────────────────────────────────────────────────
  const receive = document.createElement("section");
  receive.innerHTML = `<h2 style="margin-top:22px">${escapeHtml(L("Ricevi un pacchetto", "Receive a package"))}</h2>
    <div class="k-form"><input type="file" id="k-r-file" accept="application/json,.json"></div><div id="k-r-out"></div>`;
  receive.querySelector("#k-r-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    let pkg;
    try { pkg = JSON.parse(await file.text()); } catch { toast(L("Non è un file JSON.", "Not a JSON file."), "bad"); return; }
    await preview(receive.querySelector("#k-r-out"), pkg, root);
  });
  root.appendChild(receive);
}

async function preview(out, pkg, root) {
  let view;
  try { view = await api.post("/admin/people-transfer/preview", pkg); }
  catch (error) { out.innerHTML = `<p class="k-note bad">${escapeHtml(error.message)}</p>`; return; }
  out.innerHTML = `
    <p class="k-note ${view.trusted ? "" : "bad"}">${escapeHtml(view.trusted
      ? L(`Da ${view.sender}, firmato con la chiave di fiducia (${view.fingerprint}). Preparato il ${String(view.made_at || "").slice(0, 16).replace("T", " ")} da ${view.made_by || "—"}.`,
          `From ${view.sender}, signed with the trusted key (${view.fingerprint}). Made ${String(view.made_at || "").slice(0, 16).replace("T", " ")} by ${view.made_by || "—"}.`)
      : view.why)}</p>
    <div class="k-tw"><table class="k-table"><thead><tr><th>${L("Porta", "Bring")}</th><th>${L("Persona", "Person")}</th>
      <th>${L("Qui oggi", "Here today")}</th><th>${L("Profilo proposto", "Proposed profile")}</th><th>${L("Accetta il profilo", "Accept the profile")}</th><th>ORCID</th></tr></thead>
    <tbody>${view.people.map((p) => `<tr>
      <td><input type="checkbox" data-inc="${escapeHtml(p.orcid)}" ${p.refused ? "disabled" : "checked"}></td>
      <td class="k-title"><b>${escapeHtml(p.name || "—")}${p.test ? " " + tag(L("prova", "test"), "och") : ""}</b><small>${escapeHtml(p.orcid)}</small>${p.refused ? `<small> · ${escapeHtml(p.refused)}</small>` : ""}</td>
      <td>${p.current ? profileChip(p.current) : tag(L("nuova", "new"), "info")}</td>
      <td>${profileChip(p.proposed)}</td>
      <td>${(p.current || "user") !== p.proposed ? `<input type="checkbox" data-acc="${escapeHtml(p.orcid)}" aria-label="${escapeHtml(L("accetta ", "accept ") + (PROFILE_WORD()[p.proposed] || p.proposed))}">` : '<span class="k-faint">—</span>'}</td>
      <td>${p.verified ? tag(L("verificato", "verified"), "ok") : tag(L("da verificare", "to verify"), "warn")}</td></tr>`).join("")}</tbody></table></div>
    ${view.groups.length ? `<p class="k-faint">${escapeHtml(L("Squadre: ", "Teams: ") + view.groups.map((g) => `${g.name || g.id}${g.here ? L(" (già qui)", " (already here)") : ""}`).join(", "))}</p>` : ""}
    <div data-slot></div>`;
  if (!view.trusted) return;
  out.querySelector("[data-slot]").appendChild(button(L("Porta dentro", "Bring in"), async () => {
    const include = [...out.querySelectorAll("[data-inc]:checked")].map((c) => c.dataset.inc);
    const accept = [...out.querySelectorAll("[data-acc]:checked")].map((c) => c.dataset.acc);
    try {
      const done = await api.post("/admin/people-transfer/import", { package: pkg, include, accept_profiles: accept });
      out.innerHTML = `<div class="k-card"><span class="k-k">${escapeHtml(L("Fatto", "Done"))}</span>
        <span>${escapeHtml(L(`${done.added.length} nuove, ${done.updated.length} già note, ${done.profiles_applied.length} profili accettati, ${done.groups_created.length} squadre create.`,
          `${done.added.length} new, ${done.updated.length} known, ${done.profiles_applied.length} profiles accepted, ${done.groups_created.length} teams created.`))}</span>
        ${done.to_verify.length ? `<span>${escapeHtml(L("Da verificare (nessuno ha attestato il loro ORCID): ", "To verify (nobody attested their ORCID): ") + done.to_verify.join(", "))}</span>` : ""}
        ${done.notes.map((n) => `<span class="k-faint">${escapeHtml(n)}</span>`).join("")}</div>
        <p class="k-note">${escapeHtml(L("Adesso, in Persone, dai a ciascuno la sua password di campo: le password non viaggiano.",
          "Now, in People, give each person their field password: passwords do not travel."))}</p>`;
    } catch (error) { toast(error.message, "bad"); }
  }, "pri"));
}

register({ id: "transfers", title: L("Trasferimenti", "Transfers"), render });
