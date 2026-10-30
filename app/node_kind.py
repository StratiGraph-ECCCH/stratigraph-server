"""WHAT KIND OF NODE THIS IS — declared, never guessed (E.D., 30 Oct 2026).

Every node runs the same StratiGraph Server: same images, same API, same
em.json. What differs is the configuration, and a configuration that fits one
kind of node is a mistake on another — test people on an institutional node, a
field node that trusts nobody and so cannot receive its team. The node therefore
SAYS what it is (`EM_NODE_KIND`), and the server holds it to the safe defaults
of that kind:

* **personal** — one person's computer; files stay in their folders by
  reference. Nothing to manage.
* **field** — the Field Computing Node: a laptop or a box on the excavation,
  often without a network. People sign in with a field password; the team
  arrives in a signed package from the institutional node.
* **institutional** — the node of an institution, reachable on the internet
  under a public name. People sign in with ORCID; it prepares the packages for
  the field and receives them back.

Undeclared reads as `node`: the server works as before and the console asks the
manager to declare the kind. `EM_NODE_PROFILE=personal` (the older setting)
still means personal.

What the kind CHANGES, and nothing more:

* an **institutional** node refuses test people even when
  `EM_ALLOW_TEST_PEOPLE` is on — the one rule that is enforced, because a
  fictitious person with a password on a public node is a door;
* everything else is ADVICE: `checks()` lists what is missing for this kind, in
  sentences, and the console shows it. A node is never stopped by advice.
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Any, Dict, List, Optional

KINDS = ("personal", "field", "institutional")

#: what each kind is called, for people
WORDS = {
    "personal": ("nodo personale", "personal node"),
    "field": ("nodo da campo", "field node"),
    "institutional": ("nodo istituzionale", "institutional node"),
    "node": ("tipo non dichiarato", "kind not declared"),
}


def _env(environ: Optional[Dict[str, str]]) -> Dict[str, str]:
    return environ if environ is not None else os.environ  # type: ignore[return-value]


def kind(environ: Optional[Dict[str, str]] = None) -> str:
    env = _env(environ)
    declared = (env.get("EM_NODE_KIND") or "").strip().lower()
    if declared in KINDS:
        return declared
    older = (env.get("EM_NODE_PROFILE") or "").strip().lower()
    if older in KINDS:
        return older
    return "node"


def _check(level: str, code: str, it: str, en: str) -> Dict[str, str]:
    return {"level": level, "code": code, "it": it, "en": en}


def _public_name_is_local(base: str) -> bool:
    host = (urllib.parse.urlsplit(base).hostname or "").lower()
    return (not host or host in ("localhost", "127.0.0.1", "::1")
            or host.endswith((".localhost", ".local", ".test", ".lan", ".internal")))


def checks(environ: Optional[Dict[str, str]] = None, *, public_base: str = "",
           kc_configured: bool = False, trusted_nodes: int = 0,
           test_people_on: bool = False, node_name: str = "") -> List[Dict[str, str]]:
    """What this node lacks for its kind, as sentences. Levels: `bad` (a rule
    the server enforces, or a real risk), `warn` (it works, but not as the kind
    needs), `info` (worth knowing)."""
    k = kind(environ)
    out: List[Dict[str, str]] = []
    if k == "node":
        out.append(_check("warn", "undeclared",
                          "Il tipo di nodo non è dichiarato. Imposta EM_NODE_KIND a field (nodo da campo) "
                          "o institutional (nodo istituzionale): il nodo applica le impostazioni prudenti di quel tipo.",
                          "The node kind is not declared. Set EM_NODE_KIND to field or institutional: the node "
                          "then applies that kind's safe defaults."))
        return out
    if k == "personal":
        return out
    if not node_name:
        out.append(_check("info", "no-name",
                          "Il nodo non ha un nome proprio (EM_NODE_NAME) né un indirizzo pubblico: "
                          "gli altri nodi lo conosceranno con un nome generico.",
                          "The node has no name of its own (EM_NODE_NAME) nor a public address: other nodes "
                          "will know it by a generic name."))
    if not kc_configured:
        out.append(_check("warn", "no-kc-admin",
                          "Il server non può gestire gli account di Keycloak (manca EM_KC_ADMIN_URL con le "
                          "credenziali): le password locali si danno solo con gli script del nodo.",
                          "The server cannot manage Keycloak accounts (EM_KC_ADMIN_URL and credentials are "
                          "missing): local passwords can only be given with the node's scripts."))
    if k == "institutional":
        if test_people_on:
            out.append(_check("bad", "test-people-refused",
                              "EM_ALLOW_TEST_PEOPLE è acceso, ma su un nodo istituzionale le persone di prova "
                              "sono rifiutate comunque. Spegnilo nella configurazione.",
                              "EM_ALLOW_TEST_PEOPLE is on, but an institutional node refuses test people anyway. "
                              "Turn it off in the configuration."))
        if not public_base:
            out.append(_check("warn", "no-public-name",
                              "Il nodo istituzionale non dichiara il suo indirizzo pubblico (EM_PUBLIC_BASE).",
                              "The institutional node does not declare its public address (EM_PUBLIC_BASE)."))
        elif _public_name_is_local(public_base) or not public_base.startswith("https://"):
            out.append(_check("warn", "local-name",
                              f"L'indirizzo {public_base} non è un nome pubblico in https: dall'esterno non si raggiunge.",
                              f"The address {public_base} is not a public https name: it cannot be reached from outside."))
    if k == "field":
        if test_people_on:
            out.append(_check("info", "test-people-on",
                              "Le persone di prova sono accese: va bene per le prove, spegnile prima di andare sul campo.",
                              "Test people are on: fine for trials, turn them off before going to the field."))
        if trusted_nodes == 0:
            out.append(_check("warn", "trusts-nobody",
                              "Il nodo da campo non ha ancora nessun nodo di fiducia: aggiungi la chiave del nodo "
                              "istituzionale (Trasferimenti) prima di partire, finché c'è rete.",
                              "The field node trusts no node yet: add the institutional node's key (Transfers) "
                              "before leaving, while there is a network."))
    return out


def describe(environ: Optional[Dict[str, str]] = None, **facts: Any) -> Dict[str, Any]:
    k = kind(environ)
    it, en = WORDS[k]
    return {"kind": k, "declared": k != "node", "word_it": it, "word_en": en,
            "checks": checks(environ, **facts)}
