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
    #: «Strumenti» is a page of its own since 11 November 2026 (`/tools/`)
    assert not (ADMIN / "modules" / "tools.js").exists()
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
    assert 'installLink(t("home.install.emstudio"))' in home
    assert 'installLink(t("home.install.blender"))' in home
    i18n = _read("i18n.js")
    assert '"home.install.emstudio": "Installa EMStudio"' in i18n
    assert '"home.install.blender": "Prima volta? Installa Blender ed EMtools"' in i18n
    # …and the way to install leads to the tools PAGE, by address
    assert 'a.href = "../tools/";' in home
    tools = (ADMIN.parent / "tools_ui" / "tools.js").read_text(encoding="utf-8")
    assert 't("tools.emt.1.body")' in tools
    assert "Blender 4.4 or 4.5" in i18n and "Blender 4.4 o 4.5" in i18n
