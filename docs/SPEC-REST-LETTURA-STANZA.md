# Leggere una stanza senza socket — specifica di due rotte

**Stato:** proposta del 12 ottobre 2026, **implementata il 17 ottobre** con l'Opzione A (cursore sull'arrivo). Dove la misura ha cambiato la proposta, c'è scritto «17 ott».
**Perché:** StratiField da smartphone non può tenere un websocket aperto (lo si prende e lo si rimette in tasca di continuo). Oggi può *scrivere* in una stanza via HTTP (`POST /v1/rooms/{id}/ops`) ma non può *rileggerla*: lo snapshot arriva solo all'apertura del socket, e `GET …/changes` restituisce un riassunto (conteggi, unità toccate), non le operazioni. Mancano due letture. Il resto della superficie REST c'è già.
**Come è stata fatta:** letto `app/main.py`, `app/ws.py`, `app/rooms.py`, `app/oplog.py`, `app/roomview.py`. Il server non è stato avviato: quello che segue dice cosa fa il codice, non cosa è stato misurato in esecuzione. Dove serve una misura, c'è scritto.

---

## 1 · Le due rotte

Stessa porta di `/who`, `/changes` e `/chat`: `_reader`, cioè *essere della stanza*, a qualunque ruolo. Non una seconda implementazione di «chi sei qui»: `_acting_role`, come per il socket e per `/ops`.

### 1.1 `GET /v1/rooms/{room_id}/document`

Restituisce il documento della stanza com'è adesso, lo stesso che il socket manda nella frame `snapshot`, più il cursore da cui ripartire.

```json
{
  "room_id": "…",
  "cursor": "k3f9:1842",
  "taken_at": "2026-10-12T09:41:07Z",
  "role": "editor",
  "can_write": true,
  "gc_watermark": null,
  "doc": { "…": "l'em.json della stanza" }
}
```

Parametri: `graph_id` (facoltativo) restituisce una sola sezione del contenitore, per il telefono che non ha bisogno di tutto. Senza, tutto lo studio.

Due scelte da tenere ferme.

**Il documento e il cursore escono dallo stesso istante.** Leggere il cursore, poi serializzare dopo un `await`, può restituire un documento più nuovo del cursore: il client ripartirebbe da un punto precedente allo stato che ha in mano (innocuo, perché le operazioni sono idempotenti) oppure, peggio nell'altro verso, da un punto successivo (si perderebbero operazioni). Quindi nel gestore si legge il cursore e si serializza il documento in un tratto sincrono, senza `await` in mezzo, e si restituisce una `Response` con i byte già pronti, non il modello Pydantic che FastAPI serializza dopo. Non serve il lock della stanza: la scrittura (`apply_from_connector`, `_keep`) è codice sincrono sotto lock, e un tratto sincrono non può cadere in mezzo. **Da misurare:** quanto dura la serializzazione sulla stanza più grande. Nel codice una scrittura di snapshot sulla stanza più grande è citata come 26 ms; la serializzazione per la rete va misurata a parte, e se è lunga, ferma il ciclo di tutti.

**Parità con il socket.** Il socket invia `room.document` così com'è, e la chat (messaggi volatili) sta dentro quel documento. La rotta fa lo stesso: chi è nella stanza vede quello che vedrebbe dal socket. Il confine della pubblicazione (`document_view`) non entra qui: è un'altra porta.

### 1.2 `GET /v1/rooms/{room_id}/ops?after=<cursore>&limit=<n>`

Le operazioni arrivate nella stanza dopo il cursore, in ordine di arrivo. È il replay del socket, offerto a chi non ha il socket.

```json
{
  "room_id": "…",
  "granted": true,
  "after": "k3f9:1842",
  "cursor": "k3f9:1861",
  "count": 19,
  "has_more": false,
  "operations": [
    { "graph_id": "…", "op": { "…": "stessa forma del corpo di una frame `op`" } }
  ]
}
```

Ogni voce ha la forma che il socket userebbe (`replay_entry` restituisce già `(corpo, graph_id)`), così un client ha un lettore solo. `limit` ha un default di 500 e un massimo uguale a `OPS_BATCH_MAX` (1000), lo stesso tetto di `/ops` in scrittura, per la stessa ragione: un batch lungo, qui, è una lettura lunga del file del registro. Se `has_more` è vero, il client riprende da `cursor` e richiama.

