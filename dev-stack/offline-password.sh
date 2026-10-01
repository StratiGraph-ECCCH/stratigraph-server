#!/usr/bin/env bash
# The password for the field, for ONE accredited ORCID iD.
#
#   ./dev-stack/offline-password.sh 0000-0002-1825-0097
#
# «L'accesso sul campo» (E.D., 1 Oct 2026): without internet a person signs in to
# the node with the iD and a password of the node, and the node attests the
# identity until the network comes back. The node can only attest what was
# verified once: so this script gives a password ONLY to a user that is already
# LINKED to the realm's ORCID identity provider — somebody who signed in at least
# once with real ORCID. Anybody else is refused, with the reason.
#
# The password is chosen by the node manager AT THE PROMPT (asked twice, not
# echoed): never an argument, never an environment variable, never in a log. It
# is TEMPORARY: the person changes it at the first use (Keycloak asks).
# Non-interactively it reads the two lines from stdin.
#
# Exit: 0 set · 1 Keycloak unreachable · 2 not an iD / the two entries differ /
#       too short · 3 no user for this iD (not accredited: ./accredit.sh) ·
#       4 the user never signed in with ORCID.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=kc-admin.sh
source "$HERE/kc-admin.sh"

case "${1:-}" in
    ""|-h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac
ORCID="$(python3 "$HERE/../app/accredited.py" --check "$1")" || exit 2

kc_login
ID="$(kc_user_id "$ORCID")"
if [[ -z "$ID" ]]; then
    KC_EXIT=3 kc_die "$ORCID has no user on this node: it is not accredited.
  Add it to dev-stack/accredited.yaml and run ./accredit.sh; then the person
  signs in once with ORCID, and only then the offline password can be given."
fi

LINKED="$(kc_api GET "/users/$ID/federated-identity" | python3 -c '
import json, sys
try:
    links = json.load(sys.stdin)
except ValueError:
    links = []
print("yes" if any(l.get("identityProvider") == sys.argv[1] for l in links) else "")' \
    "$KC_ORCID_IDP")"
if [[ -z "$LINKED" ]]; then
    KC_EXIT=4 kc_die "$ORCID never signed in with ORCID on this node (no link to
  the identity provider «$KC_ORCID_IDP»). The node attests only an iD that ORCID
  verified once: the person signs in online with ORCID first, then run this again."
fi

ask() {
    local prompt="$1" value
    if [[ -t 0 ]]; then
        read -r -s -p "$prompt" value; echo >&2
    else
        IFS= read -r value || true
    fi
    printf '%s' "$value"
}
P1="$(ask "offline password for $ORCID: ")"
P2="$(ask "again: ")"
[[ "$P1" == "$P2" ]] || KC_EXIT=2 kc_die "the two entries differ: nothing changed"
[[ ${#P1} -ge 8 ]] || KC_EXIT=2 kc_die "at least 8 characters: nothing changed"

# The password goes through stdin (a here-string is a shell builtin), so it is in
# no command line; the here-string's own trailing newline is the one removed.
BODY="$(python3 -c '
import json, sys
value = sys.stdin.read()
value = value[:-1] if value.endswith("\n") else value
print(json.dumps({"type": "password", "temporary": True, "value": value}))' <<< "$P1")"
P1=""; P2=""
kc_api PUT "/users/$ID/reset-password" - <<< "$BODY" >/dev/null
BODY=""
[[ "$KC_CODE" == 204 ]] || kc_die "Keycloak refused the password (HTTP $KC_CODE): \
the realm's password policy may want more"
echo "✔ $ORCID: temporary offline password set. The person changes it at the first sign-in."
