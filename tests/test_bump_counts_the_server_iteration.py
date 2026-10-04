"""bump-s3dgraphy.sh counts one more iteration of the server when it moves the pin (W3).

Measured on 4 Oct 2026: `/v1/health` said `"version": "1.6.0.dev1"` while the
pin had gone from dev17 to dev35 — a number nobody moved, so it said nothing.
Now the script that moves the pin (run by `./em.sh release` at step 6, through
`./em.sh propagate --pins`) also moves the server's own `1.6.0.devN` to
`devN+1`, in `app/__init__.py` and pyproject.toml's `version`, once per commit.

Run on a COPY of the five files in a throwaway git repository: no `.venv`
there, so the script's own pytest guard is skipped, and nothing here is built.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FILES = ["bump-s3dgraphy.sh", "pyproject.toml", "Dockerfile",
         "dev-stack/docker-compose.dev.yml", "app/__init__.py"]

pytestmark = pytest.mark.skipif(not shutil.which("git") or not shutil.which("bash"),
                                reason="git and bash are needed")


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.org",
                           "-c", "commit.gpgsign=false", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def copy(tmp_path):
    for f in FILES:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / f, tmp_path / f)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "start")
    return tmp_path


def _bump(where, v):
    r = subprocess.run(["bash", "bump-s3dgraphy.sh", v], cwd=where, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _versions(where):
    own = re.search(r'(?m)^__version__ = "([^"]+)"', (where / "app/__init__.py").read_text()).group(1)
    meta = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (where / "pyproject.toml").read_text()).group(1)
    pin = re.search(r'"s3dgraphy\[[a-z,]*\]==([^"]+)"', (where / "pyproject.toml").read_text()).group(1)
    return own, meta, pin


def _next(v):
    head, n = v.rsplit(".dev", 1)
    return f"{head}.dev{int(n) + 1}"


def test_moving_the_pin_counts_one_iteration_in_both_places(copy):
    own, _, _ = _versions(copy)
    said = _bump(copy, "1.6.0.dev990")
    assert _versions(copy) == (_next(own), _next(own), "1.6.0.dev990")
    assert f"{own} → {_next(own)}" in said


def test_the_same_pin_again_counts_nothing(copy):
    _bump(copy, "1.6.0.dev990")
    after_first = _versions(copy)
    _bump(copy, "1.6.0.dev990")
    assert _versions(copy) == after_first


def test_once_per_commit(copy):
    own, _, _ = _versions(copy)
    _bump(copy, "1.6.0.dev990")
    _bump(copy, "1.6.0.dev991")                 # not committed yet: already counted
    assert _versions(copy) == (_next(own), _next(own), "1.6.0.dev991")
    _git(copy, "commit", "-q", "-am", "Pin")
    _bump(copy, "1.6.0.dev992")                 # a new commit, a new iteration
    assert _versions(copy)[:2] == (_next(_next(own)),) * 2


def test_a_new_language_starts_the_server_at_dev1(copy):
    _bump(copy, "1.7.0.dev1")
    assert _versions(copy) == ("1.7.0.dev1", "1.7.0.dev1", "1.7.0.dev1")
