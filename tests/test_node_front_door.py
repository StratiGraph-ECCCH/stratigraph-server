"""The node's front door — a composition, and never a fifth place to keep aligned.

The room browser grew a head: which node this is, who you are on it, what it
runs, and the three scopes — monuments, studies, rooms — which are one object at
three distances and therefore ONE card with three verbs.

What is worth a test here is not the layout. It is the property the page was
built around and that nothing in a browser would reveal: **it owns nothing.** No
list of services, no address of a neighbour, no rule about who may see what. The
day it knew one of those, it would have become the fifth thing to keep aligned —
the mistake `/v1/auth-config` and the handoff grammar exist to avoid.

`tests/test_handoff.py` already forbids the other half (a hand-built
`stratigraph://`); this file is about the addresses and the lists.
"""

from __future__ import annotations

import pathlib
import re

import pytest

import sorgenti
from fastapi.testclient import TestClient

_REPO = pathlib.Path(__file__).resolve().parent.parent
#: THE PAGES SEPARATED BY VERB on 6 September 2026 (design note
#: `EM_design_aprire-entrare-creare.md`). `index.html` is the VESTIBULE — who you
#: are, how the node is, where to go — and two verbs are pages of their own. The
#: assertions about a zone follow the zone: a test that kept asserting on the
#: vestibule what moved to `/work/` would go green by looking at the wrong file.






@pytest.fixture()
def client():
    from app import main

    return TestClient(main.app)


# ── /v1/node — what this node offers, and where ──────────────────────────────

def test_the_node_says_what_it_offers(client):
    answer = client.get("/v1/node")
    assert answer.status_code == 200
    payload = answer.json()
    assert payload["service"] == "stratigraph-server"
    named = {offer["name"] for offer in payload["offers"]}
    #: EMStudio entered on 11 November 2026: what this node SERVES you at
    #: `/em/studio/`, beside what you install (`tools`)
    assert named == {"stratigraph-catalog", "iiif", "stratigraph-chatbot", "emstudio", "nodeodm"}


def test_a_face_nobody_configured_is_ABSENT_and_has_no_link(client, monkeypatch):
    """Not an empty tile and not a guessed path: `not configured` plus the name
    of the variable that would configure it — the habit `auth.py` set."""
    for var in ("EM_CATALOG_INTERNAL", "EM_IIIF_INTERNAL", "EM_CHATBOT_INTERNAL",
                "NODEODM_URL", "EM_CATALOG_PUBLIC", "EM_FIELD_ASSISTANT_URL"):
        monkeypatch.delenv(var, raising=False)
    for offer in client.get("/v1/node").json()["offers"]:
        assert offer["state"] == "not configured", offer
        assert offer["url"] == "", offer
        assert offer["detail"], "an absent service must say what would name it"


def test_the_public_answer_carries_NO_internal_map(client, monkeypatch):
    """`/v1/admin/health` is operator-scoped because it names internal hosts and
    latencies. This one is the reduction, and the reduction has to be real."""
    monkeypatch.setenv("EM_CATALOG_INTERNAL", "http://stratigraph-catalog:8000")
    payload = client.get("/v1/node").json()
    for offer in payload["offers"]:
        assert set(offer) == {"name", "label", "state", "url", "detail", "what",
                              "capabilities"}
    assert "stratigraph-catalog:8000" not in str(payload), \
        "an internal hostname reached a public answer"
    # `capabilities` is the neighbour's own declaration, carried through — and it
    # is a reduction too: `node_health._reduce_capabilities` keeps objects with
    # string (or list-of-string) values and drops any shape it cannot vouch for.
    for offer in payload["offers"]:
        for capability in offer["capabilities"]:
            assert isinstance(capability, dict)
            for value in capability.values():
                assert isinstance(value, (str, list, bool)) or value is None


def test_the_tools_you_install_are_a_DIFFERENT_half(client):
    """The node runs the first half and cannot know anything about the second —
    so the second carries no state at all, only where to get it."""
    tools = client.get("/v1/node").json()["tools"]
    assert {t["name"] for t in tools} == {"emstudio", "blender"}
    for tool in tools:
        assert "state" not in tool
        assert tool["download"] and tool["manual"]


def test_where_the_tools_come_from_is_overridable(client, monkeypatch):
    """A node on a dig with no route out must be able to point at its own mirror
    rather than at a domain nobody there can reach."""
    monkeypatch.setenv("EM_TOOLS_EMSTUDIO_DOWNLOAD", "http://node.local/emstudio")
    tools = {t["name"]: t for t in client.get("/v1/node").json()["tools"]}
    assert tools["emstudio"]["download"] == "http://node.local/emstudio"


# ── the page owns nothing ────────────────────────────────────────────────────



def test_E_UN_VICINO_SCRITTO_DAVVERO_lo_prende_ancora():
    """La prima delle due prove: la guardia riparata morde ancora sul caso vero.

    L'indirizzo del chatbot è `/chat/...` — comincia lì — e questo è esattamente
    ciò che la regola vieta.
    """
    finta = 'const r = await fetch("/chat/v1/say", {method: "POST"});'
    chiesti = sorgenti.chiede(finta)
    assert [a for a in chiesti if a.startswith("/chat")] == ["/chat/v1/say"]
    finta_host = 'const base = "http://localhost:8000/v1";'
    assert [a for a in sorgenti.chiede(finta_host) if "localhost" in a]
















