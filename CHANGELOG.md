# Changelog — stratigraph-server

Le voci nuove in cima. Il numero di versione lo mette il bump, non questo file.

## Unreleased

### Cambiato

- **MinIO esce, RustFS entra** (18 ott 2026). MinIO community è deprecata; la
  prova del 17 ottobre aveva misurato RustFS 1.0.2 con smoke e suite invariati.
  - **Dev stack:** i servizi `minio` / `minio-init` diventano `rustfs` /
    `rustfs-init` (`rustfs/rustfs:1.0.2`, pinnata col digest; il bucket con una
    `PUT` SigV4, senza `mc`), volume nuovo `rustfs_data`, `Caddyfile.dev`
    `/assets/*` → `rustfs:9000`. In `.env.dev` le chiavi sono `RUSTFS_*`; server,
    catalogo e chatbot ricevono tutti `EM_ASSET_S3_*`. La pila di prova
    (`docker-compose.rustfs.yml`, `README-RUSTFS.md`) è tolta: ha fatto il suo.
  - **Server:** il client è `boto3` (`app/s3client.py`), non più `minio-py`;
    extra `[s3]` = `boto3>=1.34`. Via gli alias `Minio*`. Si leggono solo
    `EM_ASSET_S3_*` (e `EM_ASSET_S3_CONSOLE_URL`). Il controllo di salute del
    nodo si chiama `s3` e bussa a `<endpoint>/health`.
  - **Ovunque, lo stesso giorno:** il ruolo di produzione (`heriverse-ansible`),
    Heriverse-Docker, il catalogo, il chatbot, s3Dgraphy (`s3_backend`,
    `ingest_s3_resource`), EM-tools ed EMStudio. Gli asset della pila di
    sviluppo sono stati copiati e verificati (9672 oggetti, 5,77 GB); i nomi
    `MINIO_*` non sono più né letti né riconosciuti.

### Aggiunto

- **Quello che il nodo fa, scritto** (E.D. 19 nov 2026, notte). Delle 84 rotte
  `/v1` dello schema OpenAPI, 23 non comparivano in nessun documento.
  - **`docs/NODE-ADMIN-API.md`**: l'API della console — chi può bussare
    (`whoami` che non rifiuta, il `403` con la sua frase), persone per ORCID,
    password da campo, togliere una persona, la stanza che nessuno può più
    gestire, il registro, la chiave del nodo e la lista di fiducia, il
    pacchetto di persone firmato (export, preview che non cambia niente,
    import), il cestino. **`docs/VOCABULARIES-API.md`**: i due lati del
    gestore dei vocabolari, con la fascia C che non esce mai. Il `restore` di
    una stanza in `docs/REST-API.md`, accanto al cestino. Ogni esempio eseguito
    sullo stack di sviluppo il 18 novembre; le abbreviazioni dichiarate.
  - **`tests/test_docs_cover_routes.py`**: una rotta `/v1` che non compare in
    `docs/` (né nella prosa del README: la sua tabella non conta, è già tenuta
    uguale al codice) fa rosso. Eccezioni dichiarate nel test, oggi nessuna.
  - **Tre operationId doppi tolti**: `upload_status`, `get_asset` e
    `download_asset` erano un solo `api_route` per GET e HEAD; ora due
    registrazioni con `operation_id` espliciti, uguali a quelli che lo schema
    già pubblicava. FastAPI non avvisa più; il test lo controlla.
  - **Sphinx e Read the Docs** come in s3Dgraphy e stratigraph-templates:
    `docs/conf.py` (MyST, i documenti non riscritti; i link a file fuori da
    `docs/` mandati su GitHub da una trasformazione), `docs/requirements.txt`,
    `.readthedocs.yaml` (con `fail_on_warning: true`), `docs/index.md` come
    porta per tre lettori — il terzo, chi lavora in una stanza, dichiarato
    ancora senza manuale. `sphinx-build -W docs docs/_build` passa.

