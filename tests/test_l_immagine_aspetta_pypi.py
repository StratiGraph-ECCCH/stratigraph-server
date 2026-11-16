"""L'IMMAGINE ASPETTA PyPI (16 nov 2026).

`immagine.yml` partiva prima che la nuova s3dgraphy comparisse su PyPI e il
build falliva (dev112, dev113: rilanciati a mano). Ora, prima di costruire,
un passo chiede a pip la versione scelta e aspetta fino a 15 minuti, come già
fa `prove.yml`. Qui si guarda che il passo ci sia, che stia prima del build e
che finisca con un errore chiaro.
"""
from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "immagine.yml"


def _steps():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["immagine"]["steps"]


def _index(steps, pred):
    return next(i for i, s in enumerate(steps) if pred(s))


def test_il_passo_dell_attesa_sta_prima_del_build():
    steps = _steps()
    attesa = _index(steps, lambda s: s.get("name") == "La versione di s3Dgraphy è su PyPI")
    versione = _index(steps, lambda s: s.get("id") == "s3d")
    build = _index(steps, lambda s: str(s.get("uses", "")).startswith("docker/build-push-action"))
    assert versione < attesa < build


def test_l_attesa_e_di_15_minuti_e_finisce_con_un_errore():
    run = next(s for s in _steps() if s.get("name") == "La versione di s3Dgraphy è su PyPI")["run"]
    assert "steps.s3d.outputs.versione" in run
    assert "seq 1 30" in run and "sleep 30" in run
    assert "No matching distribution found for s3dgraphy" in run
    assert "::error::" in run and "15 minuti" in run
