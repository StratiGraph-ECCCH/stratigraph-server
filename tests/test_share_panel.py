"""«Condividi» stays small — and the test carries the reason, so whoever changes
it has to read why first.

The design note `EM_design_condividi-e-firma.md` (7 September 2026) separated two
jobs that had been one panel:

    1 · Presence     who may be at the table, and with what power   ← this panel
    2 · Property     whose the live copy is                         ← this panel
    3 · Contribution who did what, and how much                     ← NOT A DATUM
    4 · Authorship   the names on a published version, and order    ← the VERSION

The first two are operational and live on the node, beside the ACL and the owner.
The fourth is scientific and lives on the published version, in the catalogue,
agreed when publishing. **The third is not a field**: counting nodes would reward
whoever imports a GraphML of two hundred elements in one gesture and erase
whoever spends a week correcting forty — not a coarse approximation of merit but
ANOTHER THING, which resembles merit closely enough to be believed.

So the sharing surface must never name an author, an order of names, or a
scientific direction. Three consequences from the note, in its own words:

* being present is not having done — an author list populated from the ACL would
  be that claim, made by a default;
* an author need not be in the room: a director who never touched the graph is
  the normal case, so the publishing surface cannot validate names against the
  ACL and must not even suggest it;
* transferring a room transfers the operational job, not the signature.

A panel that asked «who signs?» would be asking somebody who is only adding a
colleague to the table.

WHAT THIS FILE IS NOT: a ban on the word «author» in this repository. The
narrative, the RDF projection and the catalogue all legitimately carry authors.
It is a fence around ONE surface.
"""

from __future__ import annotations

import pathlib
import re

_APP = pathlib.Path(__file__).resolve().parent.parent / "app"
I18N = (_APP / "node_admin" / "i18n.js").read_text(encoding="utf-8")

from tests import sorgenti  # noqa: E402

#: The words that would mean layer 3 or 4 had leaked into layer 1. Both
#: languages the dictionary completes, plus the ones a translator would reach
#: for — the four empty locales fall back to English, so English is the gate.
AUTHORSHIP = ("author", "autore", "autori", "authorship", "autorialità",
              "byline", "firma il", "signs", "credit", "crediti",
              "contributor", "contributo", "director", "direttore",
              "direzione scientifica", "first author", "primo autore",
              "corresponding")


def _share_strings() -> dict:
    """Every `share.*` string, in every locale the dictionary declares."""
    found = {}
    for locale in re.finditer(r"^  (\w+): \{(.*?)^  \}", I18N, re.S | re.M):
        code = locale.group(1)
        for key, value in re.findall(r'"(share\.[^"]+)":\s*"((?:[^"\\]|\\.)*)"',
                                     locale.group(2)):
            found[f"{code}/{key}"] = value
    return found






def test_NO_STRING_ON_THIS_SURFACE_NAMES_AUTHORSHIP():
    """Layer 4 is agreed when publishing, on the version. A field here would ask
    it of somebody who is adding a colleague to a table."""
    offenders = []
    for key, value in _share_strings().items():
        low = value.lower()
        for word in AUTHORSHIP:
            if word in low:
                offenders.append(f"{key}: …{word}…")
    assert not offenders, (
        "the sharing panel names authorship: " + " · ".join(offenders)
        + ". Authors belong to the PUBLISHED VERSION and are agreed when "
        "publishing — see EM_design_condividi-e-firma.md, Regola III. If a "
        "publishing surface is what you are building, it is a different one.")




def test_LA_GUARDIA_DELLAUTORIALITA_MORDE_ANCORA():
    """Prova 1 di 2: il caso vero — un nome che decide, in un id o in una
    variabile."""
    for finto in ('<div id="share-authors"></div>',
                  "const authors = roster.members.map(m => m.orcid);",
                  '<label>Autore principale</label>',
                  "// chi firma: byline",
                  "const credit = 'direzione scientifica';"):
        morde = [w for w in ("author", "autore", "byline", "credit",
                             "contributor")
                 if sorgenti.parola(w).search(finto)]
        assert morde, f"non morde su: {finto}"


def test_LA_GUARDIA_DELLAUTORIALITA_NON_MORDE_PIU_UNA_PAROLA_DENTRO_UNALTRA():
    """Prova 2 di 2: il falso positivo, ed è nel file vero a tre righe dal
    recinto."""
    onesti = ("headers: { Authorization: `Bearer ${token}` }",
              "authConfig.authorization_endpoint",
              "const chi = 'utente accreditato';",
              "await oidc.authorize(cfg);")
    for finto in onesti:
        morde = [w for w in ("author", "autore", "byline", "credit",
                             "contributor")
                 if sorgenti.parola(w).search(finto)]
        assert not morde, f"morde ancora su: {finto} → {morde}"










