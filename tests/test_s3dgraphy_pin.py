"""One s3dgraphy version for this server, written once and copied twice.

MICRO-CATENA-DATAMODEL (30 September) measured three versions declared by this
one repository, none agreeing:

    pyproject.toml                  ==1.6.0.dev12   (dependency and the extras)
    Dockerfile                      no default      (the "one place" it named,
                                                     `dev-stack/.env.dev`, is
                                                     gitignored and never had it)
    dev-stack/docker-compose.dev.yml  dev17         (the anchor the stack builds with)

So the test suite ran one library, the image another, and the extras a third.

The place written BY HAND is now `pyproject.toml`'s dependency line. The other
two are copies — the Dockerfile has to build without the stack, and the compose
anchor feeds the chatbot and the catalogue, which build from their own
repositories — and `bump-s3dgraphy.sh` writes all three in one go. This file is
what makes the copies copies: the day one of them is edited alone, the suite is
red, which is a much shorter bug than a study indexed by one vocabulary and
written by another.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


def _pyproject_pins() -> list[str]:
    """Every `s3dgraphy[...]==X` in pyproject.toml — the dependency AND the extras."""
    text = (REPO / "pyproject.toml").read_text()
    return re.findall(r'"s3dgraphy(?:\[[a-z,]*\])?==([^"]+)"', text)


def _dockerfile_default() -> str | None:
    found = re.search(r"(?m)^ARG S3DGRAPHY_VERSION=(\S+)\s*$",
                      (REPO / "Dockerfile").read_text())
    return found.group(1) if found else None


def _compose_anchors() -> dict[str, str]:
    """`x-s3dgraphy-version` in every compose file of the dev stack that has one."""
    out = {}
    for path in sorted((REPO / "dev-stack").glob("docker-compose*.yml")):
        for m in re.finditer(r'(?m)^x-s3dgraphy-version:.*?:-([^}"]+)\}',
                             path.read_text()):
            out[path.name] = m.group(1)
    return out


def the_pin() -> str:
    pins = _pyproject_pins()
    assert pins, "pyproject.toml pins no s3dgraphy at all"
    return pins[0]


def test_pyproject_says_one_version_everywhere_it_says_one():
    """The dependency and the three extras: four spellings in one file."""
    pins = _pyproject_pins()
    assert len(pins) == 4, f"expected the dependency + rdf/geo/all, found {pins}"
    assert len(set(pins)) == 1, f"pyproject.toml disagrees with itself: {pins}"


def test_the_dockerfile_default_is_the_pin():
    default = _dockerfile_default()
    assert default is not None, (
        "the Dockerfile has no `ARG S3DGRAPHY_VERSION=<v>` default: a bare "
        "`docker build .` would refuse, and the version would live wherever the "
        "caller remembered to type it")
    assert default == the_pin(), (
        f"Dockerfile builds {default}, pyproject.toml pins {the_pin()}. "
        f"Run ./bump-s3dgraphy.sh {the_pin()} instead of editing one of them.")


def test_the_compose_anchor_is_the_pin():
    anchors = _compose_anchors()
    assert "docker-compose.dev.yml" in anchors, \
        "the dev stack lost its `x-s3dgraphy-version` anchor"
    wrong = {f: v for f, v in anchors.items() if v != the_pin()}
    assert not wrong, (
        f"the dev stack builds {wrong}, pyproject.toml pins {the_pin()}. "
        f"Run ./bump-s3dgraphy.sh {the_pin()}.")


def test_no_compose_service_spells_the_version_by_hand():
    """The anchor is the only place a compose file may carry the number: a
    service that writes `S3DGRAPHY_VERSION: 1.6.0.devN` beside it is the fourth
    spelling this file exists to prevent."""
    for path in sorted((REPO / "dev-stack").glob("docker-compose*.yml")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"S3DGRAPHY_VERSION\s*[:=]\s*[\"']?\d", line):
                pytest.fail(f"{path.name}:{n} spells the version by hand: {line.strip()}")


def test_what_is_installed_answers_with_the_pin_or_says_it_is_a_checkout():
    """`/licenses/s3dgraphy-version` in the image is pip's answer; here the
    same question is asked of the environment the suite runs in.

    A developer venv runs the sibling CHECKOUT on purpose (README «Run it»), so
    a mismatch there is not a failure — it is a different, declared setup. What
    must hold either way is that `datamodel_fingerprint()` answers from what is
    installed, which is the point of dev25."""
    import importlib.metadata as md

    import s3dgraphy
    from s3dgraphy import api

    installed = md.version("s3dgraphy")
    is_checkout = "site-packages" not in str(pathlib.Path(s3dgraphy.__file__))
    if not is_checkout:
        assert installed == the_pin(), (
            f"the environment installed s3dgraphy {installed}, the pin is "
            f"{the_pin()}: reinstall with `pip install -e '.[dev]'`")
    fp = api.datamodel_fingerprint()
    assert fp["digest"].startswith("sha256:")
    assert set(fp["versions"]) >= {"nodes", "connections"}
