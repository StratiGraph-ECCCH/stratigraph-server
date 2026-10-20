"""EMStudio è il quarto fratello: l'installer lo prepara, `fcn-up` lo accende.

════════════════════════════════════════════════════════════════════════════════
## IL PROBLEMA, MISURATO IL 20 OTTOBRE 2026

`Caddyfile.dev` instrada `/em/studio/*` e `/em/read/*` al dev server Vite di
EMStudio sull'host (`host.docker.internal:5173`), e il catalogo monta
`../../EMStudio/frontend/dist` per il reader della narrativa. EMStudio era già
una dipendenza della stack, ma nessuno script lo sapeva: `fcn-install.sh` non
ne garantiva il checkout e `fcn-up.sh` non accendeva il suo dev server, quindi
`/em/studio/` restava un 502 finché qualcuno non apriva un quarto terminale.

## LA DECISIONE

Il dev server resta SULL'HOST — è supervisione, non containerizzazione. Le
prove qui sotto usano comandi finti (`git`, `npm`, `curl`, `docker`) e girano
senza rete, senza stack e senza toccare il Vite di chi le lancia: la fixture
`_nessun_emstudio_vero` del conftest sposta pid file e checkout in `tmp_path`,
e ogni prova che vuole un EMStudio se lo costruisce.
"""

from __future__ import annotations

import os
import pathlib
import signal
import time

from test_un_nodo_che_si_accende_altrove import (
    COMPOSE_YML, PATH_MINIMO, _chiamati, _clone_finto, _finti, _fratelli_dal_compose,
    _installa, _run, _uname, needs_bash)


def _scrivi(bin_: pathlib.Path, nome: str, corpo: str) -> None:
    f = bin_ / nome
    f.write_text("#!/usr/bin/env bash\n" + corpo)
    f.chmod(0o755)


def _npm_finto(bin_: pathlib.Path, tmp_path) -> None:
    """`npm install` crea node_modules, `build:reader` crea dist, `run dev`
    dichiara la 5173 aperta e DORME — cioè resta vivo come un Vite vero."""
    _scrivi(bin_, "npm",
            f'echo "npm $* @ $PWD" >> "{tmp_path}/chiamati.txt"\n'
            'case "$*" in\n'
            '  install) mkdir -p node_modules ;;\n'
            '  "run build:reader") mkdir -p dist ;;\n'
            f'  "run dev") touch "{tmp_path}/vite-su"; exec sleep 60 ;;\n'
            'esac\n'
            'exit 0\n')


def _curl_finto(bin_: pathlib.Path, tmp_path) -> None:
    """La 5173 risponde solo se il finto `npm run dev` l'ha aperta; ogni altro
    indirizzo non risponde (il nodo è finto)."""
    _scrivi(bin_, "curl",
            f'echo "curl $*" >> "{tmp_path}/chiamati.txt"\n'
            'case "$*" in\n'
            f'  *:5173*) [ -f "{tmp_path}/vite-su" ] && exit 0; exit 7 ;;\n'
            'esac\n'
            'exit 7\n')


def _emstudio_finto(tmp_path, *, node_modules=True, dist=True) -> pathlib.Path:
    ems = tmp_path / "EMStudio"
    fe = ems / "frontend"
    fe.mkdir(parents=True)
    (fe / "package.json").write_text("{}\n")
    if node_modules:
        (fe / "node_modules").mkdir()
    if dist:
        (fe / "dist").mkdir()
    return ems


# ═══ 1 · L'INSTALLER ════════════════════════════════════════════════════════

def test_EMSTUDIO_STA_IN_X_SIBLING_REPOS():
    """Senza `context:`, l'unico posto da cui l'installer sa l'indirizzo."""
    assert _fratelli_dal_compose(COMPOSE_YML).get("EMStudio") == \
        "https://github.com/ExtendedMatrix/EMStudio.git"


@needs_bash
def test_INSTALLER_CLONA_EMSTUDIO_che_manca(tmp_path):
    dev = _clone_finto(tmp_path,
                       fratelli=("stratigraph-chatbot", "stratigraph-catalog"))
    bin_ = _finti(tmp_path, docker_ok=True, plugin=False, autonomo=True,
                  nomi=("git",))
    _uname(bin_, "linux")
    _scrivi(bin_, "git",
            f'echo "git $*" >> "{tmp_path}/chiamati.txt"\n'
            'if [ "${1:-}" = "clone" ]; then mkdir -p "${!#}"; fi\n'
            'exit 0\n')
    done = _installa(dev, bin_, tmp_path)
    chiamati = _chiamati(tmp_path)
    url = _fratelli_dal_compose(dev / "docker-compose.dev.yml")["EMStudio"]
    assert f"git clone --depth 1 {url} {tmp_path}/albero/EMStudio" in chiamati, (
        chiamati + done.stdout + done.stderr)
    assert "EMStudio clonato" in done.stdout, done.stdout


