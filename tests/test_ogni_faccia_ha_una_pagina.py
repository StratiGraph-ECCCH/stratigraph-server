"""Ogni faccia ha la sua pagina (E.D., 18 novembre 2026; il cancello qui il 19).

L'invariante: **ogni cosa che il nodo dichiara di sé deve avere una pagina che
una persona può leggere, e l'assenza di quella pagina fa rosso.** Il 18 il
manuale viveva in un altro repository; il 19 è tornato accanto al codice, e il
cancello sta qui perché chi aggiunge una faccia e chi scrive la pagina sono la
stessa persona nello stesso commit.

## Che cosa dichiara il nodo

`GET /v1/node` torna tre liste, e questa prova le costruisce **come le
costruisce l'applicazione**, senza accendere il server:

* le **facce** (`faces`) da `app.main.entrances()`, cioè `ENTRANCES`;
* le **offerte** (`offers`) da `app.node_health.node_services()`, con un
  ambiente vuoto: nessuna sonda esce sulla rete, e le offerte sono le stesse
  (lo stato cambia, l'etichetta no);
* gli **strumenti** (`tools`) chiedendo `app.main.node_offers()` stesso, con le
  sonde a vuoto — il `download` e il `manual` sono quelli che il nodo dice.

Il 19 novembre: 7 facce, 5 offerte, 2 strumenti.

## Che cosa conta come «nominato»

Le pagine sono i file `.md` di `docs/` (non `docs/_build/`).

* **faccia** — il suo `label` *messo in evidenza come un nome* (`*…*`, `**…**`,
  `«…»`, `"…"`, `` `…` `` o un titolo), oppure il suo `path` scritto come
  codice (`` `/health` ``, `` `GET /health` ``, `` `/em/home/` ``,
  `` `https://…/tools/` ``). Le etichette delle facce sono frasi qualsiasi —
  «This node», «Tools», «Your rooms» — e cercarle nella prosa nuda trovava
  «This node's key» nella pagina dell'amministrazione e diceva verde per la
  vetrina, che non era raccontata da nessuna parte col suo nome. Il percorso
  `/` non conta mai: è la radice di tutto (di Heriverse, del filesystem), e
  `` `/` `` in `docs/` parlava di quelle;
* **offerta** — il suo `label`, con le maiuscole, come parola intera;
* **strumento** — il suo `label` come parola intera, **e** un `manual`
  dichiarato. Il manuale di uno strumento di qualcun altro non lo scriviamo
  noi, ma l'indirizzo dove vive lo dobbiamo dire.

Le eccezioni si dichiarano in `ECCEZIONI`, una riga ciascuna con la ragione.
Oggi non ce n'è nessuna.

## Che cosa non prende

**La vecchiaia.** Una pagina che esiste e racconta il nodo di sei mesi fa passa
senza fare una piega: qui si misura l'**assenza** di un nome, non la verità di
quello che gli sta intorno. Per la vecchiaia servono le figure generate dal
nodo vero (`scripts/schermate_del_manuale.py`), che invecchiano quando invecchia
il nodo.

E non prende i **gesti**. Una faccia è un luogo; una persona impara per gesti —
creare una stanza, portare dentro un file, firmare, pubblicare — e un gesto
attraversa più facce. Questo cancello garantisce che nessun luogo resti senza
nome: è il pavimento, non il soffitto.
"""

from __future__ import annotations

import pathlib
import re

import pytest

pytest.importorskip("fastapi", reason="needs the [dev] extra")

from app import main, node_health                           # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

#: (tipo, nome) → perché può restare senza pagina. Una riga, una ragione.
#: `tipo` è "face" (per `path`), "offer" o "tool" (per `name`).
ECCEZIONI: dict = {}


def _pagine() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(DOCS.rglob("*.md"))
        if "_build" not in p.relative_to(DOCS).parts)


# ── le dichiarazioni, come le costruisce l'applicazione ──────────────────────

def _facce():
    return main.entrances("")


def _offerte():
    return node_health.node_services(environ={})


def _strumenti(monkeypatch):
    # le offerte a vuoto: `node_offers` chiamerebbe le sonde con l'ambiente di
    # chi lancia la suite, e qui interessa solo che cosa dichiara
    monkeypatch.setattr(main, "node_services", _offerte)
    return [t.model_dump() for t in main.node_offers().tools]


# ── «nominato» ────────────────────────────────────────────────────────────────

def _parola(testo: str) -> str:
    return r"(?<![\w])" + re.escape(testo) + r"(?![\w'’])"


def _nome_in_evidenza(label: str, pagine: str) -> bool:
    l = re.escape(label)
    return bool(re.search(
        rf"\*\*{l}\*\*|(?<!\*)\*{l}\*(?!\*)|«{l}»|\"{l}\"|`{l}`|^#+ {l}\s*$",
        pagine, re.M))


