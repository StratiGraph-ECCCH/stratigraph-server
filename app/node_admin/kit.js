/**
 * THE KIT the console's panels share since 30 October 2026 (the node console's
 * desk, approved by E.D.): words in two languages, the role and profile chips,
 * sizes, a slide-over panel with tabs, and a short-lived message.
 *
 * Nothing here calls the node. The panels do, through `api` — this file only
 * draws, so a rule about who may do what can never hide in it.
 */
import { escapeHtml } from "./console.js";
import { LOCALE } from "./i18n.js";

/** The console's panels speak Italian or English; the other languages of the
 *  chrome fall back to English here, which is what the modules did before. */
export const L = (it, en) => (LOCALE === "it" ? it : en);

export const ROLE_WORD = () => ({
  owner: L("proprietario", "owner"), admin: L("amministratore", "admin"),
  editor: L("editor", "editor"), viewer: L("lettore", "reader"),
});
export const PROFILE_WORD = () => ({
  super: L("Super-amministratore", "Super-administrator"),
  creator: L("Editor di nodo", "Node editor"),
  user: L("Utente", "User"),
});
export const RANK = { viewer: 0, editor: 1, admin: 2, owner: 3 };

export function roleChip(role, via) {
  if (!role) return `<span class="k-faint">—</span>`;
  const title = via ? L(`tramite il gruppo ${via}`, `through the group ${via}`)
                    : L("assegnato direttamente", "given directly");
  return `<span class="k-role ${escapeHtml(role)}${via ? " via" : ""}" title="${escapeHtml(title)}">`
    + `${escapeHtml(ROLE_WORD()[role] || role)}${via ? " · " + L("gruppo", "group") : ""}</span>`;
}

export function profileChip(profile) {
  return `<span class="k-profile ${escapeHtml(profile)}">${escapeHtml(PROFILE_WORD()[profile] || profile)}</span>`;
}

export function tag(text, kind = "") {
  return `<span class="k-tag ${kind}">${escapeHtml(text)}</span>`;
}

export function bytes(n) {
  if (n === null || n === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = Number(n), i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

export function shortRef(ref) {
  const hex = String(ref || "").split(":").pop();
  return hex.slice(0, 10) + "…";
}

/** A message that says what happened, then goes. */
export function toast(message, kind = "") {
  const box = document.createElement("div");
  box.className = `k-toast ${kind}`;
  box.setAttribute("role", "status");
  box.textContent = message;
  document.body.appendChild(box);
  window.setTimeout(() => box.remove(), kind === "bad" ? 6000 : 2800);
}

/**
 * The slide-over: one room, one person, one group, with tabs. `tabs` is
 * `[[id, title, async (body) => void]]`; the first draws on open. Escape and the
 * scrim close it; `onClose` redraws the panel underneath.
 */
export function drawer({ title, subtitle = "", chips = "", tabs, onClose }) {
  const scrim = document.createElement("div");
  scrim.className = "k-scrim";
  const box = document.createElement("aside");
  box.className = "k-drawer";
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-label", title);
  box.innerHTML = `
    <div class="k-dh"><div><h2>${escapeHtml(title)}</h2>
      ${subtitle ? `<p class="k-mono k-faint">${escapeHtml(subtitle)}</p>` : ""}
      <div class="k-chips">${chips}</div></div>
      <button type="button" class="k-x" aria-label="${escapeHtml(L("Chiudi", "Close"))}">×</button></div>
    <div class="k-tabs" role="tablist">${tabs.map(([id, t], i) =>
      `<button role="tab" data-tab="${escapeHtml(id)}" aria-selected="${i === 0}">${escapeHtml(t)}</button>`).join("")}</div>
    <div class="k-db"></div>`;
  const body = box.querySelector(".k-db");
  const close = () => { scrim.remove(); box.remove(); document.removeEventListener("keydown", onKey);
                        if (onClose) onClose(); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  scrim.addEventListener("click", close);
  box.querySelector(".k-x").addEventListener("click", close);
  const open = async (id) => {
    box.querySelectorAll(".k-tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === id)));
    body.innerHTML = `<p class="k-faint">${escapeHtml(L("Carico…", "Loading…"))}</p>`;
    try { await tabs.find(([t]) => t === id)[2](body, { reopen: () => open(id), close }); }
    catch (error) { body.innerHTML = `<p class="k-note bad">${escapeHtml(error.message)}</p>`; }
  };
  box.querySelectorAll(".k-tabs button").forEach((b) => b.addEventListener("click", () => open(b.dataset.tab)));
  document.body.append(scrim, box);
  box.querySelector(".k-x").focus();
  void open(tabs[0][0]);
  return { close, open };
}

/** The filter chips above a list. `items` `[[key, label, count]]`. */
export function chips(items, current, onPick) {
  const bar = document.createElement("div");
  bar.className = "k-bar";
  for (const [key, label, count] of items) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "k-chip";
    b.setAttribute("aria-pressed", String(key === current));
    b.innerHTML = `${escapeHtml(label)}${count === undefined ? "" : `<span class="k-n">${count}</span>`}`;
    b.addEventListener("click", () => onPick(key));
    bar.appendChild(b);
  }
  return bar;
}

export function head(root, title, lead, actions = []) {
  const box = document.createElement("div");
  box.className = "k-head";
  box.innerHTML = `<div><h1>${escapeHtml(title)}</h1>${lead ? `<p class="k-lead">${lead}</p>` : ""}</div>`;
  const right = document.createElement("div");
  right.className = "k-actions";
  actions.forEach((a) => right.appendChild(a));
  box.appendChild(right);
  root.appendChild(box);
  return box;
}

export function button(label, onClick, kind = "") {
  const b = document.createElement("button");
  b.type = "button";
  b.className = `k-btn ${kind}`;
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

/** The effective role in a room: the HIGHEST of owner, a direct grant and every
 *  group grant — the rule `access.py` writes, drawn, never decided, here. */
export function effective(orcid, room, groups) {
  const parts = [];
  if (room.owner === orcid) parts.push({ role: "owner", via: null });
  const direct = (room.members || []).find((m) => m.orcid === orcid);
  if (direct) parts.push({ role: direct.role, via: null });
  for (const [gid, role] of Object.entries(room.groups || {})) {
    const g = groups[gid];
    if (g && (g.members || []).includes(orcid)) parts.push({ role, via: gid });
  }
  if (!parts.length) return null;
  parts.sort((a, b) => RANK[b.role] - RANK[a.role] || (a.via ? 1 : -1));
  return { role: parts[0].role, via: parts[0].via, parts };
}
