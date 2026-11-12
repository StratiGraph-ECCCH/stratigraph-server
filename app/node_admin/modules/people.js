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
import { PROFILE_WORD, button, chips, drawer, head, profileChip, tag, toast } from "../kit.js";
import { t } from "../i18n.js";

let filter = "all";

async function render(root) {
  const data = await api.get("/admin/people?keycloak=true");
  const people = data.people || [];
  root.innerHTML = "";
  const add = button(t("people.add"), () => addDialog(data, root), "pri");
  const actions = [add];
  if (data.test_people) actions.unshift(button(t("people.test"), () => void addTestPeople(people, root)));
  head(root, t("people.title"),
    escapeHtml(t("people.lead")), actions);

  const facts = [];
  facts.push(t("people.fact.create", { who: data.create_policy === "anyone" ? t("people.fact.create.anyone") : t("people.fact.create.editors") }));
  facts.push(data.keycloak_ready ? t("people.fact.keycloak.up")
    : t("people.fact.keycloak.down"));
  if (data.test_people) facts.push(t("people.fact.testAllowed"));
  const note = document.createElement("p");
  note.className = "k-note";
  note.textContent = facts.join(" · ");
  root.appendChild(note);

  const counts = { all: people.length };
  for (const p of people) counts[p.profile] = (counts[p.profile] || 0) + 1;
  root.appendChild(chips([
    ["all", t("people.filter.all"), counts.all],
    ["super", PROFILE_WORD().super, counts.super || 0],
    ["creator", PROFILE_WORD().creator, counts.creator || 0],
    ["user", PROFILE_WORD().user, counts.user || 0],
  ], filter, (k) => { filter = k; void render(root); }));

  const wrap = document.createElement("div");
  wrap.className = "k-tw";
  const list = people.filter((p) => filter === "all" || p.profile === filter);
  wrap.innerHTML = `<table class="k-table"><thead><tr>
      <th>${t("people.col.person")}</th><th>${t("people.col.profile")}</th>
      <th>${t("people.col.signin")}</th><th class="num">${t("people.col.rooms")}</th><th>${t("people.col.groups")}</th></tr></thead>
    <tbody>${list.map((p) => `<tr class="k-click" tabindex="0" data-orcid="${escapeHtml(p.orcid)}">
      <td class="k-title"><b>${escapeHtml(p.name || t("people.noName"))}${p.test ? " " + tag(t("people.tag.test"), "och") : ""}</b><small>${escapeHtml(p.orcid)}</small></td>
      <td>${profileChip(p.profile)}${p.profile_source === "deployment" ? ` <span class="k-faint" title="${escapeHtml(t("people.profile.fromDeployment"))}">⚙</span>` : ""}</td>
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
      box.innerHTML = `<h2 style="margin:22px 0 8px">${escapeHtml(t("people.log.title"))}</h2>
        <div class="k-list">${log.slice().reverse().map((e) => `<div class="k-li"><div><b>${escapeHtml(describe(e))}</b>
          <small>${escapeHtml(`${String(e.at || "").replace("T", " ").slice(0, 16)} · ${e.by || "—"}`)}</small></div><span></span></div>`).join("")}</div>`;
      root.appendChild(box);
    }
  } catch { /* the log is a courtesy */ }
}

/** The n-th test iD (range 0000-0000-…, which ORCID never issues), with its
 *  ISO 7064 11,2 check digit — the same rule as `people.test_orcid`. */
function testOrcid(n) {
  const base = ("00000000" + String(n).padStart(7, "0")).slice(-15);
  let total = 0;
  for (const ch of base) total = (total + Number(ch)) * 2;
  const r = (12 - (total % 11)) % 11;
  const d = base + (r === 10 ? "X" : String(r));
  return `${d.slice(0, 4)}-${d.slice(4, 8)}-${d.slice(8, 12)}-${d.slice(12, 16)}`;
}

const NUMBERS = ["Uno", "Due", "Tre", "Quattro", "Cinque", "Sei", "Sette", "Otto", "Nove", "Dieci",
  "Undici", "Dodici", "Tredici", "Quattordici", "Quindici", "Sedici", "Diciassette", "Diciotto", "Diciannove", "Venti"];

/** Test people in one gesture, only where the node allows them: iDs in the
 *  range ORCID never issues, names «Prova …», profile user. Their password is
 *  given one by one, from each person's panel. */
