# The vocabularies a node has, and how they leave it

*StratiGraph Server · written for whoever builds a vocabulary manager, or a
page that looks words up on a node. Every request and response on this page
was run against the dev stack on 18 November 2026, between 20:34 and 20:35 UTC;
nothing is written by hand except the abridgements, which say so, and the
indentation of the JSON. For the clickable reference, open `/docs` on any node
and look under the tag **vocabularies**.*

## What a node's vocabulary folder is

A vocabulary — a thesaurus of materials, a list of periods, a gazetteer — comes
to the Extended Matrix tools as a **package**: a `.emvocab.zip` holding a
`manifest.json` and the source file, unmodified, whose sha256 the manifest
declares. s3Dgraphy installs packages into one folder per machine, shared by
every EM tool on it, and indexes them so that a word typed in a form can be
matched to a concept.

A node has the same folder. Where it lives is `EM_VOCABULARIES_DIR`, described
with the other variables in `docs/DEPLOYMENT.md`; the one thing worth repeating
here is that it must be a persistent volume, or the vocabularies go with the
container.

Every package carries a **tier**, and the tier decides whether it may travel:

* **A** — may be redistributed, with attribution;
* **B** — may be redistributed as an unmodified file;
* **C** — may not. The package is a *stub*: a manifest and a pointer to where
  the source can be downloaded, by each machine for itself. A copy downloaded
  on the node stays on the node.

**Tier C never leaves the node** — not its stub, not its local copy, not a label
found in it. Every read on this page filters to tiers A and B; that is not a
setting, it is how the routes are written.

The node offers its folder two ways: as **packages**, for another machine's
vocabulary manager, and as **the routes of EMStudio's bridge**, so that the
page EMStudio shows on a desktop works the same on the node. The reads are
public (a tier A or B package is made to travel); the three writes want a token
*and* the operator capability, the same check as the node console
(`docs/NODE-ADMIN-API.md`).

Below, `$NODE` is `https://em.localhost:8443/em` and `$TOKEN` an operator's
token from `dev-stack/token.sh`.

## Installing, from the central repository

The central repository of the project publishes its packages as GitHub release
assets, with a catalogue beside them. **What it offers** is
`GET /v1/vocab/catalog` — the node fetches the catalogue for the page, because a
page cannot read GitHub's release across origins:

```bash
curl -s $NODE/v1/vocab/catalog
```

```json
{
  "ok": true,
  "packages": [
    {"id": "getty-aat-materials", "version": "2026-11-18", "tier": "A",
     "serves": ["material_type", "construction_technique"], "bytes": 502787,
     "url": "https://github.com/ExtendedMatrix/vocabularies/releases/latest/download/getty-aat-materials-2026-11-18.emvocab.zip",
     "…": "title, languages (sixty-five of them), license, attribution, snapshot_date, sha256 (abridged here)"},
    {"id": "iccd-ra-materia", "version": "2018-09", "tier": "B",
     "serves": ["material_type"], "bytes": 45520,
     "url": "https://github.com/ExtendedMatrix/vocabularies/releases/latest/download/iccd-ra-materia-2018-09.emvocab.zip",
     "…": "as above (abridged here)"}
  ]
}
```

The node fetches **only** the central catalogue. A public route that fetched any
address a caller named would be a proxy for anybody; so `?url=` is accepted
only when it *is* the central catalogue:

```bash
curl -s "$NODE/v1/vocab/catalog?url=https://example.org/catalog.json"
```

```json
{"ok": false, "error": "on a node, `url` may only be the central catalogue (https://github.com/ExtendedMatrix/vocabularies/releases/latest/download/catalog.json); this node's own is /v1/vocabularies/catalog.json"}
```

That is a `400`; when the central catalogue cannot be reached, a `502`.

**Installing** is `POST /v1/vocab/install` with `{"url": …}` or
`{"zip_b64": …}` (the bytes of a package, base64). The node downloads, checks
the sha256, compiles the index. Without a token it is a `401`; with the token
of somebody who is not an operator, the console's `403` and its sentence; with
neither field, a `400` (`"install takes {url} or {zip_b64}"`); a package that
does not hold, a `422`.

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/ExtendedMatrix/vocabularies/releases/latest/download/iccd-ra-materia-2018-09.emvocab.zip"}' \
  $NODE/v1/vocab/install
