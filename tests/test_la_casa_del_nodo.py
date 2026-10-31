"""La porta e la casa del nodo (scrivania «casa del nodo», 31 ottobre 2026):
una sola porta prima dell'accesso, una sola casa dopo, per tutti."""
import pathlib
import re

ADMIN = pathlib.Path(__file__).resolve().parents[1] / "app" / "node_admin"


def _read(name):
    return (ADMIN / name).read_text(encoding="utf-8")


def test_the_door_says_what_is_done_here_in_both_complete_languages():
    i18n = _read("i18n.js")
    assert '"porta.title": "Qui si lavora insieme sugli studi e scavi archeologici."' in i18n
    for key in ("porta.title", "porta.orcid", "porta.password", "porta.tools",
                "casa.out", "casa.onNode"):
        assert i18n.count(f'"{key}"') >= 2, key


def test_the_house_is_for_everybody_and_the_node_for_operators():
    assert re.search(r'register\(\{ id: "home".*everyone: true, order: 0', _read("modules/home.js"))
    assert re.search(r'register\(\{ id: "tools".*everyone: true, order: 1', _read("modules/tools.js"))
    assert "everyone" not in _read("modules/people.js")
    assert "isOperator || m.everyone" in _read("console.js")


def test_an_invitation_lands_in_the_house_and_is_accepted_there():
    home = _read("modules/home.js")
    assert 'api.post("/join", { token: join })' in home
    assert 'door.searchParams.set("join", made.token)' in _read("modules/rooms.js")
    assert "../work/" not in _read("modules/rooms.js")


def test_the_door_asks_orcid_directly_when_the_node_has_it():
    assert 'url.searchParams.set("kc_idp_hint", hint)' in _read("auth.js")
    assert "hint: orcidReady ? authConfig.orcid_idp" in _read("console.js")


def test_a_program_to_install_is_always_next_to_its_button():
    home = _read("modules/home.js")
    assert "Installa EMStudio" in home and "Installa Blender ed EMtools" in home
    tools = _read("modules/tools.js")
    assert "Blender 4.4" in tools and "4.5" in tools
