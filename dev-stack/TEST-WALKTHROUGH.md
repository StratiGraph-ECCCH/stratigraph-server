# FCN — test walkthrough (dev-stack)

Guida ai test della stack StratiGraph di campo. Presuppone l'FCN acceso:
`./fcn-up.sh` (o `--local-s3d`) e la CA fidata (`./fcn-trust-ca.sh`).

## Tappa 1 — i servizi sono vivi (browser)
- StratiGraph Server   → https://em.localhost:8443/em/v1/health
- catalog     → https://em.localhost:8443/catalog/health
- RustFS cons. → http://localhost:9001/rustfs/console/   (chiavi `RUSTFS_*` in `.env.dev`)
- Keycloak    → http://localhost:8085   (realm `em-dev`)

## Tappa 2 — gli smoke end-to-end (la prova vera)
Da `~/Documents/GitHub/StratiGraph Server` (servono i pacchetti `requests` e `boto3`:
`pip3 install requests boto3 --break-system-packages`):

    python3 dev-stack/smoke.py          # AssetStore/S3 (RustFS) reale: PUT→sha256→GET, auth, promozione DP-76
    python3 dev-stack/smoke_iiif.py     # immagini: RustFS → Cantaloupe → info.json/thumbnail/regione + manifest IIIF
    python3 dev-stack/smoke_catalog.py  # Catalog: registra studi, public/restricted, TTL-publish nasconde il tombstone,
                                        #          e RICOSTRUISCE l'indice dai container nel bucket (l'indice è derivato)
    python3 dev-stack/smoke_embargo_viewer.py
                                        # il CANCELLO con una persona vera: viewer→403 (con la data), dev→200,
                                        #          anonimo→401, embargo tolto→200 per tutti

**Il secondo utente del realm.** `smoke_embargo_viewer.py` usa l'utente `viewer`
(password `viewer`), seminato in `dev-stack/keycloak/realm-em-dev.json`. Un
Keycloak avviato **prima** che quella riga esistesse non ce l'ha, e lo smoke lo
dice invece di fallire nel vago. Il realm si ri-importa ricreando il container
(`start-dev` tiene il realm nel database del container):

    cd dev-stack && docker-compose -f docker-compose.dev.yml --env-file .env.dev \
        up -d --force-recreate keycloak

Con il re-import nascono **chiavi di realm nuove**: i token emessi prima smettono
di verificare — atteso, non un guasto. Un token per l'uno o per l'altro:

    ./dev-stack/token.sh                 # dev   (owner della stanza che tocca)
    ./dev-stack/token.sh --user viewer   # viewer (autenticato, senza membership)

Atteso: tutti verdi, **zero SKIP** (con `boto3` installato, gli smoke aprono il bucket e verificano da soli —
non si fidano della parola di StratiGraph Server).

## Tappa 3 — vedi gli effetti
- RustFS console → bucket `em-assets`: asset nominati col loro **sha256**, prefisso `studies/` coi container.
- Catalog → https://em.localhost:8443/catalog/studies (i due studi) · vista HDT `…/catalog/hdt/<hc2>`.
- IIIF → l'`info.json`/thumbnail stampati da `smoke_iiif` (Cantaloupe pesca da RustFS per sha256).
- Reader (dissemination) → https://em.localhost:8443/catalog/study/<id>/narrative (se lo studio ha una narrativa;
  public = senza token, restricted = 401).

## Tappa 4 — EMStudio come client (rete locale)
EMStudio non è nella stack: è il client. Serve una stanza da aprire, un token, e la CA fidata
(`./fcn-trust-ca.sh`, senza la quale il `wss://` non si apre e sembra un server muto).

**1 · la stanza** (da `~/Documents/GitHub/StratiGraph Server`):

    python3 dev-stack/seed_rooms.py     # crea `basilica-demo`: 6 US e 5 rapporti

Passa dalla porta del server (`POST /v1/rooms`, poi le operazioni): la stanza è nella casa dei documenti
(Postgres) e un client la vede appena il seme finisce, senza riavvii. Idempotente, e la stanza di lavoro
**non viene toccata** se ha già un contenuto: le altre due (`mostra`/`scavo`) sono fixture, questa è dove si
lavora. `--force` **riafferma** il seme per operazioni — nomi e rapporti tornano come il seme li scrive, ciò
che qualcuno ha aggiunto resta, la storia pure. `--room=<nome>` semina la sola stanza di lavoro sotto un
altro nome (per una prova; poi `POST /v1/rooms/<nome>/archive`).

**2 · il token** (700 caratteri, non si digita):

    ./dev-stack/token.sh | pbcopy       # negli appunti
    ./dev-stack/token.sh --claims       # cosa c'è dentro, quando una stanza risponde 4401

Dura un'ora: se la stanza smette di accettarlo, è la scadenza, non un guasto.

**3 · EMStudio** (da `~/Documents/GitHub/EMStudio/frontend`; `npm run serve` serve la `dist/`, quindi
`npm run build` almeno una volta):

    npm run build && npm run serve      # → http://localhost:4173

Nell'app, in quest'ordine:
- **Impostazioni ▸ Live sync** → `URL` = `https://em.localhost:8443/em` (la BASE, non l'endpoint: il
  `/v1/rooms/<stanza>/ws` lo compone `hub.ts`), `Stanza` = `basilica-demo`;
