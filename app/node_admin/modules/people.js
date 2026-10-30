/**
 * MODULE · Persone — the people of the node (E.D., 30 October 2026).
 *
 * Add a person by ORCID with the profile chosen explicitly (a person starts as a
 * user); change a profile; give or reset the password for the field; take
 * somebody off the node. Every rule is the server's (`app/people.py`,
 * `app/keycloak_admin.py`): this page offers the acts and shows the sentence
 * when one is refused. A password typed here goes to the node once and is shown
 * nowhere, ever.
 */
import { api, confirmTyped, escapeHtml, register } from "../console.js";
import { L, PROFILE_WORD, button, chips, drawer, head, profileChip, tag, toast } from "../kit.js";

let filter = "all";

async function render(root) {
  const data = await api.get("/admin/people?keycloak=true");
  const people = data.people || [];
  root.innerHTML = "";
  const add = button(L("Aggiungi una persona", "Add a person"), () => addDialog(data, root), "pri");
  head(root, L("Persone del nodo", "People of the node"),
    escapeHtml(L("Una persona è un ORCID. Il profilo dice cosa può fare sul nodo; nelle stanze contano i ruoli. Chi viene aggiunto senza profilo è un utente.",
      "A person is an ORCID. The profile says what they may do on the node; in rooms, roles count. Somebody added without a profile is a user.")), [add]);

  const facts = [];
  facts.push(L(`Creare stanze e gruppi: ${data.create_policy === "anyone" ? "chiunque abbia fatto l'accesso" : "editor di nodo e super-amministratori"}`,
    `Creating rooms and groups: ${data.create_policy === "anyone" ? "anybody signed in" : "node editors and super-administrators"}`));
  facts.push(data.keycloak_ready ? L("Keycloak raggiungibile: account e password si gestiscono da qui", "Keycloak reachable: accounts and passwords are managed here")
    : L("Keycloak non raggiungibile dal server: account e password con gli script del nodo", "Keycloak not reachable from the server: accounts and passwords with the node's scripts"));
  if (data.test_people) facts.push(L("Persone di prova ammesse su questo nodo (iD 0000-0000-…)", "Test people allowed on this node (iDs 0000-0000-…)"));
  const note = document.createElement("p");
  note.className = "k-note";
  note.textContent = facts.join(" · ");
  root.appendChild(note);

  const counts = { all: people.length };
  for (const p of people) counts[p.profile] = (counts[p.profile] || 0) + 1;
  root.appendChild(chips([
    ["all", L("Tutti", "All"), counts.all],
    ["super", PROFILE_WORD().super, counts.super || 0],
    ["creator", PROFILE_WORD().creator, counts.creator || 0],
    ["user", PROFILE_WORD().user, counts.user || 0],
  ], filter, (k) => { filter = k; void render(root); }));

  const wrap = document.createElement("div");
  wrap.className = "k-tw";
  const list = people.filter((p) => filter === "all" || p.profile === filter);
  wrap.innerHTML = `<table class="k-table"><thead><tr>
      <th>${L("Persona", "Person")}</th><th>${L("Profilo sul nodo", "Profile on the node")}</th>
      <th>${L("Accesso", "Sign-in")}</th><th class="num">${L("Stanze", "Rooms")}</th><th>${L("Gruppi", "Groups")}</th></tr></thead>
    <tbody>${list.map((p) => `<tr class="k-click" tabindex="0" data-orcid="${escapeHtml(p.orcid)}">
      <td class="k-title"><b>${escapeHtml(p.name || L("(senza nome)", "(no name)"))}${p.test ? " " + tag(L("prova", "test"), "och") : ""}</b><small>${escapeHtml(p.orcid)}</small></td>
      <td>${profileChip(p.profile)}${p.profile_source === "deployment" ? ` <span class="k-faint" title="${escapeHtml(L("fissato dal deploy", "set by the deployment"))}">⚙</span>` : ""}</td>
      <td>${signin(p)}</td>
      <td class="num">${p.rooms}</td>
      <td>${(p.groups || []).map((g) => tag(g, "info")).join(" ") || '<span class="k-faint">—</span>'}</td></tr>`).join("")}</tbody></table>`;
  root.appendChild(wrap);
  wrap.querySelectorAll("tr[data-orcid]").forEach((tr) => {
    const open = () => openPerson(people.find((p) => p.orcid === tr.dataset.orcid), data, root);
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  });

  try {
    const log = await api.get("/admin/log?limit=12");
    if (log.length) {
      const box = document.createElement("div");
      box.innerHTML = `<h2 style="margin:22px 0 8px">${escapeHtml(L("Ultime azioni sulle persone", "Latest acts on people"))}</h2>
        <div class="k-list">${log.slice().reverse().map((e) => `<div class="k-li"><div><b>${escapeHtml(describe(e))}</b>
          <small>${escapeHtml(`${String(e.at || "").replace("T", " ").slice(0, 16)} · ${e.by || "—"}`)}</small></div><span></span></div>`).join("")}</div>`;
      root.appendChild(box);
    }
  } catch { /* the log is a courtesy */ }
}