```

```json
{
  "ok": true,
  "installed": {
    "id": "iccd-ra-materia",
    "version": "2018-09",
    "snapshot_date": "2018-09-01",
    "title": {"en": "Thesaurus for the definition of material — archaeological finds (ICCD)",
              "it": "Thesaurus per la definizione della materia — reperti archeologici (ICCD)"},
    "languages": ["it"],
    "license": "CC BY-SA 3.0 IT",
    "tier": "B",
    "serves": ["material_type"],
    "scheme": "http://dati.beniculturali.it/vocabularies/materia_e_tecnica-ra/def/",
    "status": "ready",
    "installed_from": "https://github.com/ExtendedMatrix/vocabularies/releases/latest/download/iccd-ra-materia-2018-09.emvocab.zip",
    "sha256": "05f8a3b8339eca60f6e02e130384e280717ee3ab61ff31e973fb5ded22f93969",
    "warnings": [],
    "…": "license_url, attribution, facet, authority, homepage, carriers, owner (abridged here)"
  }
}
```

**What is newer** at the centre than on this node is `GET /v1/vocab/updates`,
compared with what the node holds of tiers A and B. With the package just
installed:

```json
{"ok": true, "updates": []}
```

Each update, when there is one, is `{id, installed, available, url}`; the same
`?url=` rule, the same `400` and `502`.

**Removing** is `POST /v1/vocab/remove {"id": …}`, operators only, and answers
`{"ok": true, "removed": true}`.

## Looking words up

**What is installed** is `GET /v1/vocab/installed`: the newest version of each
vocabulary with its `versions`, tiers A and B only. `dir` says where the
packages are *served* (`vocabularies/`, relative to `/v1/`), not where they lie
on the node's disk — and `installed_from` is said only when it is an address,
never a path of the node:

```json
{"ok": true, "dir": "vocabularies/",
 "installed": [{"id": "iccd-ra-materia", "version": "2018-09", "tier": "B", "status": "ready",
                "versions": [{"version": "2018-09", "snapshot_date": "2018-09-01",
                              "status": "ready", "…": "…"}],
                "…": "the same summary as the install answer (abridged here)"}]}
```

**Candidates for a word** — `GET /v1/vocab/search?text=…&lang=…&serves=…&limit=…`.
Exact matches come before close ones, and none is an identity: the person
choosing decides. With `serves` (the field the word is for) and nothing found,
every vocabulary is asked:

```bash
curl -s "$NODE/v1/vocab/search?text=bronzo&lang=it&limit=3"
```

```json
{
  "ok": true,
  "candidates": [
    {"uri": "http://dati.beniculturali.it/vocabularies/materia_e_tecnica-ra/def/026",
     "label": "bronzo", "lang": "it", "match": "exact",
     "vocabulary": "iccd-ra-materia", "version": "2018-09", "tier": "B", "broader": [],
     "attribution": "ICCD — Ministero della Cultura. Thesaurus per la definizione della materia per i reperti archeologici, versione settembre 2018 (M. L. Mancinelli; C. Veninata, M. Porena). CC BY-SA 3.0 IT"},
    {"uri": "http://dati.beniculturali.it/vocabularies/materia_e_tecnica-ra/def/026.001",
     "label": "bronzo a bulino", "lang": "it", "match": "close",
     "vocabulary": "iccd-ra-materia", "version": "2018-09", "tier": "B",
     "broader": ["http://dati.beniculturali.it/vocabularies/materia_e_tecnica-ra/def/026"],
     "attribution": "… (abridged here)"},
    {"uri": "http://dati.beniculturali.it/vocabularies/materia_e_tecnica-ra/def/026.008",
     "label": "bronzo a niello", "lang": "it", "match": "close",
     "…": "as above (abridged here)"}
  ]
}
```

On the dev stack, `?serves=construction_technique` found nothing in the one
vocabulary installed (it serves `material_type`) and fell back to asking all of
them: the same `bronzo` and `bronzo a bulino` came back.

**What a URI means** — `GET /v1/vocab/concepts?uri=…&uri=…`: each URI found in
an installed vocabulary of tier A or B, with that vocabulary's summary. A URI
found nowhere — here, one from a tier C scheme — is simply absent from the
answer:

```bash
curl -s "$NODE/v1/vocab/concepts?uri=http://dati.beniculturali.it/vocabularies/materia_e_tecnica-ra/def/026.001&uri=https://example.org/iaa/periods/p1"
```

```json
{
  "ok": true,
  "concepts": {
    "http://dati.beniculturali.it/vocabularies/materia_e_tecnica-ra/def/026.001": {
      "concept": {"broader": ["http://dati.beniculturali.it/vocabularies/materia_e_tecnica-ra/def/026"],
                  "pref": {"it": "bronzo a bulino"}},
      "vocab": {"id": "iccd-ra-materia", "version": "2018-09", "tier": "B",
                "…": "the same summary as above (abridged here)"}
    }
  }
}
```

## Serving packages to another machine

This is the other side: the node as one of the places a package comes from.
Another machine's vocabulary manager — EMStudio on a laptop, another node —
reads the node's catalogue in the same format as the central one and downloads
from it.

**The catalogue** — `GET /v1/vocabularies/catalog.json`: one row per installed
*version* of tier A or B with its source on the node. `url` is relative to the
catalogue: `<id>.emvocab.zip` for the newest version, with `?version=` for the
older ones.

```bash
curl -s $NODE/v1/vocabularies/catalog.json
```

```json
{
  "packages": [
    {"id": "iccd-ra-materia", "version": "2018-09", "snapshot_date": "2018-09-01",
     "tier": "B", "license": "CC BY-SA 3.0 IT", "languages": ["it"],
     "serves": ["material_type"],
     "sha256": "05f8a3b8339eca60f6e02e130384e280717ee3ab61ff31e973fb5ded22f93969",
     "url": "iccd-ra-materia.emvocab.zip",
     "…": "title, attribution (abridged here)"}
  ]
}
```

**A package** — `GET /v1/vocabularies/{vocab_id}.emvocab.zip[?version=…]`,
rebuilt from the node's folder: the manifest, minus what it says about *this*
machine (who installed it, carriers, owner), and the source byte for byte — the
bytes the installer on the other side checks against `sha256`.

```bash
curl -s -D - -o iccd.zip $NODE/v1/vocabularies/iccd-ra-materia.emvocab.zip
unzip -l iccd.zip
```

```text
HTTP/2 200
content-disposition: attachment; filename="iccd-ra-materia.emvocab.zip"
content-type: application/zip
content-length: 45520

  Length      Date    Time    Name