async function addTestPeople(people, root) {
  const how = Number(window.prompt(t("people.test.prompt"), "5"));
  if (!how || how < 1) return;
  const taken = new Set(people.map((p) => p.orcid));
  let n = 1, made = 0;
  while (made < Math.min(how, 20) && n < 999) {
    const id = testOrcid(n);
    if (!taken.has(id)) {
      try {
        await api.put(`/admin/people/${id}`, { name: `Prova ${NUMBERS[n - 1] || n}`, profile: "user" });
        made++;
      } catch (error) { toast(error.message, "bad"); break; }
    }
    n++;
  }
  toast(t("people.test.added", { made }));
  await render(root);
}

function describe(e) {
  const who = e.orcid || e.room || "";
  switch (e.kind) {
    case "person.put": return t("people.log.profile", { who, profile: PROFILE_WORD()[e.profile] || e.profile });
    case "person.remove": return t("people.log.removed", { who });
    case "person.password": return t("people.log.password", { who });
    case "room.rescue": return t("people.log.rescue", { room: e.room, owner: e.owner });
    default: return `${e.kind} ${who}`;
  }
}

function signin(p) {
  const k = p.keycloak;
  if (!k) return '<span class="k-faint">—</span>';
  if (!k.exists) return tag(t("people.signin.noAccount"), "warn");
  const bits = [];
  if (k.enabled === false) bits.push(tag(t("people.signin.disabled"), "warn"));
  bits.push(k.orcid_linked ? tag("ORCID ✓", "ok") : tag(t("people.signin.neverOrcid")));
  bits.push(k.password ? tag(t("people.signin.fieldPassword"), "info") : "");
  return bits.join(" ");
}

function addDialog(data, root) {
  const dialog = document.createElement("dialog");
  dialog.className = "k-dialog";
  dialog.innerHTML = `<form method="dialog">
    <h2>${escapeHtml(t("people.add"))}</h2>
    <label>ORCID <input id="k-p-orcid" required placeholder="0000-0002-1825-0097" autocomplete="off"></label>
    <label>${escapeHtml(t("people.add.name"))} <input id="k-p-name" autocomplete="off"></label>
    <label>${escapeHtml(t("people.col.profile"))}
      <select id="k-p-profile">${["user", "creator", "super"].map((k) => `<option value="${k}">${escapeHtml(PROFILE_WORD()[k])}</option>`).join("")}</select></label>
    ${data.test_people ? `<p class="k-faint">${escapeHtml(t("people.add.testHint"))}</p>` : ""}
    <p class="k-note" id="k-p-out" hidden></p>
    <menu><button value="cancel" class="k-btn">${escapeHtml(t("people.add.cancel"))}</button>
      <button value="ok" class="k-btn pri" id="k-p-ok">${escapeHtml(t("people.add.submit"))}</button></menu></form>`;
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
      toast(t("people.add.done", { orcid: person.orcid }) + (person.notes || []).join(" · "));
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
    chips: profileChip(p.profile) + (p.test ? " " + tag(t("people.tag.test"), "och") : ""),
    onClose: () => void render(root),
    tabs: [
      ["profile", t("people.tab.profile"), (b, d) => tabProfile(b, d, p, data)],
      ["password", t("people.tab.password"), (b) => tabPassword(b, p, data)],
      ["rooms", t("people.tab.rooms"), (b) => tabRooms(b, p)],
      ["remove", t("people.tab.remove"), (b, d) => tabRemove(b, d, p, data)],
    ],
  });
}