function describe(e) {
  const who = e.orcid || e.room || "";
  switch (e.kind) {
    case "person.put": return L(`${who}: ${PROFILE_WORD()[e.profile] || e.profile}`, `${who}: ${PROFILE_WORD()[e.profile] || e.profile}`);
    case "person.remove": return L(`${who} tolto dal nodo`, `${who} taken off the node`);
    case "person.password": return L(`${who}: password di campo impostata`, `${who}: field password set`);
    case "room.rescue": return L(`${e.room}: nuovo proprietario ${e.owner}`, `${e.room}: new owner ${e.owner}`);
    default: return `${e.kind} ${who}`;
  }
}

function signin(p) {
  const k = p.keycloak;
  if (!k) return '<span class="k-faint">—</span>';
  if (!k.exists) return tag(L("nessun account", "no account"), "warn");
  const bits = [];
  if (k.enabled === false) bits.push(tag(L("disattivato", "disabled"), "warn"));
  bits.push(k.orcid_linked ? tag("ORCID ✓", "ok") : tag(L("mai con ORCID", "never via ORCID")));
  bits.push(k.password ? tag(L("password di campo", "field password"), "info") : "");
  return bits.join(" ");
}

function addDialog(data, root) {
  const dialog = document.createElement("dialog");
  dialog.className = "k-dialog";
  dialog.innerHTML = `<form method="dialog">
    <h2>${escapeHtml(L("Aggiungi una persona", "Add a person"))}</h2>
    <label>ORCID <input id="k-p-orcid" required placeholder="0000-0002-1825-0097" autocomplete="off"></label>
    <label>${escapeHtml(L("Nome", "Name"))} <input id="k-p-name" autocomplete="off"></label>
    <label>${escapeHtml(L("Profilo sul nodo", "Profile on the node"))}
      <select id="k-p-profile">${["user", "creator", "super"].map((k) => `<option value="${k}">${escapeHtml(PROFILE_WORD()[k])}</option>`).join("")}</select></label>
    ${data.test_people ? `<p class="k-faint">${escapeHtml(L("Per una persona di prova usa un iD che inizia con 0000-0000-.", "For a test person use an iD starting 0000-0000-."))}</p>` : ""}
    <p class="k-note" id="k-p-out" hidden></p>
    <menu><button value="cancel" class="k-btn">${escapeHtml(L("Annulla", "Cancel"))}</button>
      <button value="ok" class="k-btn pri" id="k-p-ok">${escapeHtml(L("Aggiungi", "Add"))}</button></menu></form>`;
  document.body.appendChild(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.querySelector("#k-p-ok").addEventListener("click", async (e) => {
    e.preventDefault();
    const orcid = dialog.querySelector("#k-p-orcid").value.trim();
    const out = dialog.querySelector("#k-p-out");
    try {
      const person = await api.put(`/admin/people/${encodeURIComponent(orcid)}`, {
        name: dialog.querySelector("#k-p-name").value.trim(),
        profile: dialog.querySelector("#k-p-profile").value,
      });
      toast(L(`${person.orcid} aggiunto. `, `${person.orcid} added. `) + (person.notes || []).join(" · "));
      dialog.close();
      await render(root);
    } catch (error) { out.hidden = false; out.textContent = error.message; }
  });
  dialog.showModal();
}

function openPerson(p, data, root) {
  drawer({
    title: p.name || p.orcid,
    subtitle: p.orcid,
    chips: profileChip(p.profile) + (p.test ? " " + tag(L("prova", "test"), "och") : ""),
    onClose: () => void render(root),
    tabs: [
      ["profile", L("Profilo", "Profile"), (b, d) => tabProfile(b, d, p, data)],
      ["password", L("Password di campo", "Field password"), (b) => tabPassword(b, p, data)],
      ["rooms", L("Stanze e gruppi", "Rooms and groups"), (b) => tabRooms(b, p)],
      ["remove", L("Togli dal nodo", "Take off the node"), (b, d) => tabRemove(b, d, p, data)],
    ],
  });
}

function tabProfile(body, drawerCtl, p, data) {
  const self = data.you && data.you === p.orcid;
  const fixed = p.profile_source === "deployment";
  body.innerHTML = `
    <div class="k-form"><label for="k-name">${escapeHtml(L("Nome", "Name"))}</label><input id="k-name" value="${escapeHtml(p.name || "")}"></div>
    <div class="k-list">${["user", "creator", "super"].map((k) => `<label class="k-li"><span><b>${escapeHtml(PROFILE_WORD()[k])}</b><small>${escapeHtml({
      user: L("entra nelle stanze dove ha un ruolo", "enters the rooms where they hold a role"),
      creator: L("crea stanze e gruppi", "creates rooms and groups"),
      super: L("amministra il nodo: persone, stanze, memoria", "looks after the node: people, rooms, storage"),
    }[k])}</small></span><input type="radio" name="k-prof" value="${k}" ${p.profile === k ? "checked" : ""} ${self || fixed ? "disabled" : ""}></label>`).join("")}</div>
    ${self ? `<p class="k-note">${escapeHtml(L("Il tuo profilo lo cambia un altro super-amministratore: nessuno si dà da solo la cura del nodo.",
      "Your profile is changed by another super-administrator: nobody gives themselves the care of a node."))}</p>` : ""}
    ${fixed ? `<p class="k-note">${escapeHtml(L("Questo profilo è fissato dal deploy (EM_OPERATORS o un ruolo del realm) e si cambia lì.",
      "This profile is set by the deployment (EM_OPERATORS or a realm role) and is changed there."))}</p>` : ""}`;
  body.appendChild(button(L("Salva", "Save"), async () => {
    const chosen = body.querySelector('input[name="k-prof"]:checked');
    const payload = { name: body.querySelector("#k-name").value.trim() };
    if (chosen && !chosen.disabled && chosen.value !== p.profile) payload.profile = chosen.value;
    try {
      const out = await api.put(`/admin/people/${encodeURIComponent(p.orcid)}`, payload);
      Object.assign(p, out);
      toast(L("Salvato.", "Saved."));
      drawerCtl.reopen();
    } catch (error) { toast(error.message, "bad"); }
  }, "pri"));
}

function tabPassword(body, p, data) {
  const k = p.keycloak || {};
  const why = !data.keycloak_ready ? L("Il server non raggiunge Keycloak: sul nodo si usa dev-stack/offline-password.sh.",
      "The server cannot reach Keycloak: on the node use dev-stack/offline-password.sh.")
    : !k.exists ? L("Questa persona non ha ancora un account: salvala dal profilo e l'account viene creato.",
      "This person has no account yet: saving the profile creates it.")
    : (!k.orcid_linked && !p.test) ? L("Questa persona non ha mai fatto l'accesso con ORCID su questo nodo. Il nodo attesta solo un iD che ORCID ha verificato una volta: prima l'accesso online, poi la password.",
      "This person never signed in with ORCID on this node. The node attests only an iD ORCID verified once: first the online sign-in, then the password.")
    : "";
  body.innerHTML = `<p class="k-note">${escapeHtml(L(
    "Senza rete la persona entra con il suo iD e questa password, e il nodo garantisce per lei finché la rete non torna. La password è temporanea: al primo accesso Keycloak ne chiede una nuova.",
    "Without a network the person signs in with their iD and this password, and the node vouches for them until the network returns. It is temporary: at the first sign-in Keycloak asks for a new one."))}</p>
    ${why ? `<p class="k-note bad">${escapeHtml(why)}</p>` : `
    <div class="k-form"><input id="k-pw1" type="password" autocomplete="new-password" placeholder="${escapeHtml(L("almeno 8 caratteri", "at least 8 characters"))}">
      <input id="k-pw2" type="password" autocomplete="new-password" placeholder="${escapeHtml(L("ancora una volta", "once more"))}"></div>
    <p class="k-faint">${escapeHtml(k.password ? L("Ha già una password: questa la sostituisce.", "A password exists: this one replaces it.") : L("Non ha ancora una password di campo.", "No field password yet."))}</p>`}`;
  if (why) return;
  body.appendChild(button(k.password ? L("Reimposta la password", "Reset the password") : L("Imposta la password", "Set the password"), async () => {
    const a = body.querySelector("#k-pw1"), b = body.querySelector("#k-pw2");
    if (a.value !== b.value) { toast(L("Le due password non coincidono.", "The two passwords differ."), "bad"); return; }
    try {
      await api.post(`/admin/people/${encodeURIComponent(p.orcid)}/password`, { password: a.value, temporary: true });
      a.value = ""; b.value = "";
      toast(L("Password impostata: temporanea, da cambiare al primo accesso.", "Password set: temporary, changed at the first sign-in."));
    } catch (error) { toast(error.message, "bad"); }
  }, "pri"));
}

function tabRooms(body, p) {
  body.innerHTML = `<div class="k-card"><span class="k-k">${escapeHtml(L("Stanze", "Rooms"))}</span><span class="k-big">${p.rooms}</span>
    ${(p.rooms_owned || []).length ? `<span>${escapeHtml(L("proprietario di: ", "owner of: ") + p.rooms_owned.join(", "))}</span>` : ""}</div>
    <div class="k-card"><span class="k-k">${escapeHtml(L("Gruppi", "Groups"))}</span><span>${(p.groups || []).map((g) => tag(g, "info")).join(" ") || "—"}</span></div>
    <p class="k-note">${escapeHtml(L("Il dettaglio dei ruoli, stanza per stanza, è nella pagina Permessi.", "Roles room by room are in Permissions."))}</p>`;
}

function tabRemove(body, drawerCtl, p, data) {
  const self = data.you && data.you === p.orcid;
  body.innerHTML = `<div class="k-danger"><h3>${escapeHtml(L("Togli dal nodo", "Take off the node"))}</h3>
    <p class="k-faint">${escapeHtml(L(
      "Esce dal registro, perde i ruoli suoi in ogni stanza e l'appartenenza ai gruppi, e il suo account viene disattivato. Quello che ha scritto resta firmato con il suo iD. Le stanze di cui è proprietario restano sue finché non le passi a qualcuno.",
      "Leaves the register, loses their own roles in every room and their groups, and the account is disabled. What they wrote stays signed with their iD. Rooms they own stay theirs until you hand them over."))}</p>
    <div data-slot></div>${self ? `<p class="k-note">${escapeHtml(L("Non puoi togliere te stesso.", "You cannot take yourself off."))}</p>` : ""}</div>`;
  const b = button(L("Togli dal nodo…", "Take off the node…"), async () => {
    if (!confirmTyped(L("l'uscita dal nodo di questa persona", "taking this person off the node"), p.orcid)) return;
    try {
      const out = await api.del(`/admin/people/${encodeURIComponent(p.orcid)}`);
      toast(L(`Tolto. Stanze lasciate: ${out.rooms_left.length}. ${out.keycloak}.`, `Done. Rooms left: ${out.rooms_left.length}. ${out.keycloak}.`)
        + (out.rooms_owned.length ? L(` Ha ancora ${out.rooms_owned.length} stanze sue.`, ` Still owns ${out.rooms_owned.length} rooms.`) : ""));
      drawerCtl.close();
    } catch (error) { toast(error.message, "bad"); }
  }, "warn");
  b.disabled = Boolean(self);
  body.querySelector("[data-slot]").appendChild(b);
}

register({ id: "people", title: L("Persone", "People"), render });
