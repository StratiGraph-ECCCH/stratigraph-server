"""THE LIST MAKES THE PEOPLE: profiles and teams from the accredited file.

Decided by E.D. on 31 October 2026: the node manager writes who works on the
node in ONE file, with their profile and their teams, instead of adding people
one by one in the console. `accredited.py` reads the file (stdlib only, for the
scripts too); this module APPLIES it to the node's registers, at start-up.

What it does, and what it never does:

* every iD in the list is in the people register, with its name;
* an entry with `profile:` gets that profile — the FILE WINS for it, at every
  start, because the file is where the manager wrote it;
* an entry without `profile:` is left as the console set it (a new person
  starts as `user`);
* every team named under `groups:` exists, and the person is in it;
* **nothing is ever removed**: taking somebody out of the list, or out of a
  team, is a decision made in the console, where it can be seen. The same rule
  `accredit.sh` follows for the realm.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

#: the name the people log gives to changes made by the file
BY = "accredited-file"


def team_id(name: str) -> str:
    """A stable id from a team's name: lower case, words joined by `-`."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:60] or "team"


def make_people(entries: List[Dict[str, Any]], people: Any, groups: Any) -> Dict[str, int]:
    """Bring the registers in line with the list. Returns what changed."""
    from .access import Group
    from .people import Person

    said = {"people_added": 0, "people_updated": 0, "teams_added": 0,
            "memberships_added": 0}
    known = people.all()
    owner: Optional[str] = next((e["orcid"] for e in entries
                                 if e.get("profile") == "super"), None)
    for entry in entries:
        orcid, name = entry["orcid"], entry.get("name", "")
        person = known.get(orcid)
        if person is None:
            people.put(Person(orcid, name, entry.get("profile", "user"), added_by=BY))
            said["people_added"] += 1
        else:
            changed = False
            if name and person.name != name:
                person.name, changed = name, True
            if entry.get("profile") and person.profile != entry["profile"]:
                person.profile, changed = entry["profile"], True
            if changed:
                people.put(person)
                said["people_updated"] += 1
    teams = groups.all()
    for entry in entries:
        for name in entry.get("groups", []):
            gid = team_id(name)
            team = teams.get(gid)
            if team is None:
                team = Group(gid, name, [], owner)
                teams[gid] = team
                said["teams_added"] += 1
            if team.add(entry["orcid"]):
                said["memberships_added"] += 1
            groups.put(team)
    return said
