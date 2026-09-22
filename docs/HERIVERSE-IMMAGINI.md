# Le due immagini di Heriverse: cosa manca perché siano pubblicabili

**A chi serve questa pagina.** A chi deve decidere, in una riunione, se le
immagini di Heriverse possono andare su un registry pubblico insieme alle
altre — senza avere i repository aperti davanti. Ogni numero qui dentro è
misurato il 22 settembre 2026 sui checkout e sulla rete, e accanto c'è il
comando: se qualcosa non regge, si rimisura.

**Cosa NON è questa pagina.** Non è una proposta di riparazione, e non tocca
niente: i due `dockerfile` sono di 3DR, la pipeline che li costruisce è di 3DR,
e le scelte che seguono sono loro. Qui c'è l'elenco delle cose che devono
essere vere prima, non il modo di renderle vere.

---

## Il contesto in due righe

PSNC (WP4) chiede di poter **tirare le immagini del progetto da un registry
pubblico e specchiarle** sul proprio, per farle girare su OpenShift. Per le
quattro immagini nostre — `stratigraph-server`, `stratigraph-stratifield`,
`stratigraph-catalog`, `emstudio` — il lavoro è fatto: partono con un UID
arbitrario, portano la licenza dentro, si costruiscono multi-arch e si
verificano con una tirata anonima.

Per le due di Heriverse no, e i motivi sono quattro. Tre sono tecnici e uno è
una domanda a cui solo 3DR può rispondere.

---

## Dove stanno le cose

| | |
|---|---|
| `heriverse` | `StratiGraph-ECCCH/Heriverse` · file `dockerfile` (minuscolo) · ultimo commit 12 set 2026 |
| `heriverse-server` | `StratiGraph-ECCCH/Heriverse-Server` · file `dockerfile` · ultimo commit 24 lug 2026, Romano Aloisi |
| come si costruiscono oggi | `.gitlab-ci.yml` in entrambi: build su `main`, push su `$CI_REGISTRY_IMAGE` con `:<sha>` e `:latest` |
| dove finiscono oggi | `git.3dresearch.it:5050/cnr-h2iosc/heriverse/heriverse-wapp:latest`<br>`git.3dresearch.it:5050/stratigraph/heriverse-server:latest` |
| chi può tirarle | nessuno senza credenziali: `https://git.3dresearch.it:5050/v2/` → **401** |

La produzione tira da lì oggi, e **questo non si tocca**: spostare la
produzione su un registry pubblico è una decisione separata.

---

## 1 · Girano da root, e OpenShift le rifiuta prima di guardarle

Misurato: `grep -c '^USER' dockerfile` → **0** in tutti e due. Nessuna riga
`USER`, quindi il processo è root.

Perché è dirimente e non un dettaglio di igiene: la `SecurityContextConstraint`
predefinita di OpenShift (`restricted-v2`) assegna al pod un **UID casuale**
preso dall'intervallo del progetto e **rifiuta** un container che chiede di
essere root. Non è un avvertimento in un log: il pod non parte.

È lo stesso lavoro già fatto sulle quattro immagini nostre, e sta in due
righe — proprietà al gruppo 0 con i permessi di gruppo uguali a quelli utente
(`chown -R <uid>:0` + `chmod -R g=u`), e `USER` scritto come **numero** perché
Kubernetes valuta `runAsNonRoot` sull'UID e un nome non lo sa verificare.

C'è un dettaglio in più per `heriverse`: gira **pm2**
(`CMD ["pm2-runtime", "ecosystem.config.js"]`), che vuole una `HOME`
scrivibile per la propria directory di stato. Con un UID che non esiste nel
`/etc/passwd` dell'immagine, `HOME` diventa `/` e non è scrivibile: è
esattamente il guasto che abbiamo incontrato sulle nostre e che il `USER` fisso
teneva nascosto.

`heriverse-server` espone la **3000**, `heriverse` non dichiara nessuna
`EXPOSE`. Entrambe sopra la 1024, quindi da quel lato non c'è problema.

---

## 2 · Il build di `heriverse` non è riproducibile

`Heriverse/dockerfile` righe 10 e 13 — il build **clona due repository interi**
al momento in cui gira:

```
RUN git clone --depth 1 https://github.com/phoenixbf/aton.git .
RUN git clone --depth 1 https://git.3dresearch.it/cnr-h2iosc/auth-flares.git /tmp/auth-flare
```

**Correzione a una versione precedente di questo documento**, che diceva che il
secondo è privato e che quindi l'immagine non è costruibile fuori da 3DR.
**Falso, e misurato male**: avevo interrogato la pagina web invece
dell'operazione che il build fa davvero. Il clone anonimo riesce —