# ── one card, three verbs ────────────────────────────────────────────────────







# ── what a page must never print, and what it must never hide ───────────────
#
# Both of these were invisible until real data arrived on 4 September 2026: four
# case studies imported from the EM_CaseStudies archive, 37 studies in the
# catalogue, and the door showed three monument cards titled `[object Object]`
# over a list that was quietly eight-of-thirty-seven. Fake data hides exactly
# this class of bug, which is why the checks belong here rather than in a
# fixture.








# ── THE PAGES SEPARATE BY VERB (6 September 2026) ────────────────────────────
#
# The door did four jobs at once — what runs on this node, the rooms, the
# studies, the monuments — so whoever arrived for one walked through three. The
# cut, from the design note `EM_design_aprire-entrare-creare.md`:
#
#     consultare    the CATALOGUE (`/catalog/ui/`) — measured before removing
#                   anything: it already lists the published studies and already
#                   has the by-HDT view
#     lavorare      `/work/`
#     attrezzarsi   `/tools/`
#     amministrare  `/admin/`, and the map on the vestibule
#
# …and the door stays ONE: four equal pages would lose the property it had won,
# which is that you arrive and understand where everything is.













def test_all_three_doors_are_actually_SERVED(client):
    """LA CASA E IL SUO NOME (9 e 11 novembre 2026), chiesto alla porta.

    La vetrina a `/`, la casa a `/home/`, gli strumenti a `/tools/` — ciascuna
    con la SUA pagina (due montaggi sulla stessa cartella risponderebbero 200
    entrambi e mostrerebbero la stessa cosa). `/admin/` porta in casa per
    sempre (301) con la sua query; `/work/` (dal 12 novembre) e `/rooms/` non
    ci sono più, né i file sotto `/admin/`.
    """
    pages = {"/": "vetrina/vetrina.js", "/home/": "./boot.js", "/tools/": "./tools.js"}
    for path, script in pages.items():
        answer = client.get(path)
        assert answer.status_code == 200, (path, answer.status_code)
        assert script in answer.text, (path, "is not its own page")
    for path, target, code in (
            ("/admin/?room=scavo&join=t0k", "../home/?room=scavo&join=t0k", 301),
            ("/admin/", "../home/", 301),
            ("/admin", "home/", 301)):
        answer = client.get(path, follow_redirects=False)
        assert answer.status_code == code, (path, answer.status_code)
        assert answer.headers["location"] == target, path
    # `/work/` (12 novembre: EMStudio chiede al nodo dove sta la casa) e i file
    # sotto `/admin/` (il catalogo importa `/home/bar.js`) non esistono più
    for gone in ("/rooms/", "/rooms/rooms.js", "/work/rooms.css",
                 "/work/", "/work/?room=scavo&join=t0k", "/work/index.html",
                 "/admin/bar.js", "/admin/i18n.js"):
        assert client.get(gone, follow_redirects=False).status_code == 404, gone
    # …e i file restano serviti: la libreria del QR, i fogli e i moduli della
    # casa, che le altre facce importano da `/home/` (il catalogo: `bar.js`)
    for asset in ("/vendor/qrcode-generator-1.4.4.js", "/home/console.css",
                  "/home/bar.js", "/home/i18n.js", "/vetrina/vetrina.css"):
        assert client.get(asset).status_code == 200, asset


def test_the_new_doors_are_REGISTERED_WITH_THE_REALM():
    """Found by clicking «Sign in» on `/em/work/` in Chrome: the realm answered
    «Invalid parameter: redirect_uri». A door the identity provider has never
    heard of cannot be signed in from, and neither the page nor the server says
    so — the failure is a Keycloak error page one redirect away.

    So every door this server mounts must appear in the dev realm's `em-console`
    client, in the same spellings its siblings use: the bare mount on :8000 and
    the two https hostnames behind Caddy. A door registered in three of the four
    is a door that works until somebody runs the stack the other way.

    THIS DEFENDS THE FIXTURE ONLY, and says so: a deployed realm is not in this
    repo — it is configured wherever that Keycloak lives — so the end-of names
    that as a deploy step instead of pretending a test covers it.
    """
    import json
    realm = json.loads((_REPO / "dev-stack" / "keycloak"
                        / "realm-em-dev.json").read_text(encoding="utf-8"))
    console = next(c for c in realm["clients"] if c["clientId"] == "em-console")
    uris = set(console["redirectUris"])
    #: the pages a person can SIGN IN from since 11 November 2026: the house.
    #: (`/tools/` and the showcase sign nobody in; `/tools/*` stays registered
    #: and is harmless. `rooms`/`work`/`admin` may stay too: a spare URI is not a
    #: defect — `test_doors_and_realm.py` says so.)
    for verb in ("home", "tools"):
        for wanted in (f"http://localhost:8000/{verb}/*",
                       f"http://127.0.0.1:8000/{verb}/*",
                       f"https://em.localhost:8443/em/{verb}/*",
                       f"https://localhost:8443/em/{verb}/*"):
            assert wanted in uris, wanted




