"""I volumi dei dati appartengono all'utente con cui girano le immagini.

Il 28 settembre 2026 i tre volumi del dev-stack (`em_data`, `chatbot_data`,
`em_catalog_data`) erano di `1000:1000`, lasciati da un'immagine più vecchia,
mentre i container girano come `10001:0`. Un volume che esiste già non prende la
proprietà dall'immagine nuova, e il risultato era un `PermissionError` e un 500
alla prima stanza creata. `volumi-init` nel compose lo aggiusta a ogni avvio.

Questo file non avvia docker: legge il compose e i Dockerfile e controlla che le
parti restino d'accordo. La prova dal vivo (un file di 1000:1000 644 messo nel
volume, e ritrovato 10001:0 664 dopo l'avvio) è nel referto della notte.
"""

from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

HERE = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = HERE / "dev-stack" / "docker-compose.dev.yml"
TESTO = COMPOSE.read_text(encoding="utf-8")
DOC = yaml.safe_load(TESTO)
SERVIZI = DOC["services"]
INIT = SERVIZI["volumi-init"]

#: chi scrive su quale volume — e il Dockerfile da cui prende il suo UID
CHI = {"stratigraph-server": "em_data",
       "stratigraph-chatbot": "chatbot_data",
       "stratigraph-catalog": "em_catalog_data"}


def _uid_del_dockerfile(servizio: str) -> str:
    contesto = HERE / "dev-stack" / SERVIZI[servizio]["build"]["context"]
    testo = (contesto / "Dockerfile").read_text(encoding="utf-8")
    trovato = re.search(r"^ARG APP_UID=(\d+)$", testo, re.M)
    assert trovato, f"{servizio}: il Dockerfile non dichiara ARG APP_UID"
    return trovato.group(1)


@pytest.mark.parametrize("servizio", sorted(CHI))
def test_L_UID_DEL_SERVIZIO_E_QUELLO_DELL_IMMAGINE(servizio):
    """Se un Dockerfile cambia UID e il compose no, il servizio di avvio darebbe
    i volumi all'utente sbagliato: il guasto di prima, spostato di un numero."""
    contesto = HERE / "dev-stack" / SERVIZI[servizio]["build"]["context"]
    if not (contesto / "Dockerfile").is_file():
        pytest.skip(f"il repository fratello di {servizio} non è qui")
    assert INIT["environment"]["APP_UID"] == _uid_del_dockerfile(servizio)


@pytest.mark.parametrize("servizio,volume", sorted(CHI.items()))
def test_OGNI_VOLUME_DI_DATI_E_MONTATO_E_ASPETTATO(servizio, volume):
    montati = [m.split(":")[0] for m in INIT["volumes"]]
    assert volume in montati, f"volumi-init non vede {volume}"
    assert any(m.split(":")[0] == volume for m in SERVIZI[servizio]["volumes"])
    attende = SERVIZI[servizio]["depends_on"]["volumi-init"]["condition"]
    assert attende == "service_completed_successfully", servizio


def test_NESSUN_ALTRO_VOLUME_E_TOCCATO():
    """Il one-shot gira come root: vede i tre volumi dei servizi con UID 10001 e
    nient'altro — non MinIO, non Postgres, non la CA di Caddy."""
    montati = sorted(m.split(":")[0] for m in INIT["volumes"])
    assert montati == sorted(CHI.values())


def test_E_UN_ONE_SHOT_SENZA_RETE_E_PINNATO():
    assert INIT["restart"] == "no"
    assert INIT["network_mode"] == "none"
    assert INIT["user"] == "0:0"
    riga = next(r for r in TESTO.splitlines()
                if r.strip().startswith("image:") and "alpine" in r
                and TESTO.index(r) > TESTO.index("  volumi-init:"))
    assert re.search(r"image: alpine:\d+\.\d+\.\d+\s+# sha256:[0-9a-f]{64}$",
                     riga.strip()), riga


def test_LA_REGOLA_E_QUELLA_DEI_DOCKERFILE():
    """Proprietario APP_UID, gruppo 0, e `g=u`: la stessa coppia di comandi che
    i Dockerfile fanno sulle loro cartelle, non una regola nuova."""
    comando = "\n".join(INIT["entrypoint"])
    assert 'chown "$$APP_UID:0"' in comando
    assert 'chmod -R g=u "$$v"' in comando
    dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
    assert "chown -R ${APP_UID}:0" in dockerfile
    assert "chmod -R g=u" in dockerfile