- **Il nodo dentro OpenShift** (E.D. 19 nov 2026, notte). `deploy/openshift/`:
  kustomize con `base/` (Deployment con init container di preflight, Service,
  Route sotto `/em` con `rewrite-target: /` come `handle_path` di Caddy,
  ConfigMap, Secret vuoto coi nomi delle chiavi, PVC), tre componenti «ve lo
  diamo noi» (`postgres-nostro`, `s3-nostro`, `keycloak-nostro` solo per prove)
  e due overlay (`casa`: tutto della casa; `portatile`: tutto nostro).
  `deploy/openshift/README.md` classifica le 101 variabili lette da `app/` più
  le due di s3Dgraphy in obbligatorie / facoltative col default / segrete;
  `ASKING-THE-HOUSE.md` è la pagina per gli amministratori.
  - **`app/preflight.py`** (`python -m app.preflight`): rifiuta con una frase
    per variabile un ambiente senza tipo di nodo, indirizzo pubblico https,
    OIDC, `EM_SNAPSHOT_DIR` scrivibile e store degli asset. Lo chiama solo il
    manifesto: il server, altrove, parte ancora senza configurazione.
  - **Le sonde chiedono tutte `/health`**: misurato, `/v1/node` risponde 200
    anche lui ma interroga i vicini (6 s se non rispondono).
  - `tests/test_preflight.py` 28: ogni obbligatoria tolta da sola è rifiutata
    per nome; ogni variabile letta dal codice è classificata nel README.

- **Il nodo serve i vocabolari che ha** (MICRO-PL02 «gestore dei vocabolari»,
  residuo (1) di MICRO-U, E.D. 18 nov 2026). La cartella è quella di s3Dgraphy,
  `vocab_dir()` (`EM_VOCABULARIES_DIR`, ora in `docs/DEPLOYMENT.md`).
  - **I pacchetti, per il gestore di un'altra macchina:**
    `GET /v1/vocabularies/catalog.json` nel formato di `vocab_catalog`
    (`{packages: [{id, version, snapshot_date, title, languages, license, tier,
    attribution, serves, sha256, url}]}`, `url` relativo: `<id>.emvocab.zip`,
    `?version=` se non è la più nuova) e `GET /v1/vocabularies/<id>.emvocab.zip`
    ricostruito dalla cartella (`s3dgraphy.vocabularies.vocab_package_bytes`;
    con uno s3Dgraphy che non l'ha, come il dev121 del pin, lo stesso zip fatto
    qui, leggendo sia `<id>/manifest.json` sia `<id>/<versione>/manifest.json`).
  - **Le letture del ponte di EMStudio** (`tools/em_vocab.py`) sul nodo, stesse
    forme: `GET /v1/vocab/installed`, `search`, `concepts`, `catalog`, `updates`
    — la pagina web funziona senza il ponte. `catalog`/`updates` vanno solo al
    catalogo centrale (un altro `url` è 400: una rotta pubblica non fa da proxy);
    `installed` non dice percorsi del disco del nodo.
  - **La fascia C non esce mai:** né lo stub né la copia scaricata sul nodo
    compaiono nel catalogo, in `installed`, in `search`, in `concepts`; lo zip
    risponde 403 con la ragione. Le letture sono pubbliche (un pacchetto A/B è
    fatto per viaggiare).
  - **Le scritture** del ponte (`POST /v1/vocab/install`, `remove`,
    `fetch-local`) stanno in `v1` (token) e chiedono la capacità di OPERATORE,
    lo stesso controllo di `/v1/admin/*`.
  - `app/vocabularies.py` (rotte dichiarate lì e montate da `main` su `v1_public`
    e `v1`, così `/docs` e la tabella del README le vedono), 7 test
    (`tests/test_vocabularies.py`).

- **Chi tiene un `.blend`: la prenotazione nella stanza** (MICRO-BLEND-OFFICINA-2,
  decisioni di E.D. D7/D8, 31 ott 2026). Verbo `hold` (`take` / `renew` /
  `release`, `force` per owner e admin) su una chiave = il percorso del `.blend`
  relativo al progetto; frame `holds` a tutti a ogni cambio (e alla porta, come
  quarto frame, solo se qualcuno tiene qualcosa); `hold_refused` con la frase e
  chi lo tiene. Scade 15 min dopo l'ultimo `take`/`renew` (non a ogni frame),
  una disconnessione non libera; un lettore vede ma non prende. In RAM come la
  presenza: un riavvio libera tutto, il `renew` successivo della stessa persona
  la riprende. Annunciato in `/v1/health` (`room_holds`) e in `host_info`
  (`holds`, `holds_ttl_seconds`). `app/holds.py`, `tests/test_holds.py`.

