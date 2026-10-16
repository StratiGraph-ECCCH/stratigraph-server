# Changelog — stratigraph-server

Le voci nuove in cima. Il numero di versione lo mette il bump, non questo file.

## Unreleased

### Aggiunto

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
