"""La casa e il suo nome — i cancelli che si chiedono alla PAGINA (9-11 novembre 2026).

* parte seconda: un'identità NON operatore riceve la casa, e nella pagina resa
  non compaiono le sezioni del nodo;
* parte terza: cambiata lingua con un pannello aperto, il testo del pannello
  cambia (prima restava nella lingua in cui era nato, finché non si usciva e
  rientrava);
* parte quinta: EMStudio compare nella colonna «su questo nodo» quando il nodo
  lo dichiara, e solo allora;
* parte sesta: aggiunto un servizio finto agli `offers`, la vetrina lo disegna
  senza che nessun file di pagina sia cambiato.

Il server è quello vero, la pagina è quella vera, il browser è Chrome senza
testa (`pagina_vera.py`). Le toppe stanno nel processo del server — chi è
operatore, quali servizi il nodo annuncia — mai nei file della pagina.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

from pagina_vera import REPO, dom, needs_chrome, server

NON_OPERATORE = "ops.is_operator = lambda *a, **k: False\n"

#: i titoli delle sezioni del NODO, nelle due lingue complete: nessuno deve
#: comparire a chi non è operatore
SEZIONI_DEL_NODO = ("People", "Persone", "Groups", "Gruppi", "Permissions", "Permessi",
                    "Trash", "Cestino", "Node health", "Salute del nodo",
                    "Transfers", "Trasferimenti")


def _nav(page: str) -> str:
    found = re.search(r'<nav id="nav"[^>]*>(.*?)</nav>', page, re.S)
    assert found, page[:2000]
    return found.group(1)


def _buttons(nav: str) -> list:
    return re.findall(r'<button class="nav-item[^"]*">([^<]*)</button>', nav)


# ═══ parte seconda · la casa è di tutti, il nodo dell'operatore ════════════

@needs_chrome
def test_UN_NON_OPERATORE_RICEVE_LA_CASA_e_non_le_sezioni_del_nodo(tmp_path):
    with server(tmp_path, patch=NON_OPERATORE) as base:
        page = dom(f"{base}/home/")
    nav = _nav(page)
    assert _buttons(nav) in (["Your rooms"], ["Le tue stanze"]), _buttons(nav)
    for sezione in SEZIONI_DEL_NODO:
        assert f">{sezione}<" not in nav, sezione
    # …ed è DENTRO la casa, non davanti a una porta che rifiuta
    assert 'class="casa"' in page or "casa" in re.search(r"<body[^>]*>", page).group(0)
    assert "h-rooms" in page, "il pannello «Le tue stanze» non è stato disegnato"


@needs_chrome
def test_E_L_OPERATORE_LE_VEDE(tmp_path):
    """L'altra metà, perché una prova che passa anche quando non c'è niente da
    nascondere non prova niente: in modo di sviluppo il chiamante è operatore."""
    with server(tmp_path) as base:
        page = dom(f"{base}/home/")
    buttons = _buttons(_nav(page))
    assert len(buttons) >= 8, buttons
    assert ("People" in buttons) or ("Persone" in buttons), buttons


# ═══ parte terza · la lingua ridisegna il pannello aperto ══════════════════

_LINGUA = """<!doctype html><html><body><pre id="out">in attesa</pre>
<iframe id="f" style="width:1200px;height:900px"></iframe>
<script>
localStorage.setItem("sg.locale.v1", "en");
const f = document.getElementById("f"), out = document.getElementById("out");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const look = () => {
  const d = f.contentDocument;
  return { panel: d.getElementById("panel").textContent,
           nav: d.getElementById("nav").textContent, lang: d.documentElement.lang };
};
f.addEventListener("load", async () => {
  await wait(2500);
  const before = look();
  const pick = f.contentDocument.getElementById("lang");
  pick.value = "it";
  pick.dispatchEvent(new Event("change"));
  await wait(2500);
  out.textContent = JSON.stringify({ before, after: look() });
}, { once: true });
f.src = "/home/";
</script></body></html>"""


def _seen(page: str) -> dict:
    found = re.search(r'<pre id="out">(.*?)</pre>', page, re.S)
    assert found and found.group(1).startswith("{"), page[:1500]
    import html
    return json.loads(html.unescape(found.group(1)))


@needs_chrome
def test_CAMBIATA_LINGUA_IL_PANNELLO_APERTO_CAMBIA(tmp_path):
    with server(tmp_path, patch=NON_OPERATORE, pages={"lingua.html": _LINGUA}) as base:
        seen = _seen(dom(f"{base}/__prova__/lingua.html", budget_ms=15000))
    before, after = seen["before"], seen["after"]
    assert before["lang"] == "en" and after["lang"] == "it", seen
    #: il PANNELLO, non solo il guscio: il titolo e la frase del modulo aperto
    assert "Your rooms" in before["panel"] and "Where you are working now" in before["panel"], before
    assert "Le tue stanze" in after["panel"] and "Dove stai lavorando adesso" in after["panel"], after
    assert "Your rooms" not in after["panel"], after
    #: …e la voce del modulo nell'elenco, che era una stringa congelata
    assert "Le tue stanze" in after["nav"], after


@needs_chrome
def test_CAMBIATA_LINGUA_ANCHE_UN_PANNELLO_DEL_NODO_CAMBIA(tmp_path):
    """Lo stesso, sull'operatore e su una sezione del nodo (migrata da `L()` a
    `t()` la stessa notte): la «Salute del nodo» dopo un clic."""
    harness = _LINGUA.replace('  const before = look();',
        '  [...f.contentDocument.querySelectorAll("#nav button")].find((b) => /Node health/.test(b.textContent)).click();\n'
        '  await wait(2500);\n  const before = look();')
    with server(tmp_path, pages={"lingua.html": harness}) as base:
        seen = _seen(dom(f"{base}/__prova__/lingua.html", budget_ms=20000))
    assert seen["before"]["panel"] != seen["after"]["panel"], seen
    assert "Salute del nodo" in seen["after"]["nav"], seen["after"]["nav"]


# ═══ parte quinta · EMStudio nella colonna, quando il nodo lo dichiara ═════

@needs_chrome
def test_EMSTUDIO_NELLA_COLONNA_solo_se_il_nodo_lo_dichiara(tmp_path):
    with server(tmp_path / "con", env={"EM_EMSTUDIO_WEB_URL": "/em/studio/"}) as base:
        con = _nav(dom(f"{base}/home/"))
    with server(tmp_path / "senza", env={"EM_EMSTUDIO_WEB_URL": ""}) as base:
        senza = _nav(dom(f"{base}/home/"))
    assert 'href="/em/studio/"' in con, con
    assert re.search(r'href="/em/studio/"[^>]*>EMStudio (in the browser|nel browser)<', con), con
    assert "/em/studio/" not in senza and "EMStudio" not in senza, senza


# ═══ parte sesta · la vetrina si scrive da sé ══════════════════════════════

_SERVIZIO_FINTO = """
from app.node_health import Check, OK
node_health.OFFERED = node_health.OFFERED + (
    ("sonar-di-prova", "Sonar di prova", "SONAR_INTERNAL", "SONAR_PUBLIC",
     "ascolta il terreno sotto lo scavo"),)
