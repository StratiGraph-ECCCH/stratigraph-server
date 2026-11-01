"""La sessione scaduta diventa un pulsante (E.D., 1 nov 2026).

«Quando il token è scaduto andrebbe proposto un pulsante di login again.»
La console mostrava la frase nuda del nodo, «the token has expired», e niente
da premere. Ora: un 401 con un token in mano prova prima un rinnovo
silenzioso e ripete la richiesta; se non basta, una riga e «Accedi di nuovo».
"""
import pathlib
import re

ADMIN = pathlib.Path(__file__).resolve().parent.parent / "app" / "node_admin"
CONSOLE = (ADMIN / "console.js").read_text()
I18N = (ADMIN / "i18n.js").read_text()


def test_le_due_lingue_hanno_la_frase_e_il_pulsante():
    for chiave in ("console.session.lapsed", "console.session.again"):
        assert len(re.findall(rf'"{re.escape(chiave)}"', I18N)) == 2, chiave
    assert '"Accedi di nuovo"' in I18N and '"Sign in again"' in I18N


def test_un_401_prima_rinnova_e_ripete_poi_propone_il_pulsante():
    corpo = CONSOLE[CONSOLE.index("async function request("):]
    corpo = corpo[:corpo.index("\n}\n")]
    assert "answer.status === 401 && token && !retried" in corpo
    assert "renewNow()" in corpo and "request(method, path, body, true)" in corpo
    assert "sessionLapsed()" in corpo


def test_il_pulsante_rimanda_al_realm_e_torna_qui():
    corpo = CONSOLE[CONSOLE.index("function sessionLapsed()"):]
    corpo = corpo[:corpo.index("\n}\n")]
    assert 't("console.session.again")' in corpo
    assert "oidc.signIn(authConfig)" in corpo


def test_al_risveglio_il_rinnovo_in_ritardo_si_fa_subito():
    assert '"visibilitychange"' in CONSOLE
    assert "Date.now() >= refreshDue" in CONSOLE
