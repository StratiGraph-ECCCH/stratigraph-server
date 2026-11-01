"""LA STRADA DELLE IMMAGINI — nessun build, nessun codice montato (1 nov 2026).

`dev-stack/docker-compose.images.yml` sopra `docker-compose.dev.yml` deve dare
un nodo che si accende SOLO dalle immagini pubblicate: nessun servizio con
`build:`, nessun mount `../`, i volumi di DATI tutti al loro posto, e ogni
immagine nostra a un tag esplicito di GHCR che non sia `latest`.

Le prove sono due, perché sono due le cose che possono sbagliare:

* la FUSIONE, rifatta qui in Python con le regole di Compose per `!reset` e
  `!override` — gira ovunque, anche senza Docker;
* il compose VERO, `config` e basta (legge i file, non parla col demone, non
  tocca la pila accesa), dove c'è un Compose che conosce `!override`. È lui
  che conta: la fusione in Python è il modello, questa è la misura.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV = ROOT / "dev-stack"
BASE = DEV / "docker-compose.dev.yml"
IMAGES = DEV / "docker-compose.images.yml"
FIELD = DEV / "docker-compose.field.yml"

#: i nostri tre servizi, e il nome con cui ciascuno è pubblicato
NOSTRI = {
    "stratigraph-server": "stratigraph-server",
    "stratigraph-chatbot": "stratigraph-stratifield",
    "stratigraph-catalog": "stratigraph-catalog",
}


class _Reset:
    pass


class _Override(list):
    pass


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!reset", lambda loader, node: _Reset())
_Loader.add_constructor(
    "!override", lambda loader, node: _Override(loader.construct_sequence(node)))


def _load(path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)


def _target(entry: str) -> str:
    parts = entry.split(":")
    return parts[1] if len(parts) > 1 else parts[0]


def _merge_service(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, _Reset):
            out.pop(key, None)
        elif isinstance(value, _Override):
            out[key] = list(value)
        elif key == "volumes":
            #: Compose fonde i volumi per PERCORSO NEL CONTAINER
            merged = {_target(v): v for v in out.get(key, [])}
            merged.update({_target(v): v for v in value})
            out[key] = list(merged.values())
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **value}
        else:
            out[key] = value
    return out


def _merged(*paths):
    services: dict = {}
    for path in paths:
        for name, svc in (_load(path).get("services") or {}).items():
            services[name] = _merge_service(services.get(name, {}), svc or {})
    return services


def test_ogni_servizio_che_si_costruisce_ha_la_sua_immagine():
    base = _load(BASE)["services"]
    over = _load(IMAGES)["services"]
    costruiti = {n for n, s in base.items() if "build" in s}
    assert costruiti == set(NOSTRI), (
        "un servizio nuovo con `build:` nel compose di base: la strada delle "
        f"immagini deve conoscerlo ({sorted(costruiti - set(NOSTRI))})")
    for name in costruiti:
        assert isinstance(over[name].get("build"), _Reset), f"{name}: manca `build: !reset null`"
        assert isinstance(over[name].get("volumes"), _Override), (
            f"{name}: `volumes:` senza `!override` si FONDE, e i mount ../ restano")


@pytest.mark.parametrize("service", sorted(NOSTRI))
def test_il_tag_e_esplicito_e_non_e_latest(service):
    image = _load(IMAGES)["services"][service]["image"]
    m = re.fullmatch(r"ghcr\.io/stratigraph-eccch/([a-z0-9-]+):([0-9A-Za-z.\-]+)", image)
    assert m, f"{service}: «{image}» non è ghcr.io/stratigraph-eccch/<nome>:<tag>"
    assert m.group(1) == NOSTRI[service]
    assert m.group(2) != "latest"
    assert "$" not in image, "il tag sta in UN posto: niente variabili che lo spostino"


@pytest.mark.parametrize("files", [
    (BASE, IMAGES),
    (BASE, IMAGES, FIELD),
], ids=["immagini", "immagini+campo"])
def test_nessun_build_e_nessun_mount_di_codice(files):
    for name, svc in _merged(*files).items():
        assert "build" not in svc, f"{name} si costruisce ancora"
        for v in svc.get("volumes", []):
            assert not str(v).startswith("../"), f"{name} monta ancora {v}"


def test_i_volumi_di_dati_restano():
    """`!override` toglie il codice, NON i dati: ogni volume nominato che il
    compose di base monta su uno dei nostri servizi c'è ancora, allo stesso
    percorso."""
    base = _load(BASE)
    named = set((base.get("volumes") or {}).keys())
    over = _merged(BASE, IMAGES)
    for name in NOSTRI:
        prima = [v for v in base["services"][name].get("volumes", [])
                 if v.split(":")[0] in named]
        dopo = over[name].get("volumes", [])
        assert prima, f"{name}: nessun volume di dati nel compose di base?"
        for v in prima:
            assert v in dopo, f"{name}: il volume di dati {v} è sparito"


def test_il_campo_porta_ancora_la_sua_lista():
    svc = _merged(BASE, IMAGES, FIELD)["stratigraph-server"]
    assert "./accredited.field.yaml:/srv/em-node/accredited.yaml:ro" in svc["volumes"]
    assert "./accredited.yaml:/srv/em-node/accredited.yaml:ro" not in svc["volumes"]


def test_gli_script_controllano_la_versione_di_compose():
    platform = (DEV / "platform.sh").read_text(encoding="utf-8")
    assert 'SG_COMPOSE_MIN_IMAGES="2.24.4"' in platform
    for script in ("fcn-up.sh", "fcn-install.sh", "fcn-down.sh"):
        text = (DEV / script).read_text(encoding="utf-8")
        assert "sg_compose_supports_images" in text, script
        assert "docker-compose.images.yml" in text, script


def _bash(snippet, **env):
    return subprocess.run(["bash", "-c", f'cd "{DEV}" && . ./platform.sh && {snippet}'],
                          capture_output=True, text=True,
                          env={**os.environ, "EM_NODE_ROAD": "", "EM_NODE_KIND": "",
                               **env})


@pytest.mark.parametrize("a,b,ok", [
    ("2.24.4", "2.24.4", True), ("2.29.1", "2.24.4", True), ("5.3.0", "2.24.4", True),
    ("2.24.3", "2.24.4", False), ("2.9.0", "2.24.4", False), ("1.29.2", "2.24.4", False),
])
def test_il_confronto_delle_versioni(a, b, ok):
    assert (_bash(f"sg_version_at_least {a} {b}").returncode == 0) is ok


@pytest.mark.parametrize("arg,env,attesa", [
    ("", {"EM_NODE_KIND": "field"}, "images"),
    ("", {"EM_NODE_KIND": "institutional"}, "source"),
    ("source", {"EM_NODE_KIND": "field"}, "source"),
    ("", {"EM_NODE_KIND": "field", "EM_NODE_ROAD": "source"}, "source"),
    ("images", {}, "images"),
])
def test_chi_sceglie_la_strada(arg, env, attesa, tmp_path):
    # da una copia di dev-stack senza .env.dev: decide solo quello che si passa
    done = subprocess.run(
        ["bash", "-c", f'cd "{tmp_path}" && . "{DEV}/platform.sh" && sg_node_road {arg}'],
        capture_output=True, text=True,
        env={**os.environ, "EM_NODE_ROAD": "", "EM_NODE_KIND": "", **env})
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == attesa


def test_una_strada_sconosciuta_e_un_errore(tmp_path):
    done = subprocess.run(
        ["bash", "-c", f'cd "{tmp_path}" && . "{DEV}/platform.sh" && sg_node_road'],
        capture_output=True, text=True, env={**os.environ, "EM_NODE_ROAD": "binari"})
    assert done.returncode != 0 and "binari" in done.stderr


def _compose():
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    if shutil.which("docker") and subprocess.run(
            ["docker", "compose", "version"], capture_output=True).returncode == 0:
        return ["docker", "compose"]
    return None


def test_il_compose_vero_dice_lo_stesso():
    """`config` e basta: legge i file e li fonde, non parla col demone."""
    compose = _compose()
    if compose is None:
        pytest.skip("nessun Docker Compose su questa macchina")
    v = subprocess.run(compose + ["version", "--short"], capture_output=True, text=True)
    nums = re.findall(r"\d+", v.stdout)[:3]
    if len(nums) < 3 or tuple(map(int, nums)) < (2, 24, 4):
        pytest.skip(f"Compose {v.stdout.strip()} non conosce `!override`")
    done = subprocess.run(
        compose + ["-f", str(BASE), "-f", str(IMAGES), "-f", str(FIELD),
                   "--profile", "https", "config", "--format", "json"],
        capture_output=True, text=True, cwd=DEV,
        env={**os.environ, "COMPOSE_PROJECT_NAME": "em-prova-immagini"})
    assert done.returncode == 0, done.stderr
    services = json.loads(done.stdout)["services"]
    dev = DEV.resolve()
    for name, svc in services.items():
        assert "build" not in svc, f"{name} si costruisce ancora"
        for vol in svc.get("volumes", []):
            if vol.get("type") == "bind":
                src = pathlib.Path(vol["source"]).resolve()
                assert dev in (src, *src.parents), (
                    f"{name} monta {src}, fuori da dev-stack/")
    for name, published in NOSTRI.items():
        assert services[name]["image"].startswith(f"ghcr.io/stratigraph-eccch/{published}:")
