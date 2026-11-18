"""The node inside OpenShift: the list of obligatory variables is COMPLETE.

Three things, each one a way the list could lie:

1. **each obligatory variable, missing alone, stops the node and is named** —
   so no value on the list is decorative;
2. **a complete environment starts it** — so the list asks for nothing more;
3. **every variable the code reads is classified** in
   `deploy/openshift/README.md` — so a variable added tomorrow, obligatory or
   not, turns this file red until somebody decides which of the three it is.

Plus the two halves of the manifest that carry the list: the base ConfigMap and
Secret name every obligatory key, and `python -m app.preflight` really exits
non-zero with the name on stderr (the init container's whole contract).
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

from app import preflight

REPO = pathlib.Path(__file__).resolve().parent.parent
README = REPO / "deploy" / "openshift" / "README.md"
BASE = REPO / "deploy" / "openshift" / "base"

#: Written here AND in the README's «Obligatory» table, on purpose: the test
#: below requires the two to agree, so neither can lose a line silently.
OBLIGATORY = (
    "EM_NODE_KIND",
    "EM_PUBLIC_BASE",
    "OIDC_ISSUER",
    "OIDC_AUDIENCE",
    "EM_SNAPSHOT_DIR",
    "EM_ASSET_S3_ENDPOINT",
    "EM_ASSET_S3_BUCKET",
    "EM_ASSET_S3_ACCESS_KEY",
    "EM_ASSET_S3_SECRET_KEY",
)
SECRET_OBLIGATORY = {"EM_ASSET_S3_ACCESS_KEY", "EM_ASSET_S3_SECRET_KEY"}


def complete(tmp_path: pathlib.Path) -> dict:
    return {
        "EM_NODE_KIND": "institutional",
        "EM_PUBLIC_BASE": "https://em.example.org/em",
        "OIDC_ISSUER": "https://login.example.org/realms/em",
        "OIDC_AUDIENCE": "em-server",
        "EM_SNAPSHOT_DIR": str(tmp_path / "snapshots"),
        "EM_ASSET_S3_ENDPOINT": "https://s3.example.org",
        "EM_ASSET_S3_BUCKET": "em-assets",
        "EM_ASSET_S3_ACCESS_KEY": "access",
        "EM_ASSET_S3_SECRET_KEY": "secret",
    }


def _section(title: str) -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index(f"### {title}\n")
    end = text.find("\n### ", start + 1)
    return text[start:end if end != -1 else None]


def test_a_complete_environment_has_no_problem(tmp_path):
    assert preflight.problems(complete(tmp_path)) == []


@pytest.mark.parametrize("name", OBLIGATORY)
def test_each_obligatory_variable_missing_alone_is_refused_by_name(tmp_path, name):
    env = complete(tmp_path)
    del env[name]
    found = preflight.problems(env)
    assert found, f"{name} missing and the preflight said nothing"
    assert any(name in line for line in found), (name, found)


@pytest.mark.parametrize("name", OBLIGATORY)
def test_empty_is_the_same_as_missing(tmp_path, name):
    """The ConfigMap ships the obligatory keys EMPTY: that must refuse too."""
    env = complete(tmp_path)
    env[name] = ""
    assert any(name in line for line in preflight.problems(env))


def test_an_empty_environment_names_every_obligatory_variable():
    said = "\n".join(preflight.problems({}))
    for name in ("EM_NODE_KIND", "EM_PUBLIC_BASE", "OIDC_ISSUER", "OIDC_AUDIENCE",
                 "EM_SNAPSHOT_DIR", "EM_ASSET_S3_ENDPOINT"):
        assert name in said, name


def test_the_alternative_spellings_the_code_accepts_are_accepted(tmp_path):
    env = complete(tmp_path)
    issuer = env.pop("OIDC_ISSUER")
    env["TOKEN_ENDPOINT"] = issuer + "/protocol/openid-connect/token"
    env["CLIENT_ID_em"] = env.pop("OIDC_AUDIENCE")
    for key in ("EM_ASSET_S3_ENDPOINT", "EM_ASSET_S3_BUCKET",
                "EM_ASSET_S3_ACCESS_KEY", "EM_ASSET_S3_SECRET_KEY"):
        del env[key]
    env["EM_ASSET_DIR"] = str(tmp_path / "assets")
    assert preflight.problems(env) == []


def test_plain_http_public_base_is_refused(tmp_path):
    env = complete(tmp_path)
    env["EM_PUBLIC_BASE"] = "http://em.example.org/em"
    assert any("https://" in line for line in preflight.problems(env))


def test_half_a_database_is_refused_and_none_is_fine(tmp_path):
    env = complete(tmp_path)
    env["EM_DOCUMENTS_HOST"] = "postgres"
    assert any("EM_DOCUMENTS_DB" in line for line in preflight.problems(env))
    env.update(EM_DOCUMENTS_DB="d", EM_DOCUMENTS_USER="u", EM_DOCUMENTS_PASSWORD="p")
    assert preflight.problems(env) == []


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root writes through any permission")
def test_an_unwritable_snapshot_dir_is_refused(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        env = complete(tmp_path)
        env["EM_SNAPSHOT_DIR"] = str(locked / "snapshots")
        assert any("not writable" in line for line in preflight.problems(env))
    finally:
        locked.chmod(0o700)


def _run(env: dict) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items()
            if not k.startswith(("EM_", "OIDC_", "TOKEN_ENDPOINT", "CLIENT_ID_"))}
    base["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    return subprocess.run([sys.executable, "-m", "app.preflight"], cwd=REPO,
                          env={**base, **env}, capture_output=True, text=True,
                          timeout=120)


def test_the_init_container_contract_exit_2_and_the_name_on_stderr(tmp_path):
    env = complete(tmp_path)
    # a directory instead of S3, so the run touches no network
    for key in ("EM_ASSET_S3_ENDPOINT", "EM_ASSET_S3_BUCKET",
                "EM_ASSET_S3_ACCESS_KEY", "EM_ASSET_S3_SECRET_KEY"):
        del env[key]
    env["EM_ASSET_DIR"] = str(tmp_path / "assets")
    ok = _run(env)
    assert ok.returncode == 0, ok.stderr
    del env["OIDC_AUDIENCE"]
    refused = _run(env)
    assert refused.returncode == 2
    assert "OIDC_AUDIENCE" in refused.stderr


def test_the_readme_lists_exactly_these_as_obligatory():
    table = _section("Obligatory")
    rows = re.findall(r"^\| `([A-Z_a-z0-9]+)` \|", table, flags=re.M)
    assert tuple(rows) == OBLIGATORY


def test_the_base_manifests_carry_every_obligatory_key():
    config = (BASE / "configmap.yaml").read_text(encoding="utf-8")
    secret = (BASE / "secret.yaml").read_text(encoding="utf-8")
    for name in OBLIGATORY:
        where = secret if name in SECRET_OBLIGATORY else config
        assert re.search(rf"^\s+{name}:", where, flags=re.M), name


#: what the code reads, found the way the README says it was: every quoted
#: name with one of these prefixes in `app/`
_READ = re.compile(r"""["']((?:EM|OIDC|NODEODM|OPS|TOKEN|CLIENT)_[A-Za-z0-9_]*)["']""")


def test_every_variable_the_code_reads_is_classified_in_the_readme():
    names = set()
    for path in (REPO / "app").rglob("*.py"):
        if "vendor" in path.parts:
            continue
        names.update(_READ.findall(path.read_text(encoding="utf-8")))
    # the prefixes catch two strings that are not variables at all
    names -= {"EM_"}
    readme = README.read_text(encoding="utf-8")
    missing = sorted(n for n in names if f"`{n}`" not in readme)
    assert not missing, ("read by the code, classified nowhere in "
                         f"deploy/openshift/README.md: {missing}")
