/**
 * MODULE · Strumenti — quello che si installa sul proprio computer, una volta
 * sola (scrivania «casa del nodo», 31 ottobre 2026). Per CHIUNQUE abbia firmato.
 *
 * Gli indirizzi da cui scaricare li dice il nodo (`/v1/node` → `tools`, che un
 * nodo senza rete fa puntare al suo specchio). I requisiti di EMtools vengono
 * dalla sua guida d'installazione (1.5): Blender 4.4 o successivo; sui Mac
 * Intel 4.4 o 4.5, perché Blender 5 non li supporta; le dipendenze si
 * installano da sole.
 */
import { api, escapeHtml, register } from "../console.js";
import { L, head } from "../kit.js";
import { setToolsModule } from "./home.js";

const BLENDER = "https://www.blender.org/download/";

async function render(root) {
  const node = await api.get("/node").catch(() => ({}));
  const by = Object.fromEntries((node.tools || []).map((x) => [x.name, x]));
  const ems = by.emstudio || {};
  const emt = by.blender || {};
  root.innerHTML = "";
  head(root, L("Gli strumenti sul tuo computer", "The tools on your computer"),
    escapeHtml(L("Si installano una volta sola. Poi ogni stanza si apre dal suo pulsante, senza scrivere niente.",
                 "You install them once. Then every room opens from its button, with nothing to type.")));
  const grid = document.createElement("div");
  grid.className = "t-grid";
  const link = (href, text, kind = "") => href
    ? `<a class="k-btn ${kind}" href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(text)}</a>` : "";
  const step = (n, title, body, extra = "") => `<li class="t-step"><span class="t-n">${n}</span><div>
      <b>${escapeHtml(title)}</b><p>${escapeHtml(body)}</p>${extra}</div></li>`;
  grid.innerHTML = `
    <section class="t-card"><h2>EMStudio</h2><ol>
      ${step(1, L("Scarica e installa EMStudio", "Download and install EMStudio"),
        L("Il nodo indica da dove prenderlo.", "The node says where to get it."), link(ems.download, L("Scarica EMStudio", "Download EMStudio"), "pri"))}
      ${step(2, L("Aprilo una volta", "Open it once"),
        L("Così il computer impara che i link delle stanze si aprono con EMStudio.", "So the computer learns that room links open with EMStudio."))}
      ${step(3, L("Torna alla stanza e premi «EMStudio»", "Go back to the room and press «EMStudio»"),
        L("Senza installare niente c'è anche «Nel browser».", "Without installing anything there is also «In the browser»."))}
    </ol>${ems.manual ? `<p class="k-faint"><a href="${escapeHtml(ems.manual)}" target="_blank" rel="noopener">${escapeHtml(L("La guida di EMStudio", "The EMStudio guide"))}</a></p>` : ""}</section>
    <section class="t-card"><h2>${escapeHtml(L("EMtools in Blender", "EMtools in Blender"))}</h2><ol>
      ${step(1, L("Blender 4.4 o successivo", "Blender 4.4 or later"),
        L("Su un Mac con processore Intel resta su Blender 4.4 o 4.5: Blender 5 non li supporta più.",
          "On a Mac with an Intel processor stay on Blender 4.4 or 4.5: Blender 5 no longer supports them."), link(BLENDER, L("Scarica Blender", "Download Blender")))}
      ${step(2, L("Aggiungi EMtools", "Add EMtools"),
        L("Premi «Installa EMtools»: dalla pagina che si apre trascina la scheda di installazione dentro Blender: la prima volta aggiunge il repository di Extended Matrix, la seconda installa EMtools. Poi attivalo in Preferenze › Estensioni. Le sue dipendenze si installano da sole. Senza rete: scarica il file .zip e scegli Installa da disco.",
          "Press «Install EMtools»: from the page that opens drag the install card into Blender: the first time it adds the Extended Matrix repository, the second installs EMtools. Then enable it in Preferences › Extensions. Its dependencies install themselves. Without a network: download the .zip and choose Install from Disk."),
        link(emt.download, L("Installa EMtools", "Install EMtools"), "pri"))}
      ${step(3, L("Apri la stanza da un link", "Open the room from a link"),
        L("Nella stanza premi «EMtools» per copiare il link, poi in Blender: EMtools › Apri una stanza da un link, e incolla.",
          "In the room press «EMtools» to copy the link, then in Blender: EMtools › Open room from link, and paste."))}
    </ol>${emt.manual ? `<p class="k-faint"><a href="${escapeHtml(emt.manual)}" target="_blank" rel="noopener">${escapeHtml(L("La guida completa all'installazione di EMtools", "The full EMtools installation guide"))}</a></p>` : ""}</section>`;
  root.appendChild(grid);
}

setToolsModule(register({ id: "tools", title: L("Strumenti", "Tools"), render, everyone: true, order: 1 }));