```
GIT_TERMINAL_PROMPT=0 git ls-remote https://git.3dresearch.it/cnr-h2iosc/auth-flares.git
c5124ae…  HEAD
```

— quindi da questo lato non c'è nessun ostacolo.

Il problema vero è un altro, ed è peggiore perché è silenzioso: `--depth 1`
senza `--branch <tag>` prende **la punta di quel momento**. Due build dello
stesso commit di Heriverse, a due settimane di distanza, producono due immagini
diverse, entrambe etichettate con lo stesso `$CI_COMMIT_SHORT_SHA`. Chi
specchia l'immagine non ha modo di sapere quale ATON c'è dentro, e chi trova un
guasto non ha modo di ricostruire l'immagine che ce l'aveva.

Si chiude pinnando i due cloni a un tag o a un commit, esattamente come le
nostre immagini pinnano s3Dgraphy — che lì è una `==` senza default, e il
Dockerfile **rifiuta** di costruire se nessuno ha detto quale.

C'è anche una dipendenza di disponibilità: il build ha bisogno che
`git.3dresearch.it` sia in piedi. Su una Action pubblica è una terza macchina
fra il sorgente e l'immagine.

---

## 3 · La licenza di `heriverse-server` non è dichiarata

| | `heriverse` | `heriverse-server` |
|---|---|---|
| file `LICENSE` | **c'è** — GNU GPL v3, 29 June 2007 | **assente** |
| `package.json` → `license` | (non è un progetto npm) | `"ISC"` |

`ISC` è anche ciò che `npm init` scrive da solo quando nessuno risponde alla
domanda, e il `package.json` porta `"version": "1.0.0"`, che è l'altro valore
predefinito di quel comando. Quindi non si può distinguere **una scelta** da
**un default**, e la differenza conta: pubblicare un'immagine è distribuire, e
la distribuzione è l'atto a cui gli obblighi di una licenza si attaccano.

Va **confermato da chi ha scritto quel codice** (ultimo commit: Romano Aloisi,
24 luglio 2026). Nessuno di noi può scegliere al posto suo, e questa pagina non
propone niente.

E c'è un fatto in più da tenere presente per `heriverse`: l'immagine
**contiene ATON per intero** (il clone della riga 10), e ATON è
**GPL-3.0** — misurato su `api.github.com/repos/phoenixbf/aton`. Coerente con
la GPL-3 di Heriverse; va detto perché chi pubblica un'immagine ne diventa il
manutentore apparente, e qui dentro c'è il software di un altro.

---

## 4 · Il namespace, e perché l'ordine conta

Se e quando queste due immagini andranno su GHCR, vanno sotto
`ghcr.io/stratigraph-eccch/` come le altre del progetto.

**Un pacchetto GHCR non segue il rinomino o il trasferimento del suo
repository**: nasce nel namespace del proprietario di allora, e cambiarlo vuol
dire cancellarlo e ripubblicarlo — cioè rompere chiunque l'abbia già
specchiato. PSNC specchia: è il caso peggiore. Quindi prima si decide dove
stanno i repository, poi si pubblica; mai il contrario.

E una trappola che vale per ogni pacchetto nuovo: **al primo push GHCR crea il
pacchetto privato**. Il workflow diventa verde, il push è riuscito davvero, e
nessuno può tirare niente. Renderlo pubblico è un passo a mano, per pacchetto,
nell'interfaccia di GitHub — misurato: non esiste nessuna rotta REST che lo
faccia.

---

## La lista, in ordine

1. **3DR conferma la licenza di `heriverse-server`** e, se è una scelta, mette
   il file `LICENSE` nel repository.
2. **3DR pinna i due cloni** nel `dockerfile` di `heriverse` (un tag o un
   commit per ATON, uno per `auth-flares`).
3. **3DR mette le due immagini in condizione di girare con un UID arbitrario**
   — `chown :0` + `chmod g=u` sui percorsi scrivibili e su `HOME`, `USER`
   numerico. La prova è un avvio:
   `docker run --user 12345:0 …`, con un UID che non esiste nell'immagine.
4. **Si decide dove vivono i repository** (restano in `StratiGraph-ECCCH`?).
5. Solo dopo: workflow su tag verso `ghcr.io/stratigraph-eccch/`, multi-arch
   `amd64`+`arm64`, etichette OCI, e la verifica finale fatta **senza
   credenziali**.
6. **E.D. rende pubblico ogni pacchetto**, una volta, a mano.

I punti 1-3 sono di 3DR. Il 4 è una conversazione. Il 5 è mezz'ora, ed è lo
stesso file già scritto quattro volte in questo progetto.
