# The dev realm

`realm-em-dev.json` is imported by the dev-stack Keycloak at start-up. Everything
in it is a **development** credential and none of it is ever a production one:
the real realm is the shared Keycloak the Ansible role points at.

**The file itself carries no comments on purpose.** Keycloak's importer
deserializes strictly and refuses an unknown key — a `_comment` field at the top
stops the container from starting, with a Jackson stack trace that says nothing
about realms. So the explanation lives here.

What it seeds, and why each piece is needed to get a token with `curl`:

| piece | why |
|---|---|
| realm `em-dev` | the isolated realm this stack validates against |
| client `em-server` | confidential (`em-dev-secret`), **service accounts ON** so `client_credentials` works, **direct access grants ON** so a password grant works too — which is what a human uses |
| mapper `audience` | **the one that is always missing.** Without it the token's `aud` is `account`, and StratiGraph Server answers `403 … issued for another client`. It is the single most common reason a correct-looking token is refused |
| mapper `orcid` | puts the user's ORCID iD in the token, so the room stamps an identity (`_identity()` in `app/ws.py` reads `orcid` first) instead of leaving edits unsigned |
| user `dev` / `dev` | the human; carries the ORCID attribute. Bootstraps as the **owner** of any room they are the first to join |
| user `viewer` / `viewer` | a second, ordinary authenticated identity with **no** membership anywhere. Added 2026-08-17 for the embargo end-to-end (`dev-stack/smoke_embargo_viewer.py`): the gate refuses anybody below editor, and with one user in the realm there was nobody to be refused — the 403 could only be measured against a stand-in. Its ORCID is a different one, so a room can tell the two apart |

