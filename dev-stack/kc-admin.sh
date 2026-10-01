# Sourced, not run: the Keycloak admin REST calls `accredit.sh` and
# `offline-password.sh` share. Nothing here prints a secret.
#
# The admin password and the admin token never appear in a command line (where
# `ps` would show them to every user of the machine): the password reaches curl
# through stdin (`--data-urlencode password@-`), the token through a header read
# from a pipe (`-H @<(…)`).
#
# Reads KEYCLOAK_ADMIN / KEYCLOAK_ADMIN_PASSWORD / KEYCLOAK_PORT / DEV_REALM from
# dev-stack/.env.dev, the environment winning over the file (token.sh's order).
# KC_URL overrides the whole base (`http://localhost:<port>/auth`).

KC_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

kc_env_of() {
    local name="$1" fallback="$2" value
    value="${!name:-}"
    if [[ -z "$value" && -f "$KC_HERE/.env.dev" ]]; then
        value="$(grep -E "^${name}=" "$KC_HERE/.env.dev" | tail -1 | cut -d= -f2-)"
    fi
    printf '%s' "${value:-$fallback}"
}

KC_URL="${KC_URL:-http://localhost:$(kc_env_of KEYCLOAK_PORT 8085)/auth}"
KC_REALM="$(kc_env_of DEV_REALM em-dev)"
#: the identity-provider alias that IS ORCID in the realm
KC_ORCID_IDP="${EM_ORCID_IDP_ALIAS:-orcid}"
KC_TOKEN=""

kc_die() { echo "✖ $*" >&2; exit "${KC_EXIT:-1}"; }

kc_login() {
    local admin answer
    admin="$(kc_env_of KEYCLOAK_ADMIN admin)"
    answer="$(kc_env_of KEYCLOAK_ADMIN_PASSWORD admin | curl -sS -X POST \
        "$KC_URL/realms/master/protocol/openid-connect/token" \
        --data-urlencode "grant_type=password" \
        --data-urlencode "client_id=admin-cli" \
        --data-urlencode "username=${admin}" \
        --data-urlencode "password@-" || true)"
    KC_TOKEN="$(printf '%s' "$answer" | python3 -c \
        'import json,sys; print(json.load(sys.stdin).get("access_token",""))' \
        2>/dev/null || true)"
    [[ -n "$KC_TOKEN" ]] || kc_die "no admin token from $KC_URL (is Keycloak up? \
are KEYCLOAK_ADMIN / KEYCLOAK_ADMIN_PASSWORD right?)"
}

#: kc_api METHOD PATH [BODY-ON-STDIN] → prints the body; HTTP code in KC_CODE
kc_api() {
    local method="$1" path="$2" out
    out="$(mktemp)"
    KC_CODE="$(curl -sS -o "$out" -w '%{http_code}' -X "$method" \
        -H @<(printf 'Authorization: Bearer %s\nContent-Type: application/json\n' "$KC_TOKEN") \
        ${3:+--data-binary @-} \
        "$KC_URL/admin/realms/$KC_REALM$path" || echo 000)"
    cat "$out"; rm -f "$out"
}

#: the id of the user whose USERNAME is exactly $1 (Keycloak lower-cases it), or ""
kc_user_id() {
    kc_api GET "/users?exact=true&username=$(python3 -c \
        'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1].lower()))' "$1")" \
    | python3 -c '
import json, sys
want = sys.argv[1].lower()
try:
    users = json.load(sys.stdin)
except ValueError:
    users = []
print(next((u["id"] for u in users if u.get("username", "").lower() == want), ""))' "$1"
}
