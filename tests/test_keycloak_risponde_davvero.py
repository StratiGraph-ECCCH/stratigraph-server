"""«Configurato» non vuol dire «risponde».

Il 26 novembre 2026 un nodo ha lavorato un giorno intero con la password
dell'amministratore di Keycloak cambiata in Keycloak e non nella configurazione.
Tutto diceva «configurato» — `KeycloakAdmin.configured()` guarda se le
impostazioni ci sono, non se funzionano —, nessuno veniva creato, e il primo
accesso con ORCID è fallito con `user_not_found`. Una giornata persa a cercare
nel posto sbagliato.

Qui si misura che quello stato adesso **si vede**: la console lo dice, con il
livello giusto e con la causa più probabile scritta dentro la frase.
"""

from __future__ import annotations

import pytest

from app import keycloak_admin as kc                       # noqa: E402
from app import node_kind                                  # noqa: E402

ENV = {"EM_NODE_KIND": "institutional", "EM_KC_ADMIN_URL": "http://keycloak:8080",
       "EM_KC_REALM": "em-dev", "EM_KC_ADMIN_USER": "admin",
       "EM_KC_ADMIN_PASSWORD": "quella-vecchia"}


def _codici(**facts):
    return [c["code"] for c in node_kind.checks(ENV, **facts)]


def test_senza_credenziali_lo_dice_come_prima():
    assert "no-kc-admin" in _codici(kc_configured=False)


def test_configurato_e_vivo_non_dice_niente():
    codes = _codici(kc_configured=True, kc_alive=True)
    assert "no-kc-admin" not in codes and "kc-admin-refused" not in codes


def test_configurato_e_rifiutato_e_un_guasto_non_un_avviso():
    checks = node_kind.checks(ENV, kc_configured=True, kc_alive=False,
                              kc_why="no admin token from Keycloak (HTTP 401)")
    refused = [c for c in checks if c["code"] == "kc-admin-refused"]
    assert refused, "lo stato che è costato una giornata deve comparire"
    one = refused[0]
    assert one["level"] == "bad", "un nodo che non può creare nessuno non è un avviso"
    assert "401" in one["en"] and "401" in one["it"], "la causa viaggia nella frase"
    for said in ("EM_KC_ADMIN_PASSWORD", "recreate the container"):
        assert said in one["en"], f"la frase deve dire {said!r}"


def test_non_provato_resta_zitto():
    """`kc_alive=None` = nessuno ha provato: non si inventa né un sì né un no."""
    codes = _codici(kc_configured=True, kc_alive=None)
    assert "kc-admin-refused" not in codes and "no-kc-admin" not in codes


# ── la prova vera, contro un Keycloak finto ──────────────────────────────────

def _admin(answer):
    client = kc.KeycloakAdmin(ENV, opener=None)
    client._request = lambda *a, **k: answer          # noqa: SLF001
    return client


def test_alive_chiede_un_token_e_non_si_fida_della_cache():
    client = _admin((200, {"access_token": "t"}))
    client._token = "vecchio"                          # noqa: SLF001
    ok, why = client.alive()
    assert ok and why == "answers"
    assert client._token == "t", "il token della prova è quello di adesso"  # noqa: SLF001


def test_alive_riporta_il_rifiuto_con_il_suo_stato():
    ok, why = _admin((401, {"error": "invalid_grant"})).alive()
    assert ok is False and "401" in why


def test_alive_su_un_nodo_che_non_lo_configura_non_prova_nemmeno():
    client = kc.KeycloakAdmin({}, opener=None)
    ok, why = client.alive()
    assert ok is False and why == "not configured"
