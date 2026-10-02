"""bump-s3dgraphy.sh --build recreates the server WITH `--env-file .env.dev`.

Measured on 2 Oct 2026: `--build` ran `docker-compose -f docker-compose.dev.yml
up -d stratigraph-server` with no env file, the server was recreated without
MinIO's keys and crashed over and over. Now it says `--env-file .env.dev` on
both the build and the up, like `fcn-up.sh`, and without `.env.dev` it stops
before touching any container, with `fcn-up.sh`'s message.

The script runs for real, in a copy of the files it edits, against a FAKE
docker-compose on PATH that writes down its arguments.
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _fake(bin_dir: Path, name: str, body: str) -> None:
    exe = bin_dir / name
    exe.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def copy(tmp_path):
    work = tmp_path / "srv"
    (work / "dev-stack").mkdir(parents=True)
    for rel in ("bump-s3dgraphy.sh", "pyproject.toml", "Dockerfile",
                "dev-stack/docker-compose.dev.yml", "dev-stack/platform.sh"):
        shutil.copy2(ROOT / rel, work / rel)
    shutil.copy2(ROOT / "dev-stack/.env.dev.example", work / "dev-stack/.env.dev.example")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "compose.log"
    # `docker compose` is not there (the plugin probe fails): the standalone
    # binary is the one found, as on E.D.'s Mac
    _fake(bin_dir, "docker", "exit 1\n")
    _fake(bin_dir, "docker-compose", f'echo "$*" >> "{log}"\n')
    # a git that is not a repository here: the diff line falls back
    _fake(bin_dir, "git", "exit 1\n")
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"}
    return work, log, env


def _run(work, env):
    return subprocess.run(["bash", "bump-s3dgraphy.sh", "1.6.0.dev31", "--build"],
                          cwd=work, env=env, capture_output=True, text=True)


def test_build_and_up_both_say_the_env_file(copy):
    work, log, env = copy
    (work / "dev-stack/.env.dev").write_text("X=1\n", encoding="utf-8")
    r = _run(work, env)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert calls == [
        "--env-file .env.dev -f docker-compose.dev.yml build stratigraph-server",
        "--env-file .env.dev -f docker-compose.dev.yml up -d stratigraph-server",
    ], calls


def test_without_env_dev_it_stops_before_any_container(copy):
    work, log, env = copy
    r = _run(work, env)
    assert r.returncode == 1
    assert "Manca `dev-stack/.env.dev`" in r.stderr
    assert "cp .env.dev.example .env.dev" in r.stderr
    assert not log.exists(), log.read_text(encoding="utf-8")


def test_fcn_up_and_bump_share_one_message():
    up = (ROOT / "dev-stack/fcn-up.sh").read_text(encoding="utf-8")
    bump = (ROOT / "bump-s3dgraphy.sh").read_text(encoding="utf-8")
    assert "sg_need_env_dev || exit 1" in up
    assert "sg_need_env_dev || exit 1" in bump
    assert "Manca" not in up.split("sg_need_env_dev || exit 1")[0].split("4-zero")[-1]