**Quando il server non può servire il cursore**, risponde 200 con `granted: false` e non manda operazioni:

```json
{
  "room_id": "…",
  "granted": false,
  "reason": "incomplete",
  "detail": "il registro di questa stanza arriva fin lì e il tuo cursore è più vecchio: una riproduzione parziale ti farebbe credere di essere allineato.",
  "resync": "/v1/rooms/{id}/document",
  "operations": []
}
```

I motivi sono quelli di `_replay_plan` (`unsafe`: il cursore è precedente alla compattazione; `incomplete`: il registro non arriva così indietro), più due: `unknown_cursor` (cursore malformato o di un'altra stanza) e `no_durable_log` (la stanza non ha un registro su disco e quindi non ha memoria oltre il processo). **Nella risposta di rifiuto non c'è nessun `cursor` nuovo, ed è voluto**: l'unico modo di ottenere un cursore nuovo è rileggere il documento. Un client che potesse avanzare il cursore senza aver ricevuto il documento si crederebbe allineato senza esserlo, che è il difetto che `ws.py` e `roomview.py` dichiarano più volte di voler evitare.

Senza `after` la rotta risponde con lo stesso `granted: false` (motivo `no_cursor`) e il rimando a `/document`: non è un errore, è la prima volta che qualcuno guarda.

### 1.3 Annuncio in `/v1/health`

`GET /v1/health` pubblica già `capabilities`, «così un client non scopre un 501 provandolo». Si aggiungono `room_document_read` e `room_ops_feed`, così StratiField sa se questo nodo le ha prima di scegliere la modalità smartphone.

---

## 2 · Il cursore: il punto delicato

### Cosa fa oggi il codice

Il replay del socket (`Room.replay_since`), `Journal.since` e `changes_since` filtrano tutti sul campo `ts` **dell'operazione**: `str(op.get("ts")) > cursore`. Quel `ts` non è l'istante di arrivo al server: lo scrive il client, perché è il timbro con cui i campi vincono o perdono nel CRDT (ogni client mette un timbro per gesto di salvataggio; il server aggiunge `ts` solo se manca: `entry.setdefault("ts", now_iso())` in `apply_from_connector`). L'istante di arrivo c'è, ed è registrato (`journal.append(op, at=now_iso())`, il commento dice «`at` è l'istante del SERVER, e non è il `ts` dell'operazione»), ma `Journal.read()` restituisce solo `voce["op"]` e lo butta.

### Perché conta proprio per il telefono

Una persona lavora offline dalle 10:00 alle 11:00, e le sue operazioni portano `ts` fra le 10:00 e le 11:00. Alle 11:05 il telefono riconnette e le consegna. Nel frattempo il desktop ha letto il documento alle 11:00 e tiene un cursore che vale «10:58». Alle 11:06 il desktop chiede «cosa è arrivato dopo 10:58»: vede solo le operazioni del telefono con `ts` oltre le 10:58. Quelle delle 10:10 non le vedrà mai, anche se sono arrivate dopo che aveva guardato. Il cursore su `ts` dà ragione al lavoro in tempo reale e torto al lavoro di campo tornato dal sommerso, cioè al caso per cui StratiField esiste. Nel socket vale lo stesso, ma lì un client che resta connesso riceve comunque le operazioni in diretta; la perdita si verifica per chi riconnette con un cursore.

**Da verificare, non ancora controllato:** quale valore usano oggi i client come `since` alla riconnessione (l'ultimo `ts` visto? l'istante della lettura?). Se è l'ultimo `ts` visto, il difetto è raggiungibile adesso; se è un'altra cosa, va letto cosa. Lo dico perché la conseguenza sul socket cambia, non quella sulle due rotte nuove.

**17 ott, letto nel codice dei client (sola lettura).** EMStudio (web e desktop, stesso `frontend/src/main.ts`) rientra con `since` = il `ts` dell'ultima operazione ricevuta o confermata (`hubBase = String(op.ts ?? hubBase …)`) e ri-timbra solo nel caso `resync` di `planRejoin` (`hub.ts`). EMtools rientra con `SESSION.last_applied` = il `ts` massimo visto (`room_session.py`) e ri-timbra solo sul resync. StratiField non manda `since` (apre il socket senza) e consegna la coda del ponte, anche da `POST /ops`, con il `ts` del momento della dettatura, senza ri-timbrare. **Quindi il difetto è raggiungibile oggi anche sul socket**: EMStudio o EMtools che rientrano dopo una consegna in ritardo di StratiField non la ricevono nel replay. Il socket non è stato toccato.

### Proposta per le due rotte nuove

Un cursore basato sull'**arrivo al server**, opaco per il client:

```
cursore = "<epoca>:<seq>"
```

`seq` è un intero crescente per stanza, scritto in ogni riga del registro da qui in avanti. `epoca` è una sigla breve scritta una volta all'apertura del registro: se il registro viene buttato e ricreato (`Journal.forget`, o una stanza con lo stesso nome ricostruita), `seq` riparte da zero e senza epoca un vecchio cursore sembrerebbe valido. È il difetto che `rooms.py` annota già per `Room.revision` («una revisione non è un orologio… stesso nome, revisione che riparte da zero»).

Costa questo, e va detto:

1. `Journal.append` aggiunge `"seq"` alla riga; `seq` si recupera all'apertura leggendo l'ultima riga.
2. Una riga-marcatore `{"epoca": "…"}` come quella di `compacted_upto`. **`Journal.read()` oggi conta come illeggibile ogni riga senza `"op"`** (salta solo quelle con `compacted_upto`): un marcatore nuovo, senza un `if` che lo salti, finirebbe nel contatore `unreadable` e in `/health` come registro rovinato. E `_prune` deve salvarlo, come salva il marcatore di compattazione.
3. Il marcatore di compattazione porta anche `seq` al momento in cui è stato scritto. La regola `unsafe` diventa: il cursore è precedente a quel `seq`. **È una traduzione della regola di `_replay_plan`, non una derivazione**: va confermata con chi conosce il contratto di s3Dgraphy sulla compattazione prima di fidarsene.
   **17 ott: la regola implementata è un'altra, e il perché è misurato.** «Il cursore è precedente a una compattazione» rifiuterebbe il feed a ogni `POST /ops` con un desktop seduto, perché `apply_from_connector` compatta a ogni consegna quando c'è un watermark. Il feed sul numero d'arrivo è completo anche dopo una compattazione (la compattazione non taglia il registro; la potatura sì, ed è `incomplete`). Il caso pericoloso è un'operazione **arrivata dopo una compattazione con un `ts` più vecchio del punto compattato** — il telefono tornato dal sommerso dopo la pulizia, che viola la precondizione di `s3dgraphy.api.compact` — e `unsafe` rifiuta quello. Da confermare con chi mantiene il contratto; la regola è in `roomview.operations_after`.
4. Le righe già scritte, senza `seq`, restano leggibili. Un cursore che cade prima della prima riga con `seq` riceve `incomplete` con `horizon: began` («prima di qui questo server non sa»), la stessa distinzione `pruned`/`began` che `changes_since` fa già.
5. `Journal.read_rows()` nuovo, che restituisce le righe intere (`at`, `seq`, `op`) senza toccare `read()`, che altri usano.

### Alternativa, e perché non la consiglio

Tenere il cursore su `ts` e riusare `_replay_plan` com'è. È un lavoro di mezza giornata e c'è una sola logica di rifiuto invece di due. Ma consegna al telefono esattamente il difetto sopra. Se si sceglie questa strada, il documento va corretto con la frase «le operazioni offline consegnate in ritardo possono sfuggire a chi ha già un cursore più recente», e StratiField deve rileggere il documento intero a ogni ripresa. Si perde quasi tutto il vantaggio della rotta `/ops`.

**La decisione è tua:** cursore sull'arrivo (consigliato) o su `ts`. *(17 ott: A, il default della MICRO; E.D. non ha scritto una scelta diversa.)* Le due rotte sono scritte per l'opaco `cursore`, quindi la forma delle risposte non cambia; cambia solo cosa c'è dietro.

---

## 3 · Come lo usa StratiField

In modalità smartphone:

1. All'apertura, `GET /document`: tiene `doc` e `cursor`.
2. Scrive con `POST /ops`. È già idempotente e il rifiuto di un'operazione vecchia o già applicata torna dentro `refused` con un 200, quindi un reinvio dopo un timeout è sicuro. La coda locale durevole che il bridge di StratiField ha già, consegna in ordine e si ferma al primo errore, va bene com'è.
3. **Il cursore non avanza con le proprie scritture.** Le operazioni che il telefono ha appena inviato tornano nel feed insieme a quelle degli altri, e il client le riconosce perché sono idempotenti. Un cursore spostato in avanti dopo un `/ops` salterebbe quello che altri hanno scritto nel frattempo.
4. Alla ripresa («lo riprendo dalla tasca»), `GET /ops?after=cursor`: applica, e il `cursor` della risposta diventa il nuovo.
5. Se `granted: false`: `GET /document`, poi ri-applica sopra la coda locale non ancora confermata. Funziona perché le operazioni scritte dal client portano i timbri per campo: la fusione è per campo e il perdente viene riportato (`loser_value`), non scartato.

In modalità desktop e tablet resta il socket. Stessa stanza, due porte.

---

## 4 · Dove va il codice

| cosa | dove |
|---|---|
| le due rotte | `app/main.py`, accanto a `room_changes` (riga ~3930), con `_reader` |
| la lettura, senza scrivere | `app/roomview.py`, una funzione nuova (il modulo dichiara di non scrivere e di non tenere indici) |
| `seq`, epoca, `read_rows()`, marcatori | `app/oplog.py` (`append`, `read`, `_prune`, `mark_compacted`) |
| `compacted_upto` col `seq` | `app/rooms.py` (`snapshot`) e `oplog.py` (`mark_compacted`) |
| `capabilities` | `/v1/health` in `main.py` |
| tabella delle rotte | `README.md`, la tabella dei `/v1/…` (riga ~78) |

OpenAPI si genera da solo: le due rotte compaiono in `/docs` e in `/openapi.json` senza altro lavoro.

## 5 · Prove da scrivere

Nello stile del repo (i nomi dei file di test descrivono un comportamento, `tests/test_ops_endpoint.py` è il modello per le rotte autenticate):

1. Un membro in sola lettura ottiene il documento; chi non è nella stanza ottiene 403.
2. Il `cursor` del documento, passato a `/ops?after=`, restituisce zero operazioni; dopo una scrittura via `/ops`, una.
3. **Il caso del telefono:** A scrive operazioni con `ts` vecchio *dopo* che B ha preso il cursore; B le riceve comunque dal feed. Con un cursore su `ts` questa prova fallisce, ed è la prova che giustifica la scelta.
4. Cursore più vecchio della potatura (`KEEP_OPS` abbassato per il test): `granted: false`, `incomplete`, nessuna operazione, nessun `cursor` nella risposta.
5. Cursore precedente a una compattazione (`request_save`): `unsafe`.
6. Stanza ricostruita, registro buttato: il vecchio cursore dà `unknown_cursor` e non un feed vuoto.
7. Registro con righe senza `seq` (stanze di prima): lette senza errori, `unreadable` resta zero, il cursore che cade lì dà `incomplete` con `horizon: began`.
8. `has_more` e `limit`: il feed in due pagine coincide con il feed in una.
9. Stanza senza registro durevole: `no_durable_log`.
10. `/v1/health` annuncia le due capacità.

## 6 · Fuori da questa specifica, stessa famiglia

* **`POST /ops` non restituisce i conflitti per campo.** `OpsOut` ha `applied`, `refused`, `kept`; la decisione per campo con `loser_value` esiste in s3Dgraphy e viene calcolata, ma «non lascia mai il processo» (`docs/SYNC-FIELD-TO-CLOUD.md` §1.4). Al telefono servirebbe vederla. Un campo `conflicts` facoltativo nella risposta è un cambio piccolo e compatibile.
* **Il commento in `main.py` intorno a riga 3760** dice che «la quinta risposta non c'è» (il cursore sul registro); `/changes` esiste ed è quella risposta. Va aggiornato.
* **Il cursore del socket** (§2): una volta chiarito cosa mandano i client come `since`, valutare se allinearlo a quello nuovo in una versione successiva del filo.
* **Un modo per svegliare il telefono** (notifica o SSE) non c'è e non è previsto qui: alla ripresa si fa pull, che per questo uso basta.
