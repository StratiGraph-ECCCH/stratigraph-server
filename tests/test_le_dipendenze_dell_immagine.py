"""L'immagine installa quello che il pacchetto dichiara.

Il 27 novembre 2026 `python-multipart` è entrato fra le dipendenze di
`pyproject.toml` e NON nella riga `pip install` del Dockerfile, che è scritta a
mano. I test giravano verdi (l'ambiente di prova installa `.[dev]`, quindi il
pacchetto c'era) e l'immagine `1.6.0-dev.93` è uscita senza: ogni deposito
multipart moriva con un 500 che il client vedeva come «Failed to fetch».

Nessuno se n'era accorto perché le due liste non si guardavano. Questo test le
guarda: ogni dipendenza dichiarata nel pacchetto deve stare nella riga
dell'immagine, e viceversa. Non confronta le VERSIONI — il pacchetto dice il
minimo che la libreria richiede, l'immagine può legarsi più stretta — ma i
NOMI, che sono quello che o c'è o manca.

`s3dgraphy` è l'eccezione dichiarata: nell'immagine arriva dall'argomento di
build `S3DGRAPHY_VERSION`, che `bump-s3dgraphy.sh` scrive in tutti e tre i posti
e `tests/test_s3dgraphy_pin.py` tiene uguali.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
PYPROJECT = REPO / "pyproject.toml"
DOCKERFILE = REPO / "Dockerfile"

#: Il nome del pacchetto senza extra, specificatore e spazi: `PyJWT[crypto]>=2.8`
#: → `pyjwt`. Minuscolo e con i trattini normalizzati, come PEP 503 li confronta.
def _name(requirement: str) -> str:
    bare = re.split(r"[\[<>=!~;\s]", requirement.strip(), maxsplit=1)[0]
    return bare.strip().lower().replace("_", "-")


def _declared() -> set:
    text = PYPROJECT.read_text(encoding="utf-8")
    block = re.search(r"^dependencies = \[(.*?)^\]", text, flags=re.S | re.M)
    assert block, "pyproject.toml non dichiara più `dependencies`"
    return {_name(q) for q in re.findall(r'"([^"]+)"', block.group(1))}


def _optional() -> set:
    """Gli extra dichiarati (`s3`, `pg`, `rdf`, `geo`, `all`, `dev`): l'immagine
    può prenderne — e ne prende, perché un nodo deve poter aprire uno store S3 e
    la casa dei documenti —, ma non può installare un pacchetto che nessuno
    dichiara da nessuna parte."""
    text = PYPROJECT.read_text(encoding="utf-8")
    block = re.search(r"^\[project\.optional-dependencies\](.*?)^\[", text,
                      flags=re.S | re.M)
    return {_name(q) for q in re.findall(r'"([^"]+)"', block.group(1))} if block else set()


def _installed_in_the_image() -> set:
    text = DOCKERFILE.read_text(encoding="utf-8")
    # la riga vera, continuazioni comprese; `$spec` è s3dgraphy, trattato a parte
    block = re.search(r"pip install \"\$spec\"(.*?)\n\n", text, flags=re.S)
    assert block, "il Dockerfile non ha più la riga `pip install \"$spec\"`"
    return {_name(q) for q in re.findall(r'"([^"$][^"]*)"', block.group(1))}


def test_tutto_quello_che_il_pacchetto_dichiara_sta_nell_immagine():
    manca = _declared() - _installed_in_the_image() - {"s3dgraphy"}
    assert manca == set(), (
        f"dichiarate in pyproject.toml e non installate nell'immagine: "
        f"{sorted(manca)} — una build andrebbe su, e cadrebbe alla prima "
        f"richiesta che ne ha bisogno")


def test_l_immagine_non_installa_niente_che_nessuno_dichiara():
    di_troppo = (_installed_in_the_image() - _declared() - _optional()
                 - {"s3dgraphy"})
    assert di_troppo == set(), (
        f"installate nell'immagine e dichiarate da nessuna parte: "
        f"{sorted(di_troppo)} — o diventano una dipendenza, o un extra, o non "
        f"stanno lì: chi legge pyproject.toml deve poter sapere di che cosa è "
        f"fatto un nodo")


def test_python_multipart_e_in_tutti_e_due_i_posti():
    """Il caso che ha generato il test, nominato: la porta del deposito legge un
    corpo multipart, e Starlette lo sa fare solo con questo pacchetto."""
    assert "python-multipart" in _declared()
    assert "python-multipart" in _installed_in_the_image()
