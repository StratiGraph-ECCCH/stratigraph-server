"""The field node's own installation (E.D., 31 Oct 2026): secrets generated,
no demonstration accounts, the manager named by their ORCID, Keycloak's data
kept across `down`. `dev-stack/field_setup.py`, `render_realm.py --campo`,
`docker-compose.field.yml`."""

import importlib.util
import json
import pathlib
import shutil

import pytest
import yaml

DEV = pathlib.Path(__file__).resolve().parent.parent / "dev-stack"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, DEV / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fs = _load("field_setup")
rr = _load("render_realm")
ME = "0000-0002-1825-0097"


@pytest.fixture
def here(tmp_path):
    shutil.copyfile(DEV / ".env.dev.example", tmp_path / ".env.dev.example")
    return tmp_path


def _env(path):
    return fs.read_env(path / ".env.dev")[1]


def test_l_orcid_si_controlla():
    assert fs.orcid_ok("0000-0002-1825-0097") == ME
    assert fs.orcid_ok("000000021825009 7") == ME
    assert fs.orcid_ok("0000-0002-1825-0098") is None
    assert fs.orcid_ok("0000-0000-0000-001X") == "0000-0000-0000-001X"


def test_un_nodo_nuovo_riceve_i_suoi_segreti_e_il_suo_gestore(here, capsys):
    assert fs.main(["--orcid", ME, "--name", "Josiah Carberry", "--node-name", "scavo-2027"],
                   here=here, volume_check=lambda v: False) == 0
    env = _env(here)
    for key, defaults in fs.DEV_DEFAULTS.items():
        assert env[key] not in defaults and len(env[key]) >= 24, key
    assert env["EM_NODE_KIND"] == "field" and env["EM_ALLOW_TEST_PEOPLE"] == "0"
    assert env["DEV_OPERATOR_ORCID"] == ME and env["EM_NODE_NAME"] == "scavo-2027"
    assert env["ORCID_ISSUER"] == "https://orcid.org"
    listed = yaml.safe_load((here / "accredited.field.yaml").read_text())
    assert listed["accredited"] == [{"orcid": ME, "name": "Josiah Carberry"}]
    printed = capsys.readouterr().out
    for key in fs.DEV_DEFAULTS:
        assert env[key] not in printed, "a secret was printed"


def test_rilanciarlo_non_rompe_un_nodo_che_funziona(here):
    fs.main(["--orcid", ME, "--name", "A B"], here=here, volume_check=lambda v: False)
    before = _env(here)
    fs.main(["--orcid", "0000-0003-1111-1112", "--name", "C D"], here=here, volume_check=lambda v: False)
    after = _env(here)
    for key in fs.DEV_DEFAULTS:
        assert before[key] == after[key]
    listed = yaml.safe_load((here / "accredited.field.yaml").read_text())["accredited"]
    assert [p["orcid"] for p in listed] == [ME, "0000-0003-1111-1112"]


def test_dati_che_esistono_gia_tengono_il_loro_segreto(here):
    fs.main(["--orcid", ME, "--name", "A B"], here=here,
            volume_check=lambda v: v == fs.RUSTFS_VOLUME)
    env = _env(here)
    assert env["RUSTFS_ACCESS_KEY"] == "em-dev-s3" and env["RUSTFS_SECRET_KEY"] == "em-dev-s3-secret"
    assert env["KEYCLOAK_ADMIN_PASSWORD"] != "admin"


def test_un_iD_sbagliato_si_ferma_prima_di_scrivere(here):
    assert fs.main(["--orcid", "1234", "--name", "A B"], here=here, volume_check=lambda v: False) == 2
    assert not (here / ".env.dev").exists()


def test_il_realm_del_campo_non_ha_account_e_ha_il_suo_segreto():
    realm = json.loads((DEV / "keycloak" / "realm-em-dev.json").read_text())
    assert realm["users"], "the committed realm still carries the demo accounts"
    field = rr.per_il_campo(realm, segreto_server="s3cr3t-of-this-node")
    assert field["users"] == []
    server = [c for c in field["clients"] if c["clientId"] == "em-server"][0]
    assert server["secret"] == "s3cr3t-of-this-node"
    assert realm["users"], "the function is pure"
    with pytest.raises(rr.NomeRifiutato):
        rr.per_il_campo(realm, segreto_server="em-dev-secret")


def test_il_realm_del_campo_si_rende_anche_per_un_nome(tmp_path, monkeypatch):
    monkeypatch.setenv("DEV_CLIENT_SECRET", "s3cr3t")
    out = tmp_path / "realm.campo.json"
    assert rr.main(["--campo", "--host", "scavo-mac.local", "--in",
                    str(DEV / "keycloak" / "realm-em-dev.json"), "--out", str(out), "--zitto"]) == 0
    field = json.loads(out.read_text())
    assert field["users"] == []
    console = [c for c in field["clients"] if c["clientId"] == "em-console"][0]
    assert any("scavo-mac.local:8443" in u for u in console["redirectUris"])
    monkeypatch.delenv("DEV_CLIENT_SECRET")
    assert rr.main(["--campo", "--in", str(DEV / "keycloak" / "realm-em-dev.json"),
                    "--out", str(out), "--zitto"]) == 2


def test_keycloak_tiene_i_suoi_dati_sul_nodo_da_campo():
    over = yaml.safe_load((DEV / "docker-compose.field.yml").read_text())
    assert "keycloak_field_data:/opt/keycloak/data" in over["services"]["keycloak"]["volumes"]
    assert "keycloak_field_data" in over["volumes"]
    assert "./accredited.field.yaml:/srv/em-node/accredited.yaml:ro" in \
        over["services"]["stratigraph-server"]["volumes"]
    up = (DEV / "fcn-up.sh").read_text()
    down = (DEV / "fcn-down.sh").read_text()
    assert "docker-compose.field.yml" in up and "docker-compose.field.yml" in down
    assert "render_realm.py --campo" in up and "accredit.sh accredited.field.yaml" in up
