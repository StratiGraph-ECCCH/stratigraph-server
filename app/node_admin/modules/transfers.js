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
import { PROFILE_WORD, button, head, profileChip, tag, toast } from "../kit.js";
import { t } from "../i18n.js";

async function render(root) {
  const [me, trusted, rooms] = await Promise.all([
    api.get("/admin/node-key"), api.get("/admin/trusted-nodes"), api.get("/admin/rooms"),
  ]);
  root.innerHTML = "";
  head(root, t("transfers.title"),
    escapeHtml(t("transfers.lead")));

  // ── 1 · this node ─────────────────────────────────────────────────────────
  const mine = document.createElement("section");
  mine.innerHTML = `<h2>${escapeHtml(t("transfers.self.title"))}</h2>
    <div class="k-card"><span class="k-k">${escapeHtml(me.node)}</span>
      <span>${escapeHtml(t("transfers.self.fingerprint"))}<b class="k-mono">${escapeHtml(me.fingerprint)}</b></span>
      <span class="k-mono k-faint" style="overflow-wrap:anywhere">${escapeHtml(me.public_key)}</span><div data-slot></div></div>
    <p class="k-note">${escapeHtml(t("transfers.self.why"))}</p>`;
  mine.querySelector("[data-slot]").appendChild(button(t("transfers.self.copy"), async () => {
    try { await navigator.clipboard.writeText(me.public_key); toast(t("transfers.self.copied")); }
    catch { toast(t("transfers.self.copyByHand"), "bad"); }
  }));
  root.appendChild(mine);

  // ── 2 · the trust list ────────────────────────────────────────────────────
  const trust = document.createElement("section");
  const names = Object.keys(trusted);
  trust.innerHTML = `<h2 style="margin-top:22px">${escapeHtml(t("transfers.trusted.title"))}</h2>
    <div class="k-list">${names.map((n) => `<div class="k-li"><div><b>${escapeHtml(n)}</b>
      <small>${escapeHtml(trusted[n].fingerprint)} · ${escapeHtml(String(trusted[n].added_at || "").slice(0, 10))}</small></div><span data-n="${escapeHtml(n)}"></span></div>`).join("")
      || `<div class="k-li"><span class="k-faint">${escapeHtml(t("transfers.trusted.none"))}</span></div>`}</div>
    <div class="k-form" style="margin-top:8px"><input id="k-t-name" placeholder="${escapeHtml(t("transfers.trusted.name"))}">
      <input id="k-t-key" placeholder="${escapeHtml(t("transfers.trusted.key"))}"></div>`;
  trust.querySelectorAll("[data-n]").forEach((slot) => slot.appendChild(button(t("transfers.trusted.remove"), async () => {
    if (!confirmNamed(t("transfers.trusted.remove.confirm"), slot.dataset.n)) return;
    try { await api.del(`/admin/trusted-nodes/${encodeURIComponent(slot.dataset.n)}`); toast(t("transfers.trusted.removed")); }
    catch (error) { toast(error.message, "bad"); }
    await render(root);
  }, "warn")));
  trust.querySelector(".k-form").appendChild(button(t("transfers.trusted.add"), async () => {
    const name = trust.querySelector("#k-t-name").value.trim();
    const key = trust.querySelector("#k-t-key").value.trim();
    if (!name || !key) return;
    try {
      const entry = await api.put(`/admin/trusted-nodes/${encodeURIComponent(name)}`, { public_key: key });
      toast(t("transfers.trusted.added", { fingerprint: entry.fingerprint }));
    } catch (error) { toast(error.message, "bad"); }
    await render(root);
  }, "pri"));
  root.appendChild(trust);

  // ── 3 · a package to send ─────────────────────────────────────────────────
  const send = document.createElement("section");
  const active = rooms.filter((r) => !r.implicit && !r.archived_at);
  send.innerHTML = `<h2 style="margin-top:22px">${escapeHtml(t("transfers.make.title"))}</h2>
    <p class="k-faint">${escapeHtml(t("transfers.make.why"))}</p>
    <div class="k-list">${active.map((r) => `<label class="k-li"><span><b>${escapeHtml(r.title || r.room_id)}</b><small>${escapeHtml(r.room_id)}</small></span>
      <input type="checkbox" value="${escapeHtml(r.room_id)}"></label>`).join("") || `<div class="k-li"><span class="k-faint">—</span></div>`}</div>
    <div class="k-form" style="margin-top:8px"><input id="k-x-more" placeholder="${escapeHtml(t("transfers.make.others"))}"></div>`;
  send.querySelector(".k-form").appendChild(button(t("transfers.make.button"), async () => {
    const chosen = [...send.querySelectorAll('input[type="checkbox"]:checked')].map((c) => c.value);
    const more = send.querySelector("#k-x-more").value.split(",").map((s) => s.trim()).filter(Boolean);
    if (!chosen.length && !more.length) { toast(t("transfers.make.empty"), "bad"); return; }
    try {
      const pkg = await api.post("/admin/people-transfer/export", { rooms: chosen, people: more });
      const blob = new Blob([JSON.stringify(pkg, null, 1)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `persone-${me.node.replace(/[^a-z0-9.-]+/gi, "_")}-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a); a.click(); a.remove();
      toast(t("transfers.make.done", { n: pkg.people.length }));
    } catch (error) { toast(error.message, "bad"); }
  }, "pri"));
  root.appendChild(send);

  // ── 4 · a package received ────────────────────────────────────────────────
  const receive = document.createElement("section");
  receive.innerHTML = `<h2 style="margin-top:22px">${escapeHtml(t("transfers.receive.title"))}</h2>
    <div class="k-form"><input type="file" id="k-r-file" accept="application/json,.json"></div><div id="k-r-out"></div>`;
  receive.querySelector("#k-r-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    let pkg;
    try { pkg = JSON.parse(await file.text()); } catch { toast(t("transfers.receive.notJson"), "bad"); return; }
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
      ? t("transfers.receive.from", { sender: view.sender, fingerprint: view.fingerprint, when: String(view.made_at || "").slice(0, 16).replace("T", " "), by: view.made_by || "—" })
      : view.why)}</p>
    <div class="k-tw"><table class="k-table"><thead><tr><th>${t("transfers.col.bring")}</th><th>${t("transfers.col.person")}</th>
      <th>${t("transfers.col.here")}</th><th>${t("transfers.col.proposed")}</th><th>${t("transfers.col.accept")}</th><th>ORCID</th></tr></thead>
    <tbody>${view.people.map((p) => `<tr>
      <td><input type="checkbox" data-inc="${escapeHtml(p.orcid)}" ${p.refused ? "disabled" : "checked"}></td>
      <td class="k-title"><b>${escapeHtml(p.name || "—")}${p.test ? " " + tag(t("transfers.tag.test"), "och") : ""}</b><small>${escapeHtml(p.orcid)}</small>${p.refused ? `<small> · ${escapeHtml(p.refused)}</small>` : ""}</td>
      <td>${p.current ? profileChip(p.current) : tag(t("transfers.tag.new"), "info")}</td>
      <td>${profileChip(p.proposed)}</td>
      <td>${(p.current || "user") !== p.proposed ? `<input type="checkbox" data-acc="${escapeHtml(p.orcid)}" aria-label="${escapeHtml(t("transfers.accept") + (PROFILE_WORD()[p.proposed] || p.proposed))}">` : '<span class="k-faint">—</span>'}</td>
      <td>${p.verified ? tag(t("transfers.tag.verified"), "ok") : tag(t("transfers.tag.toVerify"), "warn")}</td></tr>`).join("")}</tbody></table></div>
    ${view.groups.length ? `<p class="k-faint">${escapeHtml(t("transfers.teams") + view.groups.map((g) => `${g.name || g.id}${g.here ? t("transfers.teams.here") : ""}`).join(", "))}</p>` : ""}
    <div data-slot></div>`;
  if (!view.trusted) return;
  out.querySelector("[data-slot]").appendChild(button(t("transfers.bringIn"), async () => {
    const include = [...out.querySelectorAll("[data-inc]:checked")].map((c) => c.dataset.inc);
    const accept = [...out.querySelectorAll("[data-acc]:checked")].map((c) => c.dataset.acc);
    try {
      const done = await api.post("/admin/people-transfer/import", { package: pkg, include, accept_profiles: accept });
      out.innerHTML = `<div class="k-card"><span class="k-k">${escapeHtml(t("transfers.done.title"))}</span>
        <span>${escapeHtml(t("transfers.done.counts", { added: done.added.length, updated: done.updated.length, profiles: done.profiles_applied.length, groups: done.groups_created.length }))}</span>
        ${done.to_verify.length ? `<span>${escapeHtml(t("transfers.done.toVerify") + done.to_verify.join(", "))}</span>` : ""}
        ${done.notes.map((n) => `<span class="k-faint">${escapeHtml(n)}</span>`).join("")}</div>
        <p class="k-note">${escapeHtml(t("transfers.done.passwords"))}</p>`;
    } catch (error) { toast(error.message, "bad"); }
  }, "pri"));
}

register({ id: "transfers", title: () => t("transfers.nav"), render });
