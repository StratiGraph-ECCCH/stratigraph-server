# Testing with people who do not exist

A node knows a person by their ORCID iD, and the node gives a password for the
field only to an iD ORCID verified once. That is right for a real node and
awkward for a test: E.D., 30 October 2026, *«devo essere quell'utente per
poterlo creare, ovvero lavora con identità vere ORCID: tosto fare test con
utenti fittizi»*. There are two ways, and they test different things.

## 1 · Test people — fast, on the dev stack only

For filling a node with ten people and trying profiles, roles, groups and
permissions in an afternoon.

* The dev stack runs with `EM_ALLOW_TEST_PEOPLE=1` (the compose default).
  **Never set it on a real node.**
* A test person has an iD in the range ORCID never issues: `0000-0000-…`, with a
  correct check digit. They are marked **test** everywhere in the console.
* They get a password **directly**, without having signed in with ORCID first.

How:

1. Node console → **People** → **Test people…**, and say how many. They arrive
   as *Prova Uno*, *Prova Due*… with the profile *user*; the first iD is
   `0000-0000-0000-001X`, then `0000-0000-0000-0028`, and so on.
2. Open a person → change the profile if needed (node editor, super) → **Field
   password** → type a password twice. It is temporary.
3. Sign in as that person in a **private window** (so your own session stays):
   open the node, *Sign in*, user name = the iD, password = the one you typed.
   Keycloak asks for a new password at once; then you are that person.

What this does **not** test: the ORCID sign-in itself and the rule «a password
only for an iD ORCID verified».

## 2 · ORCID's sandbox — faithful, slower

`sandbox.orcid.org` is ORCID's own test service: real sign-in flow, fictitious
researchers. The dev realm already points at it (`ORCID_ISSUER` defaults to
`https://sandbox.orcid.org` in `docker-compose.dev.yml`); what it lacks is a
client registration.

1. Create a sandbox account at <https://sandbox.orcid.org/register> (any email:
   sandbox mail is not delivered, use a throw-away address you can read, e.g. a
   `mailinator.com` one, and confirm it).
2. In that account: **Developer tools** → register a public API client with the
   redirect URI `https://em.localhost:8443/auth/realms/em-dev/broker/orcid/endpoint`.
3. Put the client id and secret in `dev-stack/.env.dev`:
   `ORCID_CLIENT_ID=APP-…` and `ORCID_CLIENT_SECRET=…`, then re-render and restart
   the stack (`./fcn-up.sh`). The node console's sign-in shows the ORCID button.
4. For each fictitious researcher: register another sandbox account; its iD is
   on its sandbox profile page.
5. Node console → **People** → **Add a person** with that iD. The person signs
   in once with *Sign in with ORCID* (sandbox), then you can give them a field
   password: the real rule, with fictitious people.

Sandbox iDs look like real ones and they are *not* in the test range: a node
treats them exactly as it treats real people, which is the point.