#: dopo un percorso scritto non può venire un altro carattere di percorso
_CONFINE = r"(?![\w{}-])"


def _percorso_come_codice(path: str, pagine: str) -> bool:
    if path == "/":
        return False
    p = re.escape(path.rstrip("/")) + ("/" if path.endswith("/") else "")
    # dentro uno span di codice: un metodo, un'origine, un prefisso di
    # montaggio (`/em`) davanti; una query o la fine dello span dopo
    return bool(re.search(
        rf"`(?:[A-Z]+ )?(?:https?://[^\s/`]+)?(?:/[\w.-]+)?{p}{_CONFINE}"
        rf"(?:[?#][^`\n]*)?`", pagine))


def faccia_nominata(face, pagine: str) -> bool:
    return (_nome_in_evidenza(face["label"], pagine)
            or _percorso_come_codice(face["path"], pagine))


def offerta_nominata(offer, pagine: str) -> bool:
    return bool(re.search(_parola(offer["label"]), pagine))


# ── i cancelli ────────────────────────────────────────────────────────────────

def test_ogni_faccia_ha_una_pagina():
    pagine = _pagine()
    facce = _facce()
    assert facce, "il nodo non dichiara nessuna faccia: la prova non misura niente"
    senza = [f"{f['label']} ({f['path']})" for f in facce
             if ("face", f["path"]) not in ECCEZIONI
             and not faccia_nominata(f, pagine)]
    assert senza == [], (
        "facce che il nodo dichiara in `/v1/node` e che nessuna pagina di docs/ "
        "nomina (né l'etichetta in evidenza, né il percorso come codice): "
        + ", ".join(senza))


def test_ogni_offerta_ha_una_pagina():
    pagine = _pagine()
    offerte = _offerte()
    assert offerte, "il nodo non dichiara nessuna offerta: la prova non misura niente"
    senza = [f"{o['label']} ({o['name']})" for o in offerte
             if ("offer", o["name"]) not in ECCEZIONI
             and not offerta_nominata(o, pagine)]
    assert senza == [], (
        "servizi che il nodo può offrire e che nessuna pagina di docs/ nomina "
        "con l'etichetta che la vetrina mostra: " + ", ".join(senza))


def test_ogni_strumento_ha_una_pagina_e_dice_dove_vive_il_suo_manuale(monkeypatch):
    pagine = _pagine()
    strumenti = _strumenti(monkeypatch)
    assert strumenti, "il nodo non dichiara nessuno strumento: la prova non misura niente"
    guasti = []
    for t in strumenti:
        if ("tool", t["name"]) in ECCEZIONI:
            continue
        if not re.search(_parola(t["label"]), pagine):
            guasti.append(f"{t['label']} ({t['name']}): nessuna pagina di docs/ lo nomina")
        if not (t.get("manual") or "").startswith(("https://", "http://")):
            guasti.append(f"{t['label']} ({t['name']}): nessun `manual` dichiarato")
    assert guasti == [], "; ".join(guasti)


def test_le_eccezioni_dicono_perche_e_nominano_qualcosa_che_esiste(monkeypatch):
    dichiarati = ({("face", f["path"]) for f in _facce()}
                  | {("offer", o["name"]) for o in _offerte()}
                  | {("tool", t["name"]) for t in _strumenti(monkeypatch)})
    for chiave, ragione in ECCEZIONI.items():
        assert chiave in dichiarati, f"eccezione per qualcosa che il nodo non dichiara: {chiave}"
        assert isinstance(ragione, str) and ragione.strip(), f"eccezione senza ragione: {chiave}"


# ── la regola stessa, su testi scritti a mano ────────────────────────────────

@pytest.mark.parametrize("testo, atteso", [
    ("the page *This node* lists", True),
    ("the page **This node** lists", True),
    ("the page «This node» lists", True),
    ("## This node", True),
    ("**This node's key**, to give", False),      # il falso verde del 19 novembre
    ("This node runs the rooms", False),
])
def test_un_etichetta_di_faccia_conta_solo_come_nome(testo, atteso):
    assert _nome_in_evidenza("This node", testo) is atteso


@pytest.mark.parametrize("path, testo, atteso", [
    ("/health", "ask `GET /health` first", True),
    ("/health", "ask `/health?x=1`", True),
    ("/home/", "the house (`/em/home/`) asks", True),
    ("/tools/", "open `https://em.localhost:8443/em/tools/`", True),
    ("/docs", "every route is in `/docs`", True),
    ("/docs", "see `/docs/index.md`", False),
    ("/v1/node", "`GET /v1/nodes`", False),
    ("/health", "the health of the node", False),
    ("/", "| `/` | heriverse | the 3D front end |", False),
])
def test_un_percorso_di_faccia_conta_solo_come_codice(path, testo, atteso):
    assert _percorso_come_codice(path, testo) is atteso
