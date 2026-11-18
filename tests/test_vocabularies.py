"""The node serves the vocabulary packages it has (MICRO-PL02 «gestore dei
vocabolari», residue (1) of MICRO-U, E.D. 18 Nov 2026).

What would go wrong unseen, each named by a test below:

* a **tier C** source (a stub, a copy downloaded by hand on the node) leaving
  through any route — the catalogue, the zip, the bridge's reads;
* a zip that does not re-install as the SAME vocabulary on another machine;
* the bridge's routes answering a shape EMStudio's page does not read;
* an anonymous caller installing or removing on the node;
* an older s3Dgraphy (the pin, dev121: no `vocab_package_bytes`, no versions
  side by side) breaking the routes instead of falling back.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import auth as auth_module
from app import people as people_module
from app import vocabularies as vocab_module
from app.main import app

P = pytest.importorskip("s3dgraphy.authorities.packages")

SCHEME_A = "https://example.org/thesaurus/materiali/"
SCHEME_C = "https://example.org/iaa/periods/"
ANNA = "0000-0002-1825-0097"


def _nt(scheme, version, labels):
    out = [f"<{scheme}> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
           f"<http://www.w3.org/2004/02/skos/core#ConceptScheme> .",
           f"<{scheme}> <http://www.w3.org/2002/07/owl#versionInfo> \"{version}\" ."]
    for local, (lab, lang) in labels.items():
        out.append(f"<{scheme}{local}> <http://www.w3.org/2004/02/skos/core#prefLabel> "
                   f"\"{lab}\"@{lang} .")
    return ("\n".join(out) + "\n").encode("utf-8")


def _manifest(vid, version, *, tier="A", scheme=None, snapshot="2026-11-18"):
    m = {"format": P.PACKAGE_FORMAT, "id": vid, "version": version,
         "snapshot_date": snapshot, "languages": [], "title": {"it": f"titolo di {vid}"},
         "license": {"A": "CC0-1.0", "B": "CC-BY-SA-4.0", "C": "LicenseRef-IAA"}[tier],
         "tier": tier, "attribution": f"attribution of {vid}", "serves": ["material"]}
    if scheme:
        m["scheme"] = scheme
    return m


def _zip(m, data=None, fname="s.nt"):
    m = dict(m)
    if data is not None:
        m["source"] = {"file": f"source/{fname}", "sha256": hashlib.sha256(data).hexdigest()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps(m))
        if data is not None:
            z.writestr(m["source"]["file"], data)
    return buf.getvalue()


DATA_A1 = _nt(SCHEME_A, "1", {"a": ("arenaria", "it"), "b": ("ferro", "it")})
DATA_A2 = _nt(SCHEME_A, "2", {"a": ("arenaria", "it"), "b": ("ferro", "it"),
                              "c": ("bronzo", "it")})
DATA_C = _nt(SCHEME_C, "2026-10", {"p1": ("marmo antico", "it")})


@pytest.fixture
def node(tmp_path, monkeypatch):
    """A node whose folder holds a tier A vocabulary in two versions and a tier
    C one: its stub, completed by a copy downloaded by hand ON the node."""
    monkeypatch.setenv("EM_VOCABULARIES_DIR", str(tmp_path / "vocabularies"))
    P._changed()
    P.vocab_install(_zip(_manifest("materiali", "1", scheme=SCHEME_A,
                                   snapshot="2026-10-01"), DATA_A1))
    P.vocab_install(_zip(_manifest("materiali", "2", scheme=SCHEME_A), DATA_A2))
    stub = _manifest("iaa-periods", "2026-10", tier="C", scheme=SCHEME_C)
    stub["fetch"] = {"url": "https://example.org/iaa/periods.nt",
                     "digest": "sha256:" + hashlib.sha256(DATA_C).hexdigest()}
    P.vocab_install(_zip(stub))
    P.vocab_fetch_local("iaa-periods", fetch=lambda url: DATA_C)
    yield TestClient(app)
    P._changed()


def _ids(rows):
    return sorted({r["id"] for r in rows})


# ── the packages ────────────────────────────────────────────────────────────

def test_the_catalogue_lists_tier_A_and_B_only_with_relative_urls(node):
    got = node.get("/v1/vocabularies/catalog.json")
    assert got.status_code == 200
    packages = got.json()["packages"]
    assert _ids(packages) == ["materiali"]
    assert [(p["version"], p["url"]) for p in packages] == [
        ("2", "materiali.emvocab.zip"), ("1", "materiali.emvocab.zip?version=1")]
    first = packages[0]
    assert set(first) == {"id", "version", "snapshot_date", "title", "languages", "license",
                          "tier", "attribution", "serves", "sha256", "url"}
    assert first["sha256"] == hashlib.sha256(DATA_A2).hexdigest()
    # …and s3Dgraphy's own reader takes it as it is, the url resolved against it
    read = P.vocab_catalog("https://node.example/em/v1/vocabularies/catalog.json",
                           fetch=lambda url: got.content)
    assert read[0]["url"] == "https://node.example/em/v1/vocabularies/materiali.emvocab.zip"


def test_the_zip_reinstalls_as_the_same_vocabulary_elsewhere(node, tmp_path, monkeypatch):
    got = node.get("/v1/vocabularies/materiali.emvocab.zip")
    assert got.status_code == 200 and got.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(got.content))
    m = json.loads(z.read("manifest.json"))
    assert m["version"] == "2"
    assert not {"installed", "carriers", "removed_carriers", "copy_of", "owner"} & set(m)
    assert z.read(m["source"]["file"]) == DATA_A2
    old = node.get("/v1/vocabularies/materiali.emvocab.zip", params={"version": "1"})
    assert json.loads(zipfile.ZipFile(io.BytesIO(old.content)).read("manifest.json"))[
        "version"] == "1"

    # another machine
    monkeypatch.setenv("EM_VOCABULARIES_DIR", str(tmp_path / "elsewhere"))
    P._changed()
    s = P.vocab_install(got.content)
    assert (s["id"], s["version"], s["status"], s["sha256"]) == (
        "materiali", "2", "ready", hashlib.sha256(DATA_A2).hexdigest())
    assert P.search("bronzo")[0]["uri"] == SCHEME_A + "c"


def test_tier_C_never_leaves_the_node(node):
    refused = node.get("/v1/vocabularies/iaa-periods.emvocab.zip")
    assert refused.status_code == 403
    assert refused.json()["ok"] is False and "tier C" in refused.json()["error"]
    assert node.get("/v1/vocabularies/iaa-periods.emvocab.zip",
                    params={"version": "2026-10"}).status_code == 403
    assert node.get("/v1/vocabularies/nessuno.emvocab.zip").status_code == 404
    assert node.get("/v1/vocabularies/materiali.emvocab.zip",
                    params={"version": "9"}).status_code == 404
    # …nor through the bridge's reads, although the copy IS on the node
    assert P.search("marmo antico")                       # the library sees it
    assert node.get("/v1/vocab/search", params={"text": "marmo antico"}).json()[
        "candidates"] == []
    assert node.get("/v1/vocab/concepts", params={"uri": SCHEME_C + "p1"}).json()[
        "concepts"] == {}
    assert _ids(node.get("/v1/vocab/installed").json()["installed"]) == ["materiali"]


# ── the bridge's read routes ────────────────────────────────────────────────

def test_the_bridge_reads_answer_the_bridge_shapes(node):
    inst = node.get("/v1/vocab/installed").json()
    assert inst["ok"] is True and set(inst) == {"ok", "dir", "installed"}
    row = inst["installed"][0]
    assert row["version"] == "2" and [v["version"] for v in row["versions"]] == ["2", "1"]
    assert row["installed_from"] is None             # no path of the node's disk

    found = node.get("/v1/vocab/search", params={"text": "ferro", "lang": "it",
                                                 "serves": "material"}).json()
    assert found["ok"] is True
    assert [(c["uri"], c["match"], c["vocabulary"]) for c in found["candidates"]] == [
        (SCHEME_A + "b", "exact", "materiali")]
    # `serves` that nobody serves: asked again without it, as the bridge does
    again = node.get("/v1/vocab/search", params={"text": "ferro", "serves": "colour"}).json()
    assert [c["uri"] for c in again["candidates"]] == [SCHEME_A + "b"]

    con = node.get("/v1/vocab/concepts",
                   params=[("uri", SCHEME_A + "a"), ("uri", "https://x.org/none")]).json()
    assert con["ok"] is True and list(con["concepts"]) == [SCHEME_A + "a"]
    assert con["concepts"][SCHEME_A + "a"]["vocab"]["id"] == "materiali"
    assert con["concepts"][SCHEME_A + "a"]["concept"]["pref"]["it"] == "arenaria"


def test_catalog_and_updates_fetch_only_the_central_catalogue(node, monkeypatch):
    central = [{"id": "materiali", "version": "3", "snapshot_date": "2026-12-01",
                "url": "https://example.org/materiali-3.emvocab.zip"},
               {"id": "iaa-periods", "version": "2027-01", "snapshot_date": "2027-01-01"}]
    asked = []

    def fake_catalog(url=P.CENTRAL_CATALOG_URL, **kw):
        asked.append(url)
        return central
    monkeypatch.setattr(P, "vocab_catalog", fake_catalog)
    cat = node.get("/v1/vocab/catalog").json()
    assert cat == {"ok": True, "packages": central}
    upd = node.get("/v1/vocab/updates").json()
    assert upd["ok"] is True and [u["id"] for u in upd["updates"]] == ["materiali"]
    assert asked == [P.CENTRAL_CATALOG_URL] * 2
    # a public route that fetched any address would be a proxy
    other = node.get("/v1/vocab/catalog", params={"url": "http://169.254.169.254/"})
    assert other.status_code == 400 and other.json()["ok"] is False
    assert asked == [P.CENTRAL_CATALOG_URL] * 2


# ── the writes: an operator's ───────────────────────────────────────────────

@pytest.fixture
def enforcing(monkeypatch):
    class Enforcing:
        enforcing = True

        def describe(self):
            return "keycloak"
    monkeypatch.setattr(auth_module.authenticator, "settings", Enforcing())
    monkeypatch.setattr(auth_module.authenticator, "verify", lambda token: {"orcid": ANNA})
    monkeypatch.delenv("EM_OPERATORS", raising=False)
    # the node's register of people can make somebody an operator too: empty here
    monkeypatch.setattr(people_module, "PEOPLE_STORE", people_module.InMemoryPeopleStore())


def test_writes_need_a_token_and_the_operator_capability(node, enforcing, monkeypatch):
    body = {"zip_b64": base64.b64encode(_zip(_manifest("nuovo", "1"), DATA_A1)).decode()}
    assert node.post("/v1/vocab/install", json=body).status_code == 401
    auth = {"Authorization": "Bearer t"}
    refused = node.post("/v1/vocab/install", json=body, headers=auth)
    assert refused.status_code == 403 and "OPERATOR" in refused.json()["detail"]
    assert node.post("/v1/vocab/remove", json={"id": "materiali"},
                     headers=auth).status_code == 403
    # the reads stay open with auth on
    assert node.get("/v1/vocabularies/catalog.json").status_code == 200

    monkeypatch.setenv("EM_OPERATORS", ANNA)
    done = node.post("/v1/vocab/install", json=body, headers=auth).json()
    assert done["ok"] is True and done["installed"]["id"] == "nuovo"
    assert "nuovo" in _ids(node.get("/v1/vocabularies/catalog.json").json()["packages"])
    # a tier C package carrying its source: the library refuses it
    bad = _manifest("illecito", "1", tier="C")
    bad["fetch"] = {"url": "https://example.org/x.nt"}
    no = node.post("/v1/vocab/install", headers=auth,
                   json={"zip_b64": base64.b64encode(_zip(bad, DATA_C)).decode()})
    assert no.status_code == 422 and no.json()["ok"] is False
    gone = node.post("/v1/vocab/remove", json={"id": "nuovo"}, headers=auth).json()
    assert gone == {"ok": True, "removed": True}


# ── an older s3Dgraphy ──────────────────────────────────────────────────────

def test_without_the_facade_the_folder_is_read_here_in_both_layouts(node, tmp_path,
                                                                     monkeypatch):
    monkeypatch.setattr(vocab_module, "_facade", lambda: None)
    # MICRO-U's flat folder, as dev121 writes it
    flat = tmp_path / "vocabularies" / "piatto"
    (flat / "source").mkdir(parents=True)
    (flat / "source" / "s.nt").write_bytes(DATA_A1)
    m = _manifest("piatto", "0.1")
    m.update(source={"file": "source/s.nt", "format": "nt",
                     "sha256": hashlib.sha256(DATA_A1).hexdigest()},
             installed={"from": "/Users/x/piatto.emvocab.zip"})
    (flat / "manifest.json").write_text(json.dumps(m), encoding="utf-8")

    packages = node.get("/v1/vocabularies/catalog.json").json()["packages"]
    assert [(p["id"], p["version"], p["url"]) for p in packages] == [
        ("materiali", "2", "materiali.emvocab.zip"),
        ("materiali", "1", "materiali.emvocab.zip?version=1"),
        ("piatto", "0.1", "piatto.emvocab.zip")]
    for vid, data in (("piatto", DATA_A1), ("materiali", DATA_A2)):
        got = node.get(f"/v1/vocabularies/{vid}.emvocab.zip")
        assert got.status_code == 200
        z = zipfile.ZipFile(io.BytesIO(got.content))
        out = json.loads(z.read("manifest.json"))
        assert "installed" not in out and z.read(out["source"]["file"]) == data
    assert node.get("/v1/vocabularies/iaa-periods.emvocab.zip").status_code == 403