function tabProfile(body, drawerCtl, p, data) {
  const self = data.you && data.you === p.orcid;
  const fixed = p.profile_source === "deployment";
  body.innerHTML = `
    <div class="k-form"><label for="k-name">${escapeHtml(t("people.add.name"))}</label><input id="k-name" value="${escapeHtml(p.name || "")}"></div>
    <div class="k-list">${["user", "creator", "super"].map((k) => `<label class="k-li"><span><b>${escapeHtml(PROFILE_WORD()[k])}</b><small>${escapeHtml({
      user: t("people.profile.user"),
      creator: t("people.profile.creator"),
      super: t("people.profile.super"),
    }[k])}</small></span><input type="radio" name="k-prof" value="${k}" ${p.profile === k ? "checked" : ""} ${self || fixed ? "disabled" : ""}></label>`).join("")}</div>
    ${self ? `<p class="k-note">${escapeHtml(t("people.profile.notYourself"))}</p>` : ""}
    ${fixed ? `<p class="k-note">${escapeHtml(t("people.profile.deployment"))}</p>` : ""}`;
  body.appendChild(button(t("people.profile.save"), async () => {
    const chosen = body.querySelector('input[name="k-prof"]:checked');
    const payload = { name: body.querySelector("#k-name").value.trim() };
    if (chosen && !chosen.disabled && chosen.value !== p.profile) payload.profile = chosen.value;
    try {
      const out = await api.put(`/admin/people/${encodeURIComponent(p.orcid)}`, payload);
      Object.assign(p, out);
      toast(t("people.profile.saved"));
      drawerCtl.reopen();
    } catch (error) { toast(error.message, "bad"); }
  }, "pri"));
}

function tabPassword(body, p, data) {
  const k = p.keycloak || {};
  const why = !data.keycloak_ready ? t("people.password.noKeycloak")
    : !k.exists ? t("people.password.noAccount")
    : (!k.orcid_linked && !p.test) ? t("people.password.neverOrcid")
    : "";
  body.innerHTML = `<p class="k-note">${escapeHtml(t("people.password.why"))}</p>
    ${why ? `<p class="k-note bad">${escapeHtml(why)}</p>` : `
    <div class="k-form"><input id="k-pw1" type="password" autocomplete="new-password" placeholder="${escapeHtml(t("people.password.min"))}">
      <input id="k-pw2" type="password" autocomplete="new-password" placeholder="${escapeHtml(t("people.password.again"))}"></div>
    <p class="k-faint">${escapeHtml(k.password ? t("people.password.exists") : t("people.password.none"))}</p>`}`;
  if (why) return;
  body.appendChild(button(k.password ? t("people.password.reset") : t("people.password.set"), async () => {
    const a = body.querySelector("#k-pw1"), b = body.querySelector("#k-pw2");
    if (a.value !== b.value) { toast(t("people.password.differ"), "bad"); return; }
    try {
      await api.post(`/admin/people/${encodeURIComponent(p.orcid)}/password`, { password: a.value, temporary: true });
      a.value = ""; b.value = "";
      toast(t("people.password.done"));
    } catch (error) { toast(error.message, "bad"); }
  }, "pri"));
}

function tabRooms(body, p) {
  body.innerHTML = `<div class="k-card"><span class="k-k">${escapeHtml(t("people.rooms.title"))}</span><span class="k-big">${p.rooms}</span>
    ${(p.rooms_owned || []).length ? `<span>${escapeHtml(t("people.rooms.ownerOf") + p.rooms_owned.join(", "))}</span>` : ""}</div>
    <div class="k-card"><span class="k-k">${escapeHtml(t("people.rooms.groups"))}</span><span>${(p.groups || []).map((g) => tag(g, "info")).join(" ") || "—"}</span></div>
    <p class="k-note">${escapeHtml(t("people.rooms.seePermissions"))}</p>`;
}

function tabRemove(body, drawerCtl, p, data) {
  const self = data.you && data.you === p.orcid;
  body.innerHTML = `<div class="k-danger"><h3>${escapeHtml(t("people.tab.remove"))}</h3>
    <p class="k-faint">${escapeHtml(t("people.remove.why"))}</p>
    <div data-slot></div>${self ? `<p class="k-note">${escapeHtml(t("people.remove.notYourself"))}</p>` : ""}</div>`;
  const b = button(t("people.remove.button"), async () => {
    if (!confirmTyped(t("people.remove.confirm"), p.orcid)) return;
    try {
      const out = await api.del(`/admin/people/${encodeURIComponent(p.orcid)}`);
      toast(t("people.remove.done", { left: out.rooms_left.length, keycloak: out.keycloak })
        + (out.rooms_owned.length ? t("people.remove.stillOwns", { owned: out.rooms_owned.length }) : ""));
      drawerCtl.close();
    } catch (error) { toast(error.message, "bad"); }
  }, "warn");
  b.disabled = Boolean(self);
  body.querySelector("[data-slot]").appendChild(b);
}

register({ id: "people", title: () => t("people.nav"), render });