node_health._PROBES["sonar-di-prova"] = lambda env: Check(
    name="sonar-di-prova", state=OK, detail="finto")
"""


def _pagine() -> dict:
    return {p: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((REPO / "app" / "vetrina").rglob("*")) if p.is_file()}


@needs_chrome
def test_UN_SERVIZIO_NUOVO_COMPARE_NELLA_VETRINA_senza_toccare_la_pagina(tmp_path):
    prima = _pagine()
    with server(tmp_path, patch=_SERVIZIO_FINTO, env={"SONAR_PUBLIC": "/sonar/"}) as base:
        page = dom(f"{base}/")
    assert _pagine() == prima, "un file della vetrina è cambiato"
    for p in prima:
        assert "Sonar" not in p.read_text(encoding="utf-8"), p
    row = re.search(r'<li class="v-offer" data-offer="sonar-di-prova">(.*?)</li>', page, re.S)
    assert row, page[:3000]
    assert 'href="/sonar/"' in row.group(1) and "Sonar di prova" in row.group(1)
    assert "ascolta il terreno sotto lo scavo" in row.group(1)
    assert 'data-state="ok"' in row.group(1)


@needs_chrome
def test_LA_VETRINA_MOSTRA_IL_SERVIZIO_E_NON_UN_LOGIN(tmp_path):
    """Il criterio di collaudo di E.D.: un link mandato a qualcuno mostra il
    servizio. L'accesso è un gesto discreto dentro la pagina, verso la casa."""
    with server(tmp_path, env={"EM_EMSTUDIO_WEB_URL": "/em/studio/",
                               "EM_EMSTUDIO_INTERNAL": "http://127.0.0.1:9/em/studio/"}) as base:
        page = dom(f"{base}/")
    assert 'id="v-offers"' in page and "porta-signin" not in page
    assert re.search(r'<a class="v-signin" id="v-signin" href="home/">', page)
    assert re.search(r'<a class="k-btn pri" id="v-invite" href="home/">', page)
    #: EMStudio fra gli `offers`, e una sonda che non risponde si VEDE
    studio = re.search(r'<li class="v-offer" data-offer="emstudio">(.*?)</li>', page, re.S)
    assert studio and 'data-state="unreachable"' in studio.group(1), page[:3000]
