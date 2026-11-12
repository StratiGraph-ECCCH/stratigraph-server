"""L'installatore che avvia Colima e poi dice di no (11 novembre 2026).

Misurato sulla corsa di E.D.: `./fcn-install.sh` avviava Colima, Colima partiva
(22 secondi, `docker info` rispondeva: 28.4.0, Ubuntu 24.04.2), e l'installatore
chiudeva con «✖ docker non risponde» rifiutando di proseguire. Il blocco era

    sg_ensure_docker || true
    male "docker non risponde (vedi sopra)."

cioè `male` fuori da ogni condizione: lo stato riportato era quello di PRIMA
del rimedio. Sottospecie A: il tentativo riportato come se fosse l'esito.

La prova non finge `sg_ensure_docker`: finge la MACCHINA — un Mac su cui
`docker info` risponde solo dopo `colima start` — e lascia girare il
`sg_ensure_docker` vero di `platform.sh`.
"""

from __future__ import annotations

import pathlib

from test_un_nodo_che_si_accende_altrove import (
    _chiamati, _clone_finto, _finti, _installa, _uname, needs_bash)


def _mac_con_colima_spento(tmp_path) -> pathlib.Path:
    bin_ = _finti(tmp_path, docker_ok=False, plugin=True, autonomo=False,
                  nomi=("git", "npm"))
    _uname(bin_, "macos")
    acceso = tmp_path / "colima-acceso"
    docker = bin_ / "docker"
    testo = docker.read_text()
    vecchio = 'if [ "${1:-}" = "info" ]; then\n  exit 1\nfi'
    assert vecchio in testo, "il docker finto ha cambiato forma"
    docker.write_text(testo.replace(
        vecchio, f'if [ "${{1:-}}" = "info" ]; then\n  [ -f "{acceso}" ] && exit 0; exit 1\nfi'))
    colima = bin_ / "colima"
    colima.write_text(colima.read_text().replace(
        "exit 0", f'[ "${{1:-}}" = "start" ] && touch "{acceso}"\nexit 0', 1))
    return bin_


@needs_bash
def test_COLIMA_PARTE_e_l_installatore_conta_ZERO_guai(tmp_path):
    dev = _clone_finto(tmp_path, fratelli=("stratigraph-chatbot", "stratigraph-catalog",
                                           "EMStudio"))
    bin_ = _mac_con_colima_spento(tmp_path)
    done = _installa(dev, bin_, tmp_path, args=("--source",))
    out = done.stdout + done.stderr
    assert "colima start" in _chiamati(tmp_path), "il rimedio non è stato tentato"
    assert "docker non risponde" not in out, out
    assert "cosa/e da sistemare" not in out, out
    assert "✔ docker risponde" in out, out
    assert done.returncode == 0, out


@needs_bash
def test_E_SE_COLIMA_NON_BASTA_il_guaio_si_conta(tmp_path):
    """L'altra metà: un rimedio che non riesce resta un guaio, e lo si dice."""
    dev = _clone_finto(tmp_path, fratelli=("stratigraph-chatbot", "stratigraph-catalog",
                                           "EMStudio"))
    bin_ = _finti(tmp_path, docker_ok=False, plugin=True, autonomo=False,
                  nomi=("git", "npm"))
    _uname(bin_, "macos")
    done = _installa(dev, bin_, tmp_path, args=("--source",))
    out = done.stdout + done.stderr
    assert "colima start" in _chiamati(tmp_path)
    assert "docker non risponde (vedi sopra)" in out, out
    assert "cosa/e da sistemare" in out, out