@needs_bash
def test_DRY_RUN_nomina_EMSTUDIO_e_non_fa_niente(tmp_path):
    dev = _clone_finto(tmp_path,
                       fratelli=("stratigraph-chatbot", "stratigraph-catalog"))
    bin_ = _finti(tmp_path, docker_ok=True, plugin=False, autonomo=True,
                  nomi=("git",))
    _uname(bin_, "linux")
    _npm_finto(bin_, tmp_path)
    done = _installa(dev, bin_, tmp_path, args=("--dry-run",))
    assert "clonerei EMStudio da https://github.com/ExtendedMatrix/EMStudio.git" \
        in done.stdout, done.stdout
    chiamati = _chiamati(tmp_path)
    assert "git clone" not in chiamati and "npm " not in chiamati, chiamati


@needs_bash
def test_INSTALLER_FA_NPM_INSTALL_e_BUILD_READER_in_quest_ordine(tmp_path):
    dev = _clone_finto(tmp_path,
                       fratelli=("stratigraph-chatbot", "stratigraph-catalog"))
    fe = tmp_path / "albero" / "EMStudio" / "frontend"
    fe.mkdir(parents=True)
    (fe / "package.json").write_text("{}\n")
    bin_ = _finti(tmp_path, docker_ok=True, plugin=False, autonomo=True,
                  nomi=("git",))
    _uname(bin_, "linux")
    _npm_finto(bin_, tmp_path)
    done = _installa(dev, bin_, tmp_path)
    chiamati = _chiamati(tmp_path)
    assert f"npm install @ {fe}" in chiamati, chiamati + done.stderr
    assert f"npm run build:reader @ {fe}" in chiamati, chiamati
    assert chiamati.index("npm install") < chiamati.index("npm run build:reader")
    assert "501" in done.stdout, "non dice perché serve la dist"
    #: …e al secondo giro non rifà niente
    (tmp_path / "chiamati.txt").unlink()
    _installa(dev, bin_, tmp_path)
    assert "npm " not in _chiamati(tmp_path)


@needs_bash
def test_SENZA_NPM_lo_dice_e_non_lo_installa(tmp_path):
    """La dottrina di Docker: una sorgente di pacchetti non la aggiungo io.
    PATH ridotto ai finti e a quello di sistema, dove npm non c'è."""
    dev = _clone_finto(tmp_path,
                       fratelli=("stratigraph-chatbot", "stratigraph-catalog"))
    fe = tmp_path / "albero" / "EMStudio" / "frontend"
    fe.mkdir(parents=True)
    (fe / "package.json").write_text("{}\n")
    bin_ = _finti(tmp_path, docker_ok=True, plugin=False, autonomo=True,
                  nomi=("git",))
    _uname(bin_, "linux")
    #: `docker-compose config` passa al compose VERO per percorso assoluto,
    #: quindi PATH può restare minimo
    done = _installa(dev, bin_, tmp_path,
                     extra_env={"PATH": f"{bin_}{os.pathsep}"
                                        f"{os.pathsep.join(PATH_MINIMO)}"})
    assert "npm non c'è" in done.stderr, done.stderr
    assert "Non lo installo" in done.stderr
    #: …e non è un guaio: il resto della stack sale lo stesso
    assert done.returncode == 0, done.stdout + done.stderr
    chiamati = _chiamati(tmp_path)
    for vietato in ("brew", "apt", "npm "):
        assert vietato not in chiamati, chiamati


# ═══ 2 · fcn-up / fcn-down ══════════════════════════════════════════════════

@needs_bash
def test_STUDIO_PRETESO_SENZA_CHECKOUT_si_ferma_prima_di_up(tmp_path):
    bin_ = _finti(tmp_path, docker_ok=True, plugin=True, autonomo=False)
    _uname(bin_, "linux")
    done = _run("fcn-up.sh", bin_, tmp_path, args=("--studio",))
    assert done.returncode != 0, done.stdout
    assert "--studio" in done.stderr and "./fcn-install.sh" in done.stderr
    assert "up -d" not in _chiamati(tmp_path)


@needs_bash
def test_SENZA_CHECKOUT_tace(tmp_path):
    """Il default: un nodo di campo non ha EMStudio, e non è rotto."""
    bin_ = _finti(tmp_path, docker_ok=True, plugin=True, autonomo=False)
    _uname(bin_, "linux")
    done = _run("fcn-up.sh", bin_, tmp_path)
    assert done.returncode == 0, done.stderr
    assert "EMStudio" not in done.stdout + done.stderr
    assert "npm" not in _chiamati(tmp_path)


@needs_bash
def test_NO_STUDIO_non_lo_accende(tmp_path):
    ems = _emstudio_finto(tmp_path)
    bin_ = _finti(tmp_path, docker_ok=True, plugin=True, autonomo=False)
    _uname(bin_, "linux")
    _npm_finto(bin_, tmp_path)
    _curl_finto(bin_, tmp_path)
    done = _run("fcn-up.sh", bin_, tmp_path, args=("--no-studio",),
                extra_env={"SG_STUDIO_DIR": str(ems)})
    assert done.returncode == 0, done.stderr
    assert "npm run dev" not in _chiamati(tmp_path)
    assert "/em/studio/" not in done.stdout
