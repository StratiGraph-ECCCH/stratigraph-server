"""Un collegamento del manuale che non porta da nessuna parte (19 novembre 2026).

Il 19 novembre, il giorno in cui il manuale è tornato accanto al codice,
`docs/` aveva tredici collegamenti relativi che uscivano dal repository:
`../../s3Dgraphy`, `../../stratigraph-catalog/README.md`, `../../EMStudio`,
`../../EM-blender-tools`, `../../heriverse-ansible`,
`../../stratigraph-stratifield/docs/FIELD-NODE.md`. Sul Mac dove sono stati
scritti funzionavano tutti, perché i repository sono cartelle sorelle; letti su
GitHub erano tredici 404. `sphinx-build -W` non li vedeva: `docs/conf.py` li
mandava a GitHub per nome, e per Sphinx un collegamento a un file che non è una
pagina del progetto non è un avviso.

Questa prova chiede una cosa sola: **ogni collegamento relativo di `docs/`
resta dentro il repository e arriva a un file che esiste**. Quello che esce dal
repository si scrive come indirizzo intero (`https://…`), che è onesto: dice a
chi legge che sta per uscire di casa.

Portata da `stratigraph-stratifield/tests/test_docs_link_veri.py` (commit
`b9a6b45`). La trappola in cui è caduta la prima versione di quella prova:
`resolve()` da solo trova il file sul disco di chi scrive, quindi
`../../s3Dgraphy/README.md` «esiste» e la prova è verde col collegamento rotto.
Il confine del repository fa parte della regola, ed è controllato **prima**
dell'esistenza del file.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

#: `[testo](destinazione)`, saltando le immagini `![...]`. Il testo può andare a
#: capo; la destinazione no, ma può contenere uno spazio — `(../../StratiGraph
#: Catalog)` non era un collegamento per CommonMark, e la pagina lo stampava
#: tale e quale: è un guasto anche quello.
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\n]+)\)")


def _relative_links():
    for page in sorted(DOCS.rglob("*.md")):
        if "_build" in page.relative_to(DOCS).parts:
            continue
        for raw in _LINK.findall(page.read_text(encoding="utf-8")):
            target = raw.split("#", 1)[0].strip()
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target):
                continue                      # https:, mailto:, …: indirizzi interi
            yield page, target


def _guasto(page: pathlib.Path, target: str) -> str | None:
    """Perché questo collegamento non va, o None se va."""
    dove = (page.parent / target).resolve()
    try:
        dove.relative_to(ROOT)
    except ValueError:
        # esce dal repository: sul disco di chi scrive funziona, perché i
        # repository sono cartelle sorelle; una volta pubblicato è un 404.
        return f"{page.name} → {target} (esce dal repository)"
    if not dove.exists():
        return f"{page.name} → {target} (il file non c'è)"
    return None


def test_ogni_collegamento_relativo_resta_in_casa_e_arriva_a_un_file():
    rotti = [g for g in (_guasto(page, target) for page, target in _relative_links())
             if g]
    assert rotti == [], (
        "collegamenti che non portano da nessuna parte una volta pubblicati: "
        + ", ".join(rotti)
        + ". Un documento di un altro repository si cita con l'indirizzo intero.")


def test_il_confine_viene_prima_del_disco():
    """La trappola, tenuta chiusa: un fratello che ESISTE sul disco è rotto lo stesso."""
    sorella = ROOT.parent / "s3Dgraphy" / "README.md"
    pagina = DOCS / "ARCHITECTURE-SYSTEM.md"
    motivo = _guasto(pagina, "../../s3Dgraphy/README.md")
    assert motivo is not None and "esce dal repository" in motivo, (
        f"il collegamento verso un repository fratello passa (sul disco: "
        f"{sorella.exists()}): il confine non fa parte della regola")
    assert _guasto(pagina, "../dev-stack/README-DEV.md") is None
    assert "il file non c'è" in _guasto(pagina, "../non-c-e.md")