- **I gruppi chiusi viaggiano nelle stanze** (MICRO «globo, interazione» p.5,
  decisione di E.D., 23 ott 2026: tutto condiviso). Il frame `layout` porta
  anche `folded: {id: chiuso?}` (può portare solo quello): un gruppo del grafo
  va in `graphs.<id>.layout.folded_groups`, il gruppo che la vista di EMStudio
  fa per i paradati sciolti di un'unità (`implicit-pd:<unità>`, chiuso se
  nessuno lo apre) in `layout.open_implicit`. Si conserva come le posizioni
  (istantanea, REST, disco), passa agli altri, un id che il grafo non ha è
  scartato e detto, un lettore riceve `denied`. **Aprire un gruppo lo apre a
  tutti.** Come `moved_from` per le posizioni, la stanza ricorda in
  `layout.folded_from` i gruppi com'erano prima del primo cambiamento: chi entra
  dopo calcola la vista della Matrix su quella base, poi chiude e apre come gli
  altri (un layout intero la azzera). Detto in `host_info.layout_folded` e in
  `capabilities.room_layout_folded`. 10 test (`test_i_gruppi_chiusi_della_stanza.py`).

- **Le posizioni viaggiano nelle stanze** (MICRO «stanza, posizioni condivise»,
  decisioni di E.D., 23 ott 2026: anche quelle della Matrix sono della stanza).
  Prima il relay applicava le cinque operazioni del grafo e lasciava cadere un
  frame che non conosceva.
  - Frame `layout` sul socket, `{space, positions, whole?, swimlanes?, canvas?}`
    con il grafo nella busta: `space` vuoto è la Matrix (`layout.positions`), un
    id di gruppo è il suo interno (`layout.group_spaces`); `null` toglie una
    voce; `whole` sostituisce lo spazio («Ricalcola layout»).
  - Autorizzato come i verbi che scrivono (un lettore riceve `denied`),
    inoltrato agli altri con `author` e `connection_id`, **senza** passare da
    `em.apply_op`: vince l'ultimo arrivato. Tenuto in `graphs.<id>.layout` del
    documento della stanza, conta come lavoro da salvare (`unsaved`), quindi
    arriva nell'istantanea del JOIN (anche prima di un replay), nella lettura
    REST e sul disco. Non va nel registro delle operazioni.
  - `layout.moved_from`: da dove sono partiti i nodi della Matrix mossi dopo
    l'ultimo layout intero (`null` = non avevano posto). Chi entra dopo ci
    ricostruisce la base su cui gli altri hanno calcolato la loro vista, e poi
    sposta quei nodi; un layout intero lo azzera.
  - Limiti: 640 KB per frame (`layout_too_large`), 240 frame in 10 s per
    connessione (`layout_too_fast`), solo nodi del grafo (le voci sconosciute
    scartate e dette in `layout_result.dropped`; un gruppo che non c'è è
    `unknown_space`).
  - Dichiarato: `host_info.layout` (con `layout_limits`) e `/v1/health`
    `capabilities.room_layout`, `limits.layout_*`.