---------  ---------- -----   ----
     1422  11-18-2026 20:34   manifest.json
  1497184  11-18-2026 20:34   source/ICCD_Vocabolario_definizione_della_materia_reperti_archeologici.rdf
---------                     -------
  1498606                     2 files
```

(The other response headers are left out here.) A vocabulary or a version the
node does not have is a `404`:

```json
{"ok": false, "error": "iccd-ra-materia 2017-01: not installed on this node"}
```

**And tier C.** To show what the node does with one, a tier C stub was
installed on the dev stack — a manifest with `"tier": "C"` and a `fetch`
pointer, no source — with `POST /v1/vocab/install {"zip_b64": …}`. It was
installed (`"status": "stub"`), did not appear in the catalogue nor in
`/v1/vocab/installed`, and asking for its package was refused:

```bash
curl -s $NODE/v1/vocabularies/iaa-periods.emvocab.zip
```

```json
{"ok": false, "error": "iaa-periods: tier C — not redistributable; its copy stays on the machine that downloaded it (install its manifest and «Download locally» from the source)"}
```

That is a `403`. A tier C package that arrives *carrying* its source is refused
by the library at install time (`422`).

**Downloading a tier C source onto the node** is
`POST /v1/vocab/fetch-local {"id": …}`, operators only: the node follows the
stub's `fetch` pointer, checks the digest, and keeps the copy for itself — no
route above hands it on. The stub on the dev stack pointed at an address that
does not exist, so the answer was the refusal, a `502`:

```json
{"ok": false, "error": "not reachable: HTTP Error 404: Not Found"}
```

A successful `fetch-local` answers `{"ok": true, "installed": summary}`; it was
not run here, because no tier C source was at hand to point at. The stub was
then removed (`{"ok": true, "removed": true}`).

## Every route

| endpoint | what it does | token |
|---|---|---|
| `GET /v1/vocabularies/catalog.json` | The packages this node serves (tiers A and B) | — |
| `GET /v1/vocabularies/{vocab_id}.emvocab.zip` | One package, rebuilt from the node's folder; tier C is `403` | — |
| `GET /v1/vocab/installed` | What is installed here, tiers A and B | — |
| `GET /v1/vocab/search` | Candidates for a word | — |
| `GET /v1/vocab/concepts` | The concepts of some URIs | — |
| `GET /v1/vocab/catalog` | What the central repository offers | — |
| `GET /v1/vocab/updates` | What the central repository has newer than this node | — |
| `POST /v1/vocab/install` | Install a package, from `url` or `zip_b64` | operator |
| `POST /v1/vocab/remove` | Remove a vocabulary | operator |
| `POST /v1/vocab/fetch-local` | Download a tier C source onto this node only | operator |

## Where to read more

The code is `app/vocabularies.py`, and what it promises is held by
`tests/test_vocabularies.py`. The package format, the tiers and the index are
s3Dgraphy's (`s3dgraphy.authorities.packages`); the bridge whose routes these
mirror is EMStudio's `tools/em_vocab.py`.
