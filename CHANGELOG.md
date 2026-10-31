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