- **Cancellare una stanza, e tenere i suoi asset** (MICRO «spazio 3D 2»,
  Parte 6, decisioni di E.D., 16 ott 2026). L'API del nodo non aveva nessuna
  operazione per cancellare una stanza.
  - `DELETE /v1/rooms/{id}` con corpo `{"confirm": "<id>"}`: al **proprietario**
    della stanza e all'**operatore** del nodo (`app/operators.py`), a nessun
    altro — un admin della stanza è 403. Conferma assente o diversa → 400;
    stanza che non c'è → 404; qualcuno collegato → 409 (la sua sessione,
    uscendo, riscriverebbe il documento). La stanza si trova dai fatti DUREVOLI
    (registro, contenitore), mai aprendola: una copia vuota in memoria lasciata
    da una lettura non la rende cancellabile e non resta.
  - Toglie: la copia di lavoro (senza salvarla), il contenitore con **tutte**
    le sue revisioni in Postgres (un contenitore che un'altra stanza nomina
    resta, ed è detto), l'oplog, il record del registro, l'ACL (proprietario,
    membri, grant ai gruppi), gli inviti, gli upload riprendibili in sospeso,
    il registro dei `.blend` della stanza. I blob `.blend` restano.
  - **Gli asset non si cancellano mai con la stanza.** Uno che nessun'altra
    stanza cita (grafo) o tiene (upload), e che il corpus residente non
    documenta, diventa **orfano**: resta nello store, e il suo record in
    `asset_homes` porta `orphan: {orphaned_at, origin_room, deleted_by,
    media_type, size}`. Se la stanza era la casa, la casa passa alla prossima
    stanza che tiene i byte.
  - `GET /v1/admin/assets/orphans` (operatore; filtri `type`, `since`,
    `until`): gli orfani, ricontrollati a ogni chiamata — uno che un grafo cita
    di nuovo, ricaricato in una stanza, documentato nel corpus o sparito dallo
    store non è elencato.
  - `DELETE /v1/admin/assets/{ref}` resta com'era (409 su un asset citato da
    una stanza o dal corpus) e ora toglie anche il record dell'asset: un orfano
    cancellato esce dall'elenco.
  - Un orfano si **riusa** caricando gli stessi byte in una stanza: lo store
    non li riscrive (`created: false`), la stanza diventa la sua casa e il segno
    d'orfano cade. Caricato «in» un nome che non è una stanza resta orfano.
  - `GET`/`HEAD /v1/admin/assets/{ref}` («Scarica» nella lista degli orfani
    di EMStudio): l'operatore scarica un asset senza passare da nessuna stanza
    — un orfano non ne ha una che possa servirlo. Nessuna stanza letta, aperta
    o creata; i byte in streaming a pezzi (`read_range`), `Content-Type` il
    tipo registrato (altrimenti `application/octet-stream`), `Content-Length`,
    `ETag` il riferimento, `Content-Disposition: attachment;
    filename="<hex>.<ext>"`. 400 riferimento storto, 403 non operatore, 404
    non nello store.
  - `delete(room_id)` opzionale sugli store per stanza (snapshot ×3, registro,
    ACL, inviti, registro `.blend`), `UploadSessions.for_room`.
  - `tests/test_cancellare_una_stanza.py` (23 prove); `test_api.py` e
    `test_rooms_register.py` aggiornati: la cancellazione adesso esiste.

### Corretto

- **Una lettura su una stanza che non c'è non apre una copia di lavoro**
  (MICRO-HEAD-NON-APRE-LA-STANZA, 16 ott 2026). Misurato il 15 ottobre
  (s3Dgraphy, room-import, fase C): un `HEAD …/rooms/<id>/asset/sha256:…` su una
  stanza non ancora creata faceva costruire e TENERE al nodo una copia vuota in
  memoria; il `POST /v1/rooms` successivo scriveva le sezioni nello store, ma la
  semina veniva rifiutata («the graph … is not in this study») e alla chiusura la
  copia vuota era salvata sopra le sezioni.
  - `RoomRegistry.exists` / `RoomRegistry.find` (`app/rooms.py`): una lettura
    trova la stanza se è viva, dichiarata o ha il suo contenitore nello store
    (stanza di prima del registro), altrimenti `None`, senza aprire né tenere
    niente.
  - Le letture rispondono **404** su una stanza che non c'è: `GET`/`HEAD` di
    `…/asset/{ref}`, `GET …/asset-home/{ref}`, il manifest IIIF, e ogni
    `GET`/`HEAD` che passa da `_acting_role` (`GET /v1/rooms/{id}`, `…/members`,
    `…/blend-backups`, …). Prima rispondevano 200/403 e aprivano la stanza;
    `GET /v1/rooms/{id}` scriveva anche l'ACL (il bootstrap del proprietario).
    Le scritture (sessione WebSocket, `PUT` dei membri, operazioni) aprono la
    stanza come prima.
  - Uno store che non risponde alla domanda «esiste?» dà 503, non 404 né i byte.
  - `POST /v1/rooms` che scrive le sezioni lascia andare una copia aperta prima
    della nascita, se nessuno è collegato e non ha lavoro non salvato.
  - **Cambia per chi chiama**: leggere un asset attraverso il nome di una stanza
    mai creata ora è 404 (prima 200, «caso (i)»). Gli smoke `smoke.py` e
    `smoke_embargo_viewer.py` dichiarano la loro stanza prima di leggerla;
    `smoke_corpus_resident.py` si aspetta 404 per la stanza inventata.
