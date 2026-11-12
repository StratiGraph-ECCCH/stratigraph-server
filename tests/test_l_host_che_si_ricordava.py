"""L'host che si ricordava — e la porta che rifiuta (9 novembre 2026).

════════════════════════════════════════════════════════════════════════════════
## IL GUASTO, MISURATO

Il 31 ottobre `fcn-up.sh HOST` scriveva l'host in coda a `.env.dev`
(`FCN_HOST=…`) e lo rileggeva alla corsa dopo. Nello stesso `.env.dev`, a mano,
erano finite quattro righe per un telefono in rete locale, fra cui

    REALM_FILE=./keycloak/realm-em-dev.192.168.1.214.json

e `REALM_FILE` lo script lo esportava solo nel ramo `--campo` e nel ramo
«host diverso da em.localhost». Con l'host di default nessuno lo esportava:
compose vedeva la riga scritta a mano, Keycloak importava il realm di un'altra
macchina, e il login moriva su `redirect_uri` con tutte le porte a 200.

## I TRE CANCELLI

* con `OIDC_ISSUER=` avanzato in `.env.dev`, `fcn-up.sh` rifiuta e nomina la riga;
* con l'host di default, `REALM_FILE` arriva a compose ESPORTATO;
* dopo `./fcn-up.sh pippo.local`, una corsa senza argomenti usa em.localhost.

Si chiede alla porta: le prove eseguono lo script, con un `docker` finto che
registra l'ambiente con cui compose viene chiamato per `up`.
"""

from __future__ import annotations

import pathlib

from test_emstudio_sotto_supervisione import (
    _curl_finto, _dev_stack_ermetico, _run_ermetico)
from test_un_nodo_che_si_accende_altrove import _finti, _uname, needs_bash


def _docker_che_registra(bin_: pathlib.Path, tmp_path) -> None:
    """Il `docker` finto di `_finti`, con davanti un involucro che annota
    `REALM_FILE` e `OIDC_ISSUER` come li vede compose al momento di `up`."""
    vero = bin_ / "docker"
    vero.rename(bin_ / "docker.finto")
    vero.write_text(
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        '  if [ "$a" = "up" ]; then\n'
        f'    echo "UP REALM_FILE=${{REALM_FILE-<non esportato>}} '
        f'OIDC_ISSUER=${{OIDC_ISSUER-<non esportato>}}" >> "{tmp_path}/ambiente.txt"\n'
        '  fi\n'
        'done\n'
        f'exec "{bin_}/docker.finto" "$@"\n')
    vero.chmod(0o755)


def _banco(tmp_path):
    dev = _dev_stack_ermetico(tmp_path)
    bin_ = _finti(tmp_path, docker_ok=True, plugin=True, autonomo=False)
    _uname(bin_, "linux")
    _curl_finto(bin_, tmp_path)
    _docker_che_registra(bin_, tmp_path)
    return dev, bin_


def _visto_da_up(tmp_path) -> list:
    f = tmp_path / "ambiente.txt"
    return f.read_text().splitlines() if f.exists() else []


def _su(dev, bin_, tmp_path, *args):
    return _run_ermetico(dev, "fcn-up.sh", bin_, tmp_path, args=args,
                         extra_env={"SG_STUDIO_DIR": str(tmp_path / "nessun-EMStudio")})


# ═══ 1 · la porta che rifiuta ══════════════════════════════════════════════

@needs_bash
def test_OIDC_ISSUER_AVANZATO_IN_ENV_DEV_si_rifiuta_e_nomina_la_riga(tmp_path):
    dev, bin_ = _banco(tmp_path)
    env = dev / ".env.dev"
    righe = env.read_text().splitlines()
    righe.append("OIDC_ISSUER=https://192.168.1.214:8443/auth/realms/em-dev")
    env.write_text("\n".join(righe) + "\n")
    riga = len(righe)

    done = _su(dev, bin_, tmp_path)

    assert done.returncode != 0, done.stdout
    assert "OIDC_ISSUER" in done.stderr, done.stderr
    assert f".env.dev riga {riga}" in done.stderr, done.stderr
    assert "Togli quelle righe" in done.stderr
    #: …e si è fermato prima di accendere qualunque cosa
    assert _visto_da_up(tmp_path) == []


@needs_bash
def test_REALM_FILE_A_MANO_si_rifiuta_anche_lui(tmp_path):
    """La riga che il 9 novembre faceva morire il login."""
    dev, bin_ = _banco(tmp_path)
    env = dev / ".env.dev"
    env.write_text(env.read_text()
                   + "REALM_FILE=./keycloak/realm-em-dev.192.168.1.214.json\n")
    done = _su(dev, bin_, tmp_path)
    assert done.returncode != 0
    assert "REALM_FILE" in done.stderr, done.stderr
    assert _visto_da_up(tmp_path) == []


