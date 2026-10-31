"""La lista degli accreditati con profilo e squadre (31 ottobre 2026): il gestore
scrive in un file chi lavora sul nodo, e il nodo crea persone, profili e
squadre a ogni avvio — senza mai togliere nessuno."""
import pytest

from app import accredited
from app.accredited_apply import make_people as apply, team_id
from app.access import Groups, InMemoryGroupStore
from app.people import InMemoryPeopleStore, People, Person

LIST = """
accredited:
  - orcid: 0000-0002-1825-0097
    name: Dev User
    profile: super
  - orcid: 0000-0003-1111-1112
    name: Editor Uno
    profile: editor
    groups: [Squadra Templu Mare, Restauro]
  - orcid: 0000-0003-2222-2221
    name: Editor Due
    groups: Squadra Templu Mare
"""


def test_the_list_reads_profile_and_groups():
    rows = accredited.parse(LIST)
    assert rows[0]["profile"] == "super"
    assert rows[1]["profile"] == "creator"       # «editor» è l'editor di nodo
    assert rows[1]["groups"] == ["Squadra Templu Mare", "Restauro"]
    assert "profile" not in rows[2] and rows[2]["groups"] == ["Squadra Templu Mare"]


def test_a_wrong_profile_is_refused_with_its_entry():
    with pytest.raises(accredited.AccreditedListError, match="entry 1"):
        accredited.parse("accredited:\n  - orcid: 0000-0002-1825-0097\n    profile: boss\n")


def test_applying_makes_people_profiles_and_teams_and_removes_nothing():
    people, groups = People(InMemoryPeopleStore()), Groups(InMemoryGroupStore())
    people.put(Person("0000-0003-2222-2221", "", "creator"))   # dato dalla console
    groups.put(__import__("app.access", fromlist=["Group"]).Group(
        "restauro", "Restauro", ["0000-0001-5109-3700"]))
    said = apply(accredited.parse(LIST), people, groups)
    everyone = people.all()
    assert everyone["0000-0002-1825-0097"].profile == "super"
    assert everyone["0000-0003-1111-1112"].profile == "creator"
    # senza `profile:` resta quello della console
    assert everyone["0000-0003-2222-2221"].profile == "creator"
    assert everyone["0000-0003-2222-2221"].name == "Editor Due"
    team = groups.get(team_id("Squadra Templu Mare"))
    assert team.members == ["0000-0003-1111-1112", "0000-0003-2222-2221"]
    assert team.owner == "0000-0002-1825-0097"
    # la squadra che c'era tiene chi c'era
    assert groups.get("restauro").members == ["0000-0001-5109-3700", "0000-0003-1111-1112"]
    assert said["people_added"] == 2 and said["teams_added"] == 1
    # una seconda volta non cambia niente
    assert not any(apply(accredited.parse(LIST), people, groups).values())


def test_the_scripts_still_read_two_columns():
    import pathlib, subprocess, sys, tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(LIST)
    out = subprocess.run([sys.executable, str(pathlib.Path(accredited.__file__)), "--tsv", f.name],
                         capture_output=True, text=True)
    assert out.returncode == 0
    assert out.stdout.splitlines()[1] == "0000-0003-1111-1112\tEditor Uno"
