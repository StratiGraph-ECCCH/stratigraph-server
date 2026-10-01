#!/usr/bin/env bash
# The node's accredited ORCID iDs, made into Keycloak users.
#
#   ./dev-stack/accredit.sh                    reads dev-stack/accredited.yaml
#   ./dev-stack/accredit.sh path/to/list.yaml  another list
#   ./dev-stack/accredit.sh --dry-run          says what it would do, writes nothing
#
# «L'accesso sul campo» (E.D., 1 Oct 2026): a user is an ORCID. For every iD in
# the list this script makes sure there is ONE Keycloak user whose username is
# the iD and whose `orcid` attribute is the iD, with the name from the list. It
# creates it if missing and updates the name and attribute if they drifted.
#
# It does NOT give a password and does NOT link ORCID: the person does the
# second by signing in once with real ORCID (the realm's first-login flow links
# an EXISTING user and never creates one — which is how an iD that is not in
# this list is refused at the door). The password for the field comes after,
# from `./offline-password.sh <iD>`.
#
# It never removes anybody: taking an iD out of the list stops `accredited` in
# `/v1/whoami`, and disabling the user stays a decision of the node manager.
#
# Prints no secret. Exit: 0 done · 1 Keycloak unreachable · 2 the list is wrong.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=kc-admin.sh
source "$HERE/kc-admin.sh"

LIST="$HERE/accredited.yaml"
DRY=""
for arg in "$@"; do
    case "$arg" in
        -h|--help) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        --dry-run) DRY=1 ;;
        *) LIST="$arg" ;;
    esac
done

# The ONE reader of the list (`app/accredited.py`, stdlib only): the server reads
# the same file the same way, so the two cannot disagree about who is in it.
ENTRIES="$(python3 "$HERE/../app/accredited.py" --tsv "$LIST")" || exit 2

kc_login
created=0 updated=0 same=0 refused=0
while IFS=$'\t' read -r orcid name; do
    [[ -n "$orcid" ]] || continue
    first="${name%% *}"; last=""
    [[ "$name" == *" "* ]] && last="${name#* }"
    body="$(python3 -c '
import json, sys
orcid, first, last = sys.argv[1:4]
print(json.dumps({"username": orcid, "enabled": True, "firstName": first,
                  "lastName": last, "attributes": {"orcid": [orcid]}}))' \
        "$orcid" "$first" "$last")"
    id="$(kc_user_id "$orcid")"

    if [[ -z "$id" ]]; then
        # One user per ORCID: an iD some OTHER account already carries (the dev
        # seed's `dev`, say) is not given a second account.
        other="$(kc_api GET "/users?q=orcid:${orcid}&exact=true" | python3 -c '
import json, sys
try:
    users = json.load(sys.stdin)
except ValueError:
    users = []
print(",".join(u.get("username", "?") for u in users))')"
        if [[ -n "$other" ]]; then
            echo "· $orcid  already carried by user «$other»: one user per ORCID, left as it is"
            refused=$((refused + 1)); continue
        fi
        if [[ -n "$DRY" ]]; then echo "+ $orcid  $name  (would be created)"; continue; fi
        kc_api POST "/users" - <<< "$body" >/dev/null
        [[ "$KC_CODE" == 201 ]] || kc_die "creating $orcid: HTTP $KC_CODE"
        echo "+ $orcid  $name  created"
        created=$((created + 1))
        continue
    fi

    now="$(kc_api GET "/users/$id" | python3 -c '
import json, sys
u = json.load(sys.stdin)
print("\t".join([u.get("firstName") or "", u.get("lastName") or "",
                 ",".join((u.get("attributes") or {}).get("orcid") or [])]))')"
    if [[ "$now" == "$first"$'\t'"$last"$'\t'"$orcid" ]]; then
        echo "= $orcid  $name"
        same=$((same + 1)); continue
    fi
    if [[ -n "$DRY" ]]; then echo "~ $orcid  $name  (would be updated)"; continue; fi
    kc_api PUT "/users/$id" - <<< "$body" >/dev/null
    [[ "$KC_CODE" == 204 ]] || kc_die "updating $orcid: HTTP $KC_CODE"
    echo "~ $orcid  $name  updated"
    updated=$((updated + 1))
done <<< "$ENTRIES"

echo "accredited: $created created, $updated updated, $same unchanged, $refused left as they were${DRY:+ (dry run: nothing written)}"
