"""Gli URL da cui si clonano i fratelli sono quelli CANONICI, non quelli che funzionano.

════════════════════════════════════════════════════════════════════════════════
## LA DIFFERENZA FRA «FUNZIONA» E «È GIUSTO»

Fino al 22 settembre 2026 `x-sibling-repos` diceva
`github.com/zalmoxes-laran/stratigraph-server.git`, e `fcn-install.sh` clonava
benissimo. Misurato quel giorno con `curl`:

    zalmoxes-laran/stratigraph-server     301 → StratiGraph-ECCCH/stratigraph-server
    zalmoxes-laran/stratigraph-catalog    301 → StratiGraph-ECCCH/stratigraph-catalog
    StratiGraph-ECCCH/stratigraph-chatbot 301 → StratiGraph-ECCCH/stratigraph-stratifield

Cioè funzionava **per redirect**, che è la forma di dipendenza che muore in
silenzio: il redirect di GitHub è una cortesia e smette il giorno in cui
qualcuno riusa il nome vecchio. Da quel giorno in poi l'installer clonerebbe il
repository di un altro, e nessuna prova diventerebbe rossa.

## PERCHÉ QUESTO CANCELLO NON CHIEDE LA RETE

Una prova che interroga github.com misurerebbe la cosa giusta e sarebbe rossa
ogni volta che il Wi-Fi è lento — cioè verrebbe disattivata. Quello che si può
asserire senza rete è più debole ma vero: i tre servizi del progetto stanno in
`StratiGraph-ECCCH`, e un URL che nomina un profilo personale è, per uno di
loro, per costruzione il nome vecchio.

`s3Dgraphy` non è un'eccezione: ha una casa sua, `github.com/ExtendedMatrix`,
che è l'organizzazione della comunità Extended Matrix — la libreria è più
longeva del progetto che la consuma, e il 22 settembre 2026 ci è stata
trasferita. Due organizzazioni, due recinti, nessuna riga «tranne questa».

## LA MUTAZIONE

Rimetti `zalmoxes-laran` su una delle tre righe → rosso.
"""

from __future__ import annotations

import pathlib
import re

import pytest

COMPOSE = (pathlib.Path(__file__).resolve().parent.parent
           / "dev-stack" / "docker-compose.dev.yml")

#: I repository del PROGETTO, che stanno nell'organizzazione. La chiave è il
#: nome della cartella (il basename del `context:`), che NON è il nome del
#: repository: `stratigraph-chatbot` è la cartella, `stratigraph-stratifield` è
#: il repository, e `git clone <url> <dir>` li tiene distinti apposta.
NELL_ORGANIZZAZIONE = {
    "stratigraph-server": "StratiGraph-ECCCH/stratigraph-server",
    "stratigraph-chatbot": "StratiGraph-ECCCH/stratigraph-stratifield",
    "stratigraph-catalog": "StratiGraph-ECCCH/stratigraph-catalog",
}

#: I repository dell'ECOSISTEMA, che non appartengono a questo progetto e hanno
#: una casa loro: `github.com/ExtendedMatrix`, l'organizzazione della comunità
#: Extended Matrix, creata il 22 settembre 2026. s3Dgraphy ci è stato
#: trasferito quel giorno (misurato: `zalmoxes-laran/s3Dgraphy` → 301 →
#: `ExtendedMatrix/s3Dgraphy`), e la libreria sta lì perché è più longeva del
#: progetto che la consuma.
NELL_ECOSISTEMA = {
    "s3Dgraphy": "ExtendedMatrix/s3Dgraphy",
}

#: Vuoto, e la casella resta perché il giorno in cui qualcosa ci finisce dentro
#: deve portare la sua ragione scritta, come le esenzioni di `x-public-addresses`.
FUORI_DALLE_ORGANIZZAZIONI: dict[str, str] = {}


def _fratelli() -> dict[str, str]:
    """La mappa nome→URL, letta come la legge `fcn-install.sh`: il blocco
    `x-sibling-repos` del compose, e nient'altro."""
    dentro = False
    mappa: dict[str, str] = {}
    for riga in COMPOSE.read_text(encoding="utf-8").splitlines():
        if riga.startswith("x-sibling-repos:"):
            dentro = True
            continue
        if dentro:
            if riga and not riga[0].isspace():
                break
            m = re.match(r"\s+([^\s#:]+):\s*(\S+)", riga)
            if m:
                mappa[m.group(1)] = m.group(2)
    return mappa


def test_il_blocco_esiste_e_si_legge():
    mappa = _fratelli()
    assert mappa, (
        "`x-sibling-repos` non si legge dal compose. Se il blocco è stato "
        "spostato o rinominato, `fcn-install.sh` non lo trova più nemmeno lui "
        "— e cloni niente invece di dirlo."
    )
    mancanti = (set(NELL_ORGANIZZAZIONE) | set(NELL_ECOSISTEMA)) - set(mappa)
    assert not mancanti, f"mancano dal blocco: {sorted(mancanti)}"


@pytest.mark.parametrize("cartella,atteso", sorted(
    {**NELL_ORGANIZZAZIONE, **NELL_ECOSISTEMA}.items()))
def test_i_fratelli_si_clonano_dal_nome_canonico(cartella, atteso):
    url = _fratelli()[cartella]
    assert url == f"https://github.com/{atteso}.git", (
        f"`{cartella}` si clona da {url}.\n"
        f"Il nome canonico misurato è https://github.com/{atteso}.git — "
        f"se quello scritto qui funziona lo fa per il redirect di GitHub, che "
        f"è una cortesia e non un contratto."
    )


def test_nessun_profilo_personale_fra_i_repo_del_progetto():
    """Il predicato largo, quello che prende anche una riga NUOVA scritta male."""
    colpevoli = {
        nome: url for nome, url in _fratelli().items()
        if "zalmoxes-laran" in url and nome not in FUORI_DALLE_ORGANIZZAZIONI
    }
    assert not colpevoli, (
        f"questi si clonano da un profilo personale: {colpevoli}\n"
        f"Le case sono due — StratiGraph-ECCCH per i servizi del progetto, "
        f"ExtendedMatrix per la libreria — e un profilo personale non è "
        f"nessuna delle due. Se dev'esserci un'eccezione, va dichiarata in "
        f"FUORI_DALLE_ORGANIZZAZIONI con la sua ragione."
    )