- poi **Mode ▾ → «In a room»** («In una stanza» con l'interfaccia in italiano) nella toolbar: **è lì che
  l'app chiede il token**. Il vecchio pulsante `#btn-mode-hub` («Mode ▸ Hub») esiste ancora ma sta in un menu
  nascosto. Non è un campo delle impostazioni di proposito — il token vive in memoria per la sessione e non
  viene scritto da nessuna parte (`hubToken` in `main.ts`).

**La stanza si salva da sola.** Nessuno deve premere «salva»: il server tiene il documento dopo 2 s di quiete,
ogni 64 operazioni, quando esce l'ultimo scrittore e allo spegnimento (misurato il 12 ottobre: `request_save`
→ revisione in 4 ms). Il client lo legge in `host_info.keeping` — `after_ops`, `after_quiet_seconds`,
`unsaved_ops`, `snapshot_at`, `at_risk`.

**4 · la prova senza mani** (da `EMStudio/frontend`, usa il client VERO — `SyncClient` e `roomUrl`):

    node scripts/check-room-live.mjs    # due client, un edit, la presenza: 18 check

Prende il token da `dev-stack/token.sh` e la CA da `~/caddy-em-root.crt` da sé. Per provare la porta diretta
invece di Caddy: `EM_HUB_BASE=http://localhost:8000 node scripts/check-room-live.mjs`.

**La prova del tavolo** (12 ottobre 2026): quattro client nella stessa stanza — due EMStudio, Blender,
StratiField — guidati da script, con un registro dei frame e delle latenze. Gli strumenti stanno in
`~/Documents/GitHub/_datasets/_tavolo/lavoro/` (`tavolo.py` è il client ws, `crea_stanza.py` la stanza
fatta per l'API) e restano lì: sono un **esempio** di come si prova la stanza da fuori, non una suite di
questo repo. La stanza la crea ora `seed_rooms.py --room=<nome>`; il token per la parte StratiField è quello
di `token.sh` (vedi CHEATSHEET §1-ter, «la prova senza mani»).

**5 · la geometria che scende (DP-76, metà che consuma)**: in Blender, pannello
**EM ▸ EMStudio Sync**, dentro una stanza → **«Materialize geometry from the
store»**. Atteso: i modelli che il grafo referenzia e che vivono nello store
compaiono in scena, legati alle loro epoche; premuto una seconda volta non
scarica e non duplica (l'oggetto porta già il suo `sha256`); un modello embargato
è **saltato con la ragione** e la scena resta intera.

Questa è la **controprova umana**. La prova ripetibile è headless, e sono due:

    cd ~/Documents/GitHub/EM-blender-tools
    .venv/bin/python -m pytest tests/test_room_materialise.py -q   # 13 · la funzione pura
    EM_ROOM_URL=http://localhost:8000 EM_ROOM_ID=basilica-demo \
      EM_ROOM_TOKEN=$(~/Documents/GitHub/stratigraph-server/dev-stack/token.sh) \
      EM_ASSET_SHA256=sha256:<un glb resident della stanza> \
      "/Applications/Blender 520.app/Contents/MacOS/Blender" --background \
        --python tests/blender_smoke_materialise.py                # 18 · L'OPERATORE

Il secondo **registra l'addon** (è la Blender vera, con l'estensione abilitata),
entra davvero nella stanza e preme il bottone: è l'unico posto dove
`EM_ep_belong_ob` esiste, quindi l'unico che può misurare che il legame
all'epoca viene **scritto** e non solo annunciato.

> **La libreria dell'addon è una COPIA.** EMtools spedisce s3dgraphy come wheel,
> che Blender installa nel site-packages dell'estensione: una Blender abilitata
> prima che la libreria crescesse `geometry_summary` ha una copia più vecchia
> **con la stessa stringa di versione** (misurato: 1.6.0.dev14 da entrambe le
> parti). Se il bottone dice «this Blender's s3dgraphy … predates DP-76's
> consuming half», la cura è ricostruire il wheel e reinstallarlo:
>
>     cd ~/Documents/GitHub/s3Dgraphy && .venv/bin/pip wheel . --no-deps \
>         -w ~/Documents/GitHub/EM-blender-tools/wheels/cp313
>     "/Applications/Blender 520.app/Contents/Resources/5.2/python/bin/python3.13" \
>         -m pip install --target "$HOME/Library/Application Support/Blender/5.2/extensions/.local/lib/python3.13/site-packages" \
>         --upgrade --no-deps --no-index \
>         ~/Documents/GitHub/EM-blender-tools/wheels/cp313/s3dgraphy-*.whl

**6 · il test forte, a due macchine**: un **secondo** EMStudio sull'altro Mac, `./fcn-up.sh <mac>.local` (il nome
Bonjour, mai un IP nudo → rompe il TLS della CA interna), stessa stanza `basilica-demo` → editi di qua, compare
di là in tempo reale. Sull'altro Mac va copiato e fidato anche `caddy-em-root.crt`.

## Note
- La ROOT `/` è vuota: apri percorsi veri (`/em/v1/health`, `/catalog/…`, `/iiif/…`).
- Certificato rifiutato dal browser → `./fcn-trust-ca.sh` (una volta; e dopo ogni `--wipe`).
- Altro computer: serve un **hostname** (Bonjour `.local` / hosts / dominio), mai un IP nudo (rompe il TLS
  della CA interna), e le due macchine devono vedersi in rete (hotspot che isola → travel-router / Tailscale).
- Spegni: `./fcn-down.sh` (o `--stop` / `--wipe` / `--colima`).
- **Persistenza:** i dati (studi, stanze, **asset e corpus** in RustFS, realm, CA) vivono su volumi *named* e
  **restano fra i riavvii** — `./fcn-down.sh` poi `./fcn-up.sh` (o un restart) li ritrova. **Solo `--wipe`
  cancella** tutto (e dopo serve `./fcn-trust-ca.sh` per la nuova CA). `--help` di `fcn-down`/`fcn-up` lo ricorda.