@needs_bash
def test_LE_RIGHE_DEL_MODELLO_non_fermano_un_clone(tmp_path):
    """`.env.dev.example` porta `EM_DEV_DOMAIN`, `EM_PUBLIC_BASE` e
    `EM_IIIF_PUBLIC`: un `.env.dev` appena nato dal modello deve accendersi."""
    dev, bin_ = _banco(tmp_path)
    modello = (dev / ".env.dev.example").read_text()
    for v in ("EM_DEV_DOMAIN=", "EM_PUBLIC_BASE=", "EM_IIIF_PUBLIC="):
        assert f"\n{v}" in modello, f"il modello non porta più {v}: rivedi l'eccezione"
    done = _su(dev, bin_, tmp_path)
    assert done.returncode == 0, done.stderr + done.stdout
    assert len(_visto_da_up(tmp_path)) == 1


# ═══ 2 · il caso di default è un caso ══════════════════════════════════════

@needs_bash
def test_CON_EM_LOCALHOST_REALM_FILE_E_ESPORTATO(tmp_path):
    dev, bin_ = _banco(tmp_path)
    done = _su(dev, bin_, tmp_path)
    assert done.returncode == 0, done.stderr + done.stdout
    (up,) = _visto_da_up(tmp_path)
    assert "REALM_FILE=./keycloak/realm-em-dev.json " in up, up
    assert "OIDC_ISSUER=https://em.localhost:8443/auth/realms/em-dev" in up, up


# ═══ 3 · una corsa non lascia tracce sulla successiva ══════════════════════

@needs_bash
def test_DOPO_UN_HOST_DATO_A_MANO_la_corsa_dopo_usa_em_localhost(tmp_path):
    dev, bin_ = _banco(tmp_path)
    prima = (dev / ".env.dev").read_text()

    uno = _su(dev, bin_, tmp_path, "pippo.local")
    assert uno.returncode == 0, uno.stderr + uno.stdout
    assert (dev / ".env.dev").read_text() == prima, "fcn-up.sh ha scritto .env.dev"

    due = _su(dev, bin_, tmp_path)
    assert due.returncode == 0, due.stderr + due.stdout
    up_uno, up_due = _visto_da_up(tmp_path)
    assert "https://pippo.local:8443/" in up_uno, up_uno
    assert "OIDC_ISSUER=https://em.localhost:8443/" in up_due, up_due
    assert "REALM_FILE=./keycloak/realm-em-dev.json " in up_due, up_due
    assert "https://em.localhost:8443/em/v1/health" in due.stdout


@needs_bash
def test_FCN_HOST_SU_UN_NODO_QUALUNQUE_si_ignora_e_lo_dice(tmp_path):
    """La riga che resta nel `.env.dev` di chi ha usato la versione del 31
    ottobre: non comanda più, e lo script dice dove sta."""
    dev, bin_ = _banco(tmp_path)
    env = dev / ".env.dev"
    env.write_text(env.read_text() + "FCN_HOST=192.168.1.214\n")
    done = _su(dev, bin_, tmp_path)
    assert done.returncode == 0, done.stderr + done.stdout
    assert "FCN_HOST è il nome di un nodo da campo" in done.stdout, done.stdout
    (up,) = _visto_da_up(tmp_path)
    assert "https://em.localhost:8443/" in up and "192.168.1.214" not in up, up


@needs_bash
def test_IL_NODO_DA_CAMPO_tiene_il_suo_nome(tmp_path):
    """L'eccezione: `EM_NODE_KIND=field` + `FCN_HOST` (scritti da
    `fcn-field-setup.sh`) → una corsa senza argomenti usa quel nome. È il
    Raspberry che si riaccende da solo con `./fcn-up.sh --offline` (qui per
    la strada `--source`: quella delle immagini vuole un compose recente, e
    il nome del nodo non dipende dalla strada)."""
    dev, bin_ = _banco(tmp_path)
    env = dev / ".env.dev"
    env.write_text(env.read_text() + "EM_NODE_KIND=field\nFCN_HOST=scavo.local\n"
                   "DEV_CLIENT_SECRET=segreto-di-prova\n")
    (dev / "accredited.field.yaml").write_text("accredited: []\n")
    #: Keycloak «risponde» e l'accreditamento è finto: qui si misura il nome
    (dev / "accredit.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    curl = bin_ / "curl"
    curl.write_text(curl.read_text().replace(
        "case \"$*\" in\n", "case \"$*\" in\n  *auth/realms/em-dev*) exit 0 ;;\n", 1))
    done = _su(dev, bin_, tmp_path, "--offline", "--source")
    assert done.returncode == 0, done.stderr + done.stdout
    (up,) = _visto_da_up(tmp_path)
    assert "OIDC_ISSUER=https://scavo.local:8443/" in up, up
    assert "REALM_FILE=./keycloak/realm-em-dev.campo.json" in up, up
    assert "FCN_HOST è il nome di un nodo da campo" not in done.stdout
