"""Le immagini del manuale non fanno ingrassare il repo di nascosto (E.D., 19 novembre 2026).

La parte per chi lavora in una stanza chiede schermate, e una schermata presa
così com'è pesa mezzo megabyte. Ogni versione di ogni immagine resta nella
storia di git per sempre: il momento di accorgersene è prima del commit, non
quando un clone ci mette un minuto.

Tre regole su `docs/img/`:

* **massimo 150 KB** per file;
* **PNG o WebP**, e nient'altro (un `.gif` animato o un `.tiff` venuto da una
  macchina fotografica non passano per sbaglio);
* **ogni immagine è usata** da almeno un documento di `docs/`: un'immagine che
  nessuna pagina mostra è peso per niente.

Le schermate si rifanno con `scripts/schermate_del_manuale.py`, che le esce già
ridotte.
"""

from __future__ import annotations

import pathlib

import pytest

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"
IMG = DOCS / "img"

#: il tetto, in byte: 150 KB
TETTO = 150 * 1024
FORMATI = {".png", ".webp"}


def _immagini() -> list:
    if not IMG.is_dir():
        return []
    return sorted(p for p in IMG.rglob("*") if p.is_file() and p.name != ".DS_Store")


def test_CI_SONO_IMMAGINI_da_guardare():
    """Se la cartella si svuota, le altre prove passerebbero per niente."""
    assert _immagini(), f"{IMG} è vuota o non c'è"


@pytest.mark.parametrize("img", _immagini(), ids=lambda p: p.name)
def test_NESSUNA_IMMAGINE_SUPERA_150_KB(img):
    peso = img.stat().st_size
    assert peso <= TETTO, (
        f"docs/img/{img.relative_to(IMG)} pesa {peso // 1024} KB, il tetto è "
        f"{TETTO // 1024} KB: riducila (scripts/schermate_del_manuale.py lo fa per "
        f"le schermate: 1024 px, 256 colori)")


@pytest.mark.parametrize("img", _immagini(), ids=lambda p: p.name)
def test_SOLO_PNG_O_WEBP(img):
    assert img.suffix.lower() in FORMATI, (
        f"docs/img/{img.relative_to(IMG)}: {img.suffix} non è fra {sorted(FORMATI)}")


def test_OGNI_IMMAGINE_E_USATA_DA_UNA_PAGINA():
    testo = "\n".join(p.read_text(encoding="utf-8") for p in DOCS.rglob("*.md")
                      if "_build" not in p.relative_to(DOCS).parts)
    orfane = [p.relative_to(DOCS).as_posix() for p in _immagini()
              if p.relative_to(DOCS).as_posix() not in testo]
    assert not orfane, f"immagini che nessuna pagina mostra: {orfane}"
