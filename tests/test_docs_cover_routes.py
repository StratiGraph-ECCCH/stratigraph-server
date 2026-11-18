"""Una rotta senza pagina fa rosso (E.D., 19 novembre 2026).

Il 18 novembre lo schema OpenAPI dichiarava 84 percorsi `/v1` e 23 di loro non
comparivano in nessun documento di `docs/` né nella prosa del README: quasi
tutta l'API della console, quasi tutti i vocabolari, il `restore` di una
stanza. Avevano `summary` e `tags`, quindi su
`/docs` si vedevano; mancava la prosa per una persona che costruisce un client.

È lo stesso invariante di `concetti/quello-che-il-nodo-dichiara.md`: questo
test non misura la freschezza di un documento, misura l'**assenza** — ed è
l'assenza che fa danno.

## Che cosa conta come «scritto»

* ogni file `.md` di `docs/` (non `docs/_build/`, che è l'uscita di Sphinx);
* il `README.md`, **tranne le righe della sua tabella delle rotte**. Quella
  tabella è tenuta uguale al codice da
  `test_la_documentazione_dice_il_vero.py`: contarla qui renderebbe questo
  cancello verde per costruzione, e non saprebbe mai dire che una rotta non ha
  una pagina.

Un percorso si confronta con i segnaposti normalizzati (`{room_id}` e `{id}`
sono lo stesso `{}`) e con un confine a destra: `/v1/admin/assets` non è
«scritto» perché nei documenti c'è `/v1/admin/assets/{ref}`, né
`/v1/vocab/install` perché c'è `/v1/vocab/installed`.

## Le eccezioni

Si dichiarano in `ECCEZIONI`, una riga ciascuna con la ragione. Oggi non ce n'è
nessuna. Il WebSocket `/v1/rooms/{room_id}/ws` non è un'eccezione: nello schema
OpenAPI non c'è per costruzione, quindi qui non viene chiesto.
"""

from __future__ import annotations

import pathlib
import re
import warnings

import pytest

pytest.importorskip("fastapi", reason="needs the [dev] extra")

from app import main                                        # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
README = ROOT / "README.md"

#: percorso OpenAPI → perché può restare senza pagina. Una riga, una ragione.
ECCEZIONI: dict = {}

_SEGNAPOSTO = re.compile(r"\{[^}/]*\}")
#: dopo un percorso scritto non può venire un altro carattere di percorso
_CONFINE = r"(?![\w{}/-])"


def _norm(testo: str) -> str:
    return _SEGNAPOSTO.sub("{}", testo)


def _scritto() -> str:
    parti = [p.read_text(encoding="utf-8") for p in sorted(DOCS.rglob("*.md"))
             if "_build" not in p.relative_to(DOCS).parts]
    # il README, senza la tabella delle rotte (una riga `| `METODO /percorso` |`)
    parti.append("\n".join(
        riga for riga in README.read_text(encoding="utf-8").splitlines()
        if not re.match(r"^\| `[A-Z, ]+ /", riga)))
    return _norm("\n".join(parti))


def _scoperti(spec, testo: str):
    return sorted(
        p for p in spec["paths"]
        if p.startswith("/v1") and p not in ECCEZIONI
        and not re.search(re.escape(_norm(p)) + _CONFINE, testo))


@pytest.fixture(scope="module")
def spec():
    return main.app.openapi()


def test_ogni_percorso_v1_e_scritto_in_un_documento(spec):
    scoperti = _scoperti(spec, _scritto())
    assert scoperti == [], (
        f"{len(scoperti)} percorsi /v1 senza una pagina in docs/ (né nella prosa "
        f"del README): {scoperti}. Scrivili dove un lettore li cerca, o dichiarali "
        "in ECCEZIONI con la ragione.")


def test_le_eccezioni_nominano_rotte_che_esistono_e_dicono_perche(spec):
    assert set(ECCEZIONI) <= set(spec["paths"])
    assert all(len(r.strip()) > 20 for r in ECCEZIONI.values())


def test_il_cancello_vede_davvero_un_assenza(spec):
    """Il cancello stesso, misurato: tolta da un testo la sola menzione di una
    rotta, quella rotta risulta scoperta — e un prefisso non la copre."""
    testo = _scritto()
    assert _scoperti(spec, testo) == []
    tolto = re.sub(re.escape("/v1/admin/log") + _CONFINE, "/v1/admin/l-o-g", testo)
    assert _scoperti(spec, tolto) == ["/v1/admin/log"]
    # `/v1/vocab/installed` non vale per `/v1/vocab/install`
    assert "/v1/vocab/install" in _scoperti(spec, "/v1/vocab/installed")


def test_gli_operationId_sono_unici_e_FastAPI_non_avvisa():
    """Tre funzioni di `app/main.py` registrate per GET e HEAD con un solo
    `api_route` davano a FastAPI lo stesso operationId per due operazioni: lo
    schema finale era poi corretto da `custom_openapi`, ma FastAPI avvisava tre
    volte (18 nov 2026) e chi genera un client dallo schema di FastAPI ci
    inciampa. Lo schema si ricostruisce qui da capo, e non deve avvisare."""
    salvato = main.app.openapi_schema
    main.app.openapi_schema = None
    try:
        with warnings.catch_warnings(record=True) as avvisi:
            warnings.simplefilter("always")
            schema = main.app.openapi()
    finally:
        main.app.openapi_schema = salvato
    doppi = [str(a.message) for a in avvisi if "Duplicate Operation ID" in str(a.message)]
    assert doppi == []
    ids = [op["operationId"] for ops in schema["paths"].values()
           for op in ops.values()]
    assert len(ids) == len(set(ids))