| users `editor` / `editor2` / `outsider` (password = username) | added 2026-10-25 for **firme vere e ruoli nella stanza**: the four cases a room tells apart need four people. `editor` and `editor2` are two editors (two authors to tell apart in one room's register), `viewer` above is the reader, and `outsider` is an authenticated identity with **no** role anywhere — the one the door closes on with 4403. ORCIDs `0000-0003-1111-1112`, `0000-0003-2222-2221`, `0000-0003-3333-3330` (valid check digits, not real people). The ROLES are not here: roles live in the room's ACL on StratiGraph Server (`PUT /v1/rooms/{id}/members/{orcid}`), the realm only says who somebody is |
| client `stratifield-breve` | public, PKCE S256, **access tokens of 60 s**, same three mappers as `em-console` (`em-server` + `em-chatbot` audiences, `orcid`), redirect URIs of the field page only. Exists for the EXPIRY proofs: `em-console` issues 900 s, and a token that lapses inside an open session is a thing nobody waits a quarter of an hour to watch. Direct access grants ON, so a smoke can mint one with `curl` (dev realm only). Point a StratiField at it with `EM_CHATBOT_CLIENT_ID=stratifield-breve` |

No custom scope is required, so `OIDC_REQUIRED_SCOPE` stays unset.

**Lifespans, measured on 25 October**: `em-server` (password grant) 3600 s ·
`em-console` (the pages' PKCE client) 900 s · `stratifield-breve` 60 s. The
refresh token lives 1800 s (`refresh_expires_in`), the realm's SSO idle.

## `em-console`'s redirect URIs, and the two that are deliberately NOT there

pyarchinit-mini joined the realm on 2026-09-12 by REUSING `em-console` — the
public client the other browser pages already use — rather than by getting a
third client. It needs nothing `em-console` does not already have: the standard
flow and the `orcid` mapper. A client per page would be three places to add a
mapper to.

**And it needs the `orcid` mapper through `/userinfo`, not through the
id_token.** Worth writing down, because the first live sign-in failed on it and
the next reader will hit the same wall: both mappers on both clients carry

    id.token.claim       = false
    access.token.claim   = true
    userinfo.token.claim = true      (orcid only)

So an id_token from this realm carries **no `orcid`** and **no
`aud: em-server`** — and neither is a gap. An id_token's `aud` is the client
that requested it (OpenID Connect Core); `em-server` is the audience of the
ACCESS token, which is what a resource server validates and what the `audience`
mapper exists to write. A CLIENT reading its own id_token must check `aud`
against its own `client_id`, and must ask `/userinfo` for the ORCID.

The alternative — flipping `id.token.claim` to true here — was deliberately not
taken: it changes a file the whole stack imports, and on the institutional node
this realm belongs to somebody else. A door that only opens while a third party
keeps a flag set is a door that closes one day without warning.

Four spellings, and they arrived in two goes for a reason worth keeping:

    http://localhost:8090/*                    (2026-09-12)  ← WITHDRAWN 10-07
    http://127.0.0.1:8090/*                    (2026-09-12)  ← WITHDRAWN 10-07
    https://em.localhost:8443/pyarchinit/*     (2026-09-17)  ← WITHDRAWN 10-07
    https://localhost:8443/pyarchinit/*        (2026-09-17)  ← WITHDRAWN 10-07

On 12 September the last two were **considered and refused**, because
`Caddyfile.dev` had no `/pyarchinit/*` route: granting them would have made
Keycloak answer «accepted» for an address that could not be reached, which is
worse than a refusal because it looks like it works.

On 17 September the route was built, so the reason lapsed and they were added.

**And on 7 October 2026 all four were withdrawn**, because pyarchinit-mini left
the stack: the decision is that we will not use it (the DESKTOP pyarchinit is
another thing and stays). The reason of 12 September came back exactly as it was
written — a redirect granted towards a path that answers nothing is a surface
left open for an app that is not there — so the grants went with the route.

Two of the four do not contain the word «pyarchinit». `grep -rn pyarchinit` on
`dev-stack/` finds the last two and misses the first two: what names them is the
PORT, `PYARCHINIT_PORT:-8090`, which the compose no longer publishes. Worth
writing down, because that is how a grant survives the thing it was granted for.

## `em-console`'s redirect URIs · the catalogue, added 2026-10-07

    https://em.localhost:8443/catalog/ui/*     (2026-10-07)
    https://localhost:8443/catalog/ui/*        (2026-10-07)

The catalogue's page held no token until then, «and that is deliberate»: a
catalogue exists to be found, and an anonymous caller must be answered. Reading
stays anonymous. What changed is that `DELETE /catalog/study/{id}` — written,
tested and running from the start — was callable by nobody with a browser,
because the only surface that shows a study had no way to be anybody.

The SAME client (`em-console`) and the same reasoning as pyarchinit-mini's in
September: it needs nothing that client does not already have, and a client per
page would be four places to add a mapper to.

What made the route possible was not a Caddy line but the thing that Caddy line
needs on the other side: pyarchinit-mini serves at its own root, so
`handle_path` strips `/pyarchinit` and hands it back in `X-Forwarded-Prefix`,
and the application turns that into WSGI's `SCRIPT_NAME` with `ProxyFix` — but
**only when `PYARCHINIT_BEHIND_PROXY` is set**, which the compose does for that
one service. Without it those headers are caller-supplied, and most people who
run pyarchinit-mini expose it directly.

Changing any of this means changing **this file**, not only `.env.dev`: the env
file selects which realm/client to ask for, the JSON is what actually exists.

**And a change here needs a RE-IMPORT.** Keycloak runs `start-dev
--import-realm`, which imports only when the realm is not already in the
container's own database — so editing this file changes nothing until the
container is recreated:

    cd dev-stack && docker-compose -f docker-compose.dev.yml --env-file .env.dev \
        up -d --force-recreate keycloak

The re-import mints **new realm keys**: every token issued before it stops
verifying. That is expected, and it is why a room that suddenly answers 4401
right after a realm change is not a bug — ask for a token again.

## Re-importing the realm after you change it — no `--wipe` needed

MEASURED 2026-08-29, because "import happens once" had become folklore here and
the folklore was costing a `--wipe` (which erases the studies, the rooms and the
bucket) every time somebody added a redirect URI.

This Keycloak has **no data volume**: the service mounts only
`realm-em-dev.json`, read-only, and `start-dev` keeps its database inside the
container. So the realm is re-imported whenever the CONTAINER is recreated:

```bash
docker compose --env-file .env.dev -f docker-compose.dev.yml \
  up -d --force-recreate --no-build keycloak
```

Healthy in ~30s, and the new realm is live. `--wipe` is for when you want the
DATA gone, which is a different intention and should stay a different command.

The trade-off, stated: nothing you do in the admin console survives a recreate
either. Edit the JSON, not the running realm — the JSON is the one that is in
git.

## `/auth`, and why Keycloak has ONE public URL

Keycloak serves under `KC_HTTP_RELATIVE_PATH=/auth` so Caddy's `handle /auth/*`
lands (with `handle`, the prefix is KEPT, so Keycloak must expect it — with
`handle_path` it is stripped and Keycloak must not). And `KC_HOSTNAME_URL` fixes
the FRONTEND url, which is what decides the `iss` a token carries.

That last part is the fix to a real bug, not tidiness. `app/auth.py` verifies
`iss` strictly against `OIDC_ISSUER`; with two spellings of the realm (the proxy
on 8443 and the direct port on 8085) tokens from one door are refused by a
service configured for the other. One frontend URL means one `iss`, whichever
door it came through — measured: a token from `token.sh` (direct port) carries
`iss = https://em.localhost:8443/auth/realms/em-dev` and `GET /v1/whoami` answers
200.

## L'accesso sul campo — ORCID, the accredited list, the node's password (2026-10-01)

Decided by E.D. on 1 October 2026: **a user is an ORCID**. Online you sign in
with ORCID (*verified by ORCID*); on the field, without internet, with the iD and
a password the node gave you (*attested by the node*). Nobody gets a password who
has not signed in once with real ORCID. What the realm carries for it, every piece
measured on this image (Keycloak 24.0.4) in a throwaway container:

| piece | what it does |
|---|---|
| `identityProviders[orcid]` | OIDC broker towards `${ORCID_ISSUER}` (sandbox by default, `https://orcid.org` for the real one). Endpoints written out, not discovered: Keycloak's importer does no discovery. **Client id and secret are `${ORCID_CLIENT_ID}` / `${ORCID_CLIENT_SECRET}`**: Keycloak resolves the placeholders from its own environment at import (measured: the id came out substituted), and the compose passes them from `.env.dev` or the shell. Never in this file |
| `identityProviderMappers` | username = the ORCID `sub` (the iD); attribute `orcid` = the `sub`, FORCE-synced at every login |
| flow `em accredited first login` | the IdP's first-login flow: **detect existing user** + **automatically link**. No «create user»: an iD with no user is refused — measured: «The ORCID iD 0000-0003-5555-5559 is not accredited on this node…» (the realm overrides `federatedIdentityUnavailableMessage`). Keycloak has no condition «iD in a list», so the list is enforced by **who exists**: `../accredit.sh` creates the users from `../accredited.yaml` |
| user profile | KC 24 has the declarative user profile ON, and **an undeclared attribute is silently dropped by the admin API** (measured: a user created with `orcid` came back without it). So `orcid` is declared (pattern-validated, edit = admin only), and email/first/last name are no longer required — otherwise every login of a user without an e-mail would stop at «update your profile» |
| mappers `em-idp`, `em-auth-reported` | on every client that carries `orcid`. `em_idp` = the user-session note `identity_provider` (`orcid` after a brokered login, absent after a password); `em_auth_reported: true` says this realm reports the mode, so absence means *password*. `oidc-amr-mapper` exists in 24.0.4 but gave `amr: []` for both — not used. `/v1/whoami` reads them (`app/identity.py::auth_mode_of`) |

The offline password: `../offline-password.sh <iD>` — only for a user already
LINKED to `orcid`, chosen at the prompt, temporary (changed at first use).

Two files, NOT `realm-em-dev.demo.json`: that one is rendered by
`render_realm.py` and git-ignored (`realm-em-dev.*.json`), so it follows this
file at the next `fcn-up.sh`.
