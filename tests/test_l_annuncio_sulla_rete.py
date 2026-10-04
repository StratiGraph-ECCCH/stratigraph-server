"""`fcn-up.sh <host>` annuncia il nodo sulla rete locale (`_stratigraph._tcp`),
`fcn-down.sh` smette — provato con comandi finti, senza stack.

Misurato il 4 ottobre 2026: il Pi pubblicava con avahi il NOME `fcn.local`, non
un servizio, e il cercatore di s3Dgraphy (`tools/node_finder.browse_lan`) non
trovava niente. Il nodo personale si annunciava già (`dns-sd -R`); lo stack no.

Ciò che il cercatore deve poter ricostruire è `https://<host>:8443/em`: la porta
di Caddy parla https e l'API sta sotto `/em`. Il TXT lo dice
(`path=/em scheme=https`), e `node_finder.url_of` (s3dgraphy ≥ 1.6.0.dev36) lo
legge. Misurato su questo Mac lo stesso giorno: `dns-sd -L` di un annuncio così
risponde `can be reached at MacBook-Pro-di-Emanuel.local.:8443` e, sulla riga
dopo, ` path=/em scheme=https`.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import time

import pytest

from test_un_nodo_che_si_accende_altrove import (
    DEV, _chiamati, _clone_finto, _finti, _uname, needs_bash)


def _bin(tmp_path, *strumenti, dorme=False) -> pathlib.Path:
    """Una cartella con SOLO gli strumenti nominati (più quelli di base che le
    funzioni usano): `dns-sd` vero sta in `/usr/bin` su questo Mac, quindi per
    provare «c'è solo avahi» o «non c'è niente» il PATH non può contenerlo."""
    bin_ = tmp_path / "solo"
    bin_.mkdir(exist_ok=True)
    log = tmp_path / "chiamati.txt"
    for nome in strumenti:
        corpo = f'echo "{nome} $*" >> "{log}"\n' + ("exec sleep 30\n" if dorme else "")
        (bin_ / nome).write_text("#!/bin/bash\n" + corpo)
        (bin_ / nome).chmod(0o755)
    for base in ("nohup", "sleep", "cat", "rm", "mkdir", "dirname", "sed"):
        vero = shutil.which(base)
        if vero and not (bin_ / base).exists():
            (bin_ / base).symlink_to(vero)
    return bin_


def _sh(bin_, tmp_path, codice: str):
    env = {"PATH": str(bin_), "HOME": str(tmp_path)}
    return subprocess.run(["/bin/bash", "-c", f'. "{DEV}/platform.sh"; {codice}'],
                          capture_output=True, text=True, env=env)


@needs_bash
def test_IL_COMANDO_su_macos_e_dns_sd_R_col_TXT_che_il_cercatore_legge(tmp_path):
    done = _sh(_bin(tmp_path, "dns-sd", "avahi-publish"), tmp_path,
               'sg_announce_cmd "StratiGraph (fcn)" 8443 /em https')
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [
        "dns-sd", "-R", "StratiGraph (fcn)", "_stratigraph._tcp", "local.", "8443",
        "path=/em", "scheme=https"]


@needs_bash
def test_IL_COMANDO_su_linux_e_avahi_publish_s(tmp_path):
    done = _sh(_bin(tmp_path, "avahi-publish"), tmp_path,
               'sg_announce_cmd "StratiGraph (fcn)" 8443 /em https')
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [
        "avahi-publish", "-s", "StratiGraph (fcn)", "_stratigraph._tcp", "8443",
        "path=/em", "scheme=https"]


@needs_bash
def test_SENZA_NESSUNO_DEI_DUE_lo_dice_e_non_fallisce(tmp_path):
    bin_ = _bin(tmp_path)
    assert _sh(bin_, tmp_path, "sg_announce_cmd x 1 / https").returncode == 1
    done = _sh(bin_, tmp_path, 'sg_announce_start "StratiGraph (x)" 8443 /em https')
    assert done.returncode == 0, done.stderr
    assert "né dns-sd né" in done.stdout
    assert not (tmp_path / ".cache/stratigraph/fcn-announce.pid").exists()


@needs_bash
def test_ACCESO_IN_BACKGROUND_e_FERMATO(tmp_path):
    bin_ = _bin(tmp_path, "dns-sd", dorme=True)
    done = _sh(bin_, tmp_path, 'sg_announce_start "StratiGraph (fcn)" 8443 /em https')
    assert done.returncode == 0, done.stderr
    pf = tmp_path / ".cache/stratigraph/fcn-announce.pid"
    pid = int(pf.read_text())
    os.kill(pid, 0)                                   # vivo, dopo che la shell è uscita
    assert "annunciato sulla rete locale" in done.stdout
    fermo = _sh(bin_, tmp_path, "sg_announce_stop")
    assert "fermato" in fermo.stdout and not pf.exists()
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"l'annuncio (pid {pid}) è ancora vivo")


@needs_bash
def test_FCN_DOWN_ferma_l_annuncio(tmp_path):
    bin_ = _finti(tmp_path, docker_ok=True, plugin=True, autonomo=False)
    _uname(bin_, "linux")
    vivo = subprocess.Popen(["sleep", "30"])
    pf = tmp_path / ".cache/stratigraph/fcn-announce.pid"
    pf.parent.mkdir(parents=True)
    pf.write_text(str(vivo.pid))
    try:
        done = subprocess.run(["bash", str(DEV / "fcn-down.sh"), "--stop"],
                              capture_output=True, text=True, cwd=str(DEV),
                              env={**os.environ, "HOME": str(tmp_path),
                                   "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}"})
        assert done.returncode == 0, done.stderr + done.stdout
        assert vivo.wait(timeout=5) is not None
        assert not pf.exists()
    finally:
        if vivo.poll() is None:
            vivo.kill()


def _fcn_up(tmp_path, *args):
    dev = _clone_finto(tmp_path, fratelli=("stratigraph-chatbot", "stratigraph-catalog"))
    shutil.copy(DEV / ".env.dev.example", dev / ".env.dev")
    bin_ = _finti(tmp_path, docker_ok=True, plugin=True, autonomo=False)
    _uname(bin_, "linux")
    return subprocess.run(["bash", str(dev / "fcn-up.sh"), *args],
                          capture_output=True, text=True, cwd=str(dev),
                          env={**os.environ, "HOME": str(tmp_path),
                               "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}"})


@needs_bash
def test_FCN_UP_CON_UN_HOST_si_annuncia_dopo_up(tmp_path):
    done = _fcn_up(tmp_path, "fcn.local")
    assert done.returncode == 0, done.stderr + done.stdout
    chiamati = _chiamati(tmp_path)
    riga = "dns-sd -R StratiGraph (finta-macchina) _stratigraph._tcp local. 8443 path=/em scheme=https"
    for _ in range(50):                    # in background: può arrivare un istante dopo
        if riga in chiamati:
            break
        time.sleep(0.05)
        chiamati = _chiamati(tmp_path)
    assert riga in chiamati, chiamati
    assert chiamati.index("up -d --build") < chiamati.index("dns-sd -R")


@needs_bash
def test_FCN_UP_SENZA_HOST_non_si_annuncia(tmp_path):
    done = _fcn_up(tmp_path)
    assert done.returncode == 0, done.stderr + done.stdout
    time.sleep(0.3)
    assert "dns-sd" not in _chiamati(tmp_path)
    assert "avahi-publish" not in _chiamati(tmp_path)
