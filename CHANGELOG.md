# Changelog — stratigraph-server

Le voci nuove in cima. Il numero di versione lo mette il bump, non questo file.

## Unreleased

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
