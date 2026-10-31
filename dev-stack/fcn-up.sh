#!/usr/bin/env bash
# fcn-up — accendi il Field Computing Node: Caddy+https su hostname (mai IP nudo),
# e tira su l'intera stack StratiGraph.
#
#   ./fcn-up.sh                 # locale: https://em.localhost:8443 (+ serve anche il nome mDNS .local)
#   ./fcn-up.sh mac.local       # host PRIMARIO = un hostname risolvibile (per l'altro computer)
#                               #   …e si annuncia sulla rete locale (_stratigraph._tcp; lo ferma fcn-down)
#   ./fcn-up.sh --demo          # …e POPOLA: studi, stanze, immagini IIIF. Idempotente.
#   ./fcn-up.sh --local-s3d     # s3Dgraphy dal CHECKOUT LOCALE (editi e testi live)
#   ./fcn-up.sh mac.local --local-s3d
#   ./fcn-up.sh --no-studio     # …senza il dev server di EMStudio (/em/studio/ dà 502)
#   ./fcn-up.sh --studio        # …e lo PRETENDE: se il checkout non è pronto, si ferma
#
# EMSTUDIO: `/em/studio/` e `/em/read/` sono il dev server Vite di EMStudio, che
# gira SULL'HOST (porta 5173) e che Caddy raggiunge da `host.docker.internal`.
# Lo accende questo script, in background, se `../../EMStudio/frontend/
# node_modules` c'è; altrimenti tace — un nodo di campo non ha EMStudio, e non
# è rotto. Pid e log in `dev-stack/emstudio-dev.{pid,log}`; lo spegne
# `./fcn-down.sh`. Se sulla 5173 risponde già qualcosa, non ne avvia un secondo.
#
# NB: la CA interna di Caddy NON fa certificati per un IP nudo → per l'altro computer
# serve un HOSTNAME (il nome mDNS `<host>.local` — Bonjour su macOS, avahi su
# Linux — oppure /etc/hosts, oppure un dominio vero),
# non 172.x.x.x. E la rete deve vedersi (hotspot che isola i client → travel-router/Tailscale).
#
# DATI: i volumi (studi, stanze, bucket asset+corpus, realm, CA di Caddy) PERSISTONO fra i
# riavvii — `./fcn-down.sh` poi `./fcn-up.sh` (o un restart dei container) ritrova tutto.
# Solo `./fcn-down.sh --wipe` cancella i volumi (dati persi; dopo serve ./fcn-trust-ca.sh).
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} /^[[:space:]]*$/{next} {exit}' "$0"; exit 0
fi
set -euo pipefail
cd "$(dirname "$0")"                     # stratigraph-server/dev-stack

# CHE MACCHINA È QUESTA. `platform.sh` non assume: chiede.
. ./platform.sh

HTTPS_PORT="${HTTPS_PORT:-8443}"
DEV_REALM="${DEV_REALM:-em-dev}"

# ── argomenti: hostname PRIMARIO opzionale + --local-s3d ─────────────────────
LOCAL_S3D="no"; DEMO="no"; ARG_HOST=""; STUDIO="auto"; BUILD="--build"
for a in "$@"; do
  case "$a" in
    --local-s3d) LOCAL_S3D="yes" ;;
    --demo)      DEMO="yes" ;;
    --studio)    STUDIO="yes" ;;
    --no-studio) STUDIO="no" ;;
    #: --offline (31 ott 2026): l'avvio di un nodo che può non avere rete —
    #: quello che fa da sé all'accensione (`fcn-autostart.sh`). Niente build:
    #: anche con tutto in cache, una build chiede al registro i metadati delle
    #: immagini di base, e senza rete si ferma. Le immagini le ha già fatte il
    #: primo `fcn-up.sh`, a casa. E niente dev server di EMStudio.
    --offline)   BUILD=""; STUDIO="no" ;;
    -*) echo "flag sconosciuto: $a (usa --local-s3d | --demo | --studio | --no-studio | --offline)"; exit 2 ;;
    *) ARG_HOST="$a" ;;
  esac
done

# ── 1 · Docker che risponde ──────────────────────────────────────────────────
#
# Era `colima status` SEMPRE, e Colima è di macOS: su Linux il demone è di
# sistema, su Windows non esiste. La domanda vera non è «che sistema è questo»
# ma **«docker risponde?»** — e colima è il rimedio su macOS quando la risposta
# è no, non un passo prima di averla chiesta.
sg_ensure_docker || exit 1

# ── 2 · host primario (browser) + gli indirizzi che Caddy serve ──────────────
#: …e se non lo si passa, quello che il nodo ha scelto una volta per tutte
#: (`FCN_HOST` in `.env.dev`, lo scrive `fcn-field-setup.sh`): così l'avvio di
#: ogni giorno, e quello automatico all'accensione, è `./fcn-up.sh` e basta.
FCN_HOST_SAVED="$( [ -f .env.dev ] && grep -E '^FCN_HOST=' .env.dev | tail -1 | cut -d= -f2- || true)"
PRIMARY="${ARG_HOST:-${FCN_HOST_SAVED:-em.localhost}}"   # dove punta il browser (URL pubblici)
#: IN MINUSCOLO (31 ottobre 2026): il browser scrive l'host in minuscolo
#: («macbook-pro-di-emanuel.local») e Keycloak confronta le redirect URI come
#: stringhe, quindi un realm reso per «MacBook-Pro-di-Emanuel.local» — il nome
#: che `scutil` restituisce — rispondeva «Invalid parameter: redirect_uri» al
#: primo telefono. Un nome host non distingue maiuscole: lo si scrive una volta.
PRIMARY="$(printf '%s' "$PRIMARY" | tr '[:upper:]' '[:lower:]')"
# Il nome con cui l'altro computer può raggiungere questo (mai un IP: la CA
# interna di Caddy non fa certificati per un IP nudo). `scutil` su macOS,
# `hostname -s` altrove — la differenza sta in `platform.sh`, non qui.
BONJOUR="$(sg_local_hostname)"; [ -n "$BONJOUR" ] && BONJOUR="${BONJOUR}.local"
# Caddy serve em.localhost SEMPRE, + il primario e il nome mDNS se diversi (hostname, mai IP)
addrs="https://em.localhost"
[ "$PRIMARY" != "em.localhost" ] && addrs="$addrs, https://$PRIMARY"
[ -n "$BONJOUR" ] && [ "$BONJOUR" != "em.localhost" ] && [ "$BONJOUR" != "$PRIMARY" ] && addrs="$addrs, https://$BONJOUR"
export EM_SITE="$addrs"
# il certificato da dare a chi bussa senza un nome (un indirizzo numerico)
export EM_DEFAULT_SNI="$PRIMARY"
export EM_DEV_DOMAIN="$PRIMARY"

# ── 3 · gli URL PUBBLICI puntano all'host primario ───────────────────────────
# `/iiif/3` E NON `/iiif`: misurato l'8 settembre 2026, `/iiif` dà 404 e
# `/iiif/3` dà 200 — è l'Image API 3 di Cantaloupe, e `app/main.py:1863` scrive
# la forma attesa (`https://host/iiif/3`). Questo export era MORTO perché il
# compose cablava la riga, quindi il percorso sbagliato non si era mai visto:
# leggere la variabile senza correggere qui avrebbe rotto IIIF.
export EM_IIIF_PUBLIC="https://${PRIMARY}:${HTTPS_PORT}/iiif/3"
# ── §3 · QUESTO EXPORT È STATO TOLTO, e la sua assenza è la correzione ──────
#
# Era:  export EM_CATALOG_EMSTUDIO_URL="https://${PRIMARY}:${HTTPS_PORT}"
#
# cioè un'ORIGINE NUDA, senza percorso. Il catalogo la consuma come base di
# EMStudio (`stratigraph-catalog/app/deeplink.py:120-124`):
#
#     web = _base("EM_CATALOG_EMSTUDIO_URL")
#     "web": f"{web}/?study={quoted}&emjson=…"
#
# quindi il link diventava `https://<host>:8443/?study=…`, la HOME del nodo.
# Misurato dal vivo l'8 settembre, chiedendolo al catalogo che gira:
#
#     web = https://em.localhost:8443/?study=studio-x&emjson=…   → 302
#     https://em.localhost:8443/em/studio/?study=studio-x        → 200
#
# E NON serviva un host primario per rompersi: `PRIMARY` vale `em.localhost`
# quando non si passa niente, l'ambiente di shell batte `--env-file`, quindi
# questo export vinceva SEMPRE sul default `/em/studio` del compose. Il rinomino
# non peggiorava questa variabile: era già rotta in entrambe le direzioni.
#
# La correzione è togliere l'export, non aggiustarlo: è un indirizzo sullo stesso
# nodo, quindi sta in categoria 1 e il default relativo del compose lo segue da
# sé. Un export assoluto era esattamente lo sbaglio che la regola nomina.
# (Nessuna riga cambiata in stratigraph-catalog.)
# ⚠ VERIFICA: l'issuer OIDC dipende da come Caddy espone Keycloak nel Caddyfile.dev
export OIDC_ISSUER="https://${PRIMARY}:${HTTPS_PORT}/auth/realms/${DEV_REALM}"
# …and the origin Keycloak stamps into every token, so `iss` is ONE string
# whichever door it came through (the proxy, or the direct port).
export OIDC_PUBLIC_ORIGIN="https://${PRIMARY}:${HTTPS_PORT}"
# What a HANDOFF link names (`stratigraph://open?server=…`): the same host the
# browser is on, not a hardcoded em.localhost.
export EM_PUBLIC_BASE="https://${PRIMARY}:${HTTPS_PORT}/em"

# ── 4 · su (con l'override s3Dgraphy-locale se richiesto) ─────────────────────
# ── 3-bis · IL REALM IMPARA IL NOME (prima di `up`, perché è un import) ──────
#
# Misurato sul Pi il 7 settembre 2026: `./fcn-up.sh fcn.local` fa emettere a
# Caddy un certificato per quel nome, la pagina ARRIVA da un'altra macchina —
# TLS a posto, CA fidata, Keycloak che risponde — e poi il login muore con
#
#     We are sorry…   Invalid parameter: redirect_uri
#
# perché le 28 redirect URI del client `em-console` sono cablate su
# `em.localhost:8443` e su `localhost`. L'argomento «host primario» era
# applicato a METÀ: Caddy lo imparava, il realm no. E `--help` lo offre dicendo
# «per l'altro computer», cioè promette esattamente la cosa che non funziona.
#
# `render_realm.py` RISPECCHIA le URI dell'autorità canonica per il nome nuovo:
# i percorsi restano quelli già dichiarati, cambia solo l'host, e un jolly nella
# parte host è rifiutato — sarebbe un open redirect.
#
# Il file reso è ignorato da git e il compose lo monta via `${REALM_FILE}`, il
# cui default è il file committato: senza argomenti, `up` monta esattamente
# quello di prima.
# ── 3-bis · IL NODO DA CAMPO (31 ottobre 2026) ───────────────────────────────
#
# `.env.dev` lo dice con `EM_NODE_KIND=field` (lo scrive `./fcn-field-setup.sh`).
# Allora tre cose cambiano, e solo quelle: il realm nasce SENZA account
# dimostrativi e con il segreto di em-server di questo nodo
# (`render_realm.py --campo`); Keycloak tiene i suoi dati su un volume e la
# lista degli accreditati è quella del nodo (`docker-compose.field.yml`);
# dopo l'avvio il gestore riceve il suo account (`accredit.sh`).
env_dev_val() { [ -f .env.dev ] && grep -E "^$1=" .env.dev | tail -1 | cut -d= -f2- || true; }
FIELD="no"
[ "${EM_NODE_KIND:-$(env_dev_val EM_NODE_KIND)}" = "field" ] && FIELD="yes"
if [ "$FIELD" = "yes" ]; then
  if [ ! -f accredited.field.yaml ]; then
    echo "✖ il nodo è dichiarato «da campo» ma manca accredited.field.yaml." >&2
    echo "  Lo prepara, insieme ai segreti:" >&2
    echo "    ./fcn-field-setup.sh --orcid <il tuo iD> --name \"Nome Cognome\"" >&2
    exit 1
  fi
  REALM_RESO="keycloak/realm-em-dev.campo.json"
  set +e
  DEV_CLIENT_SECRET="${DEV_CLIENT_SECRET:-$(env_dev_val DEV_CLIENT_SECRET)}" \
    python3 render_realm.py --campo --host "$PRIMARY" --porta "$HTTPS_PORT" \
            --out "$REALM_RESO" --zitto
  rc=$?
  set -e
  if [ "$rc" != 0 ]; then
    echo "✖ non riesco a preparare il realm del nodo da campo (sopra il perché)." >&2
    exit 1
  fi
  export REALM_FILE="./$REALM_RESO"
  echo "· nodo da campo: realm senza account dimostrativi, Keycloak con i suoi dati su volume"
elif [ "$PRIMARY" != "em.localhost" ]; then
  REALM_RESO="keycloak/realm-em-dev.${PRIMARY}.json"
  set +e
  python3 render_realm.py --host "$PRIMARY" --porta "$HTTPS_PORT" \
          --out "$REALM_RESO"
  rc=$?
  set -e
  case "$rc" in
    0) export REALM_FILE="./$REALM_RESO" ;;
    3) : ;;                       #: già coperto: si monta il committato
    *) echo "✖ non so insegnare \`$PRIMARY\` al realm di Keycloak." >&2
       echo "  Caddy servirebbe quel nome e il login morirebbe con «Invalid" >&2
       echo "  parameter: redirect_uri» DOPO che tutto il resto ha funzionato," >&2
       echo "  che è il modo peggiore di fallire. Mi fermo qui." >&2
       exit 1 ;;
  esac
fi

# ── 4-zero · IL FILE CHE CHI CLONA NON HA ────────────────────────────────────
#
# `.env.dev` è in `.gitignore` (contiene i valori riempiti) e `.env.dev.example`
# è committato. Ma questa riga lo USA con `--env-file` senza controllarlo, e su
# un clone fresco `./fcn-up.sh` moriva prima di qualunque altra cosa con
#
#     couldn't find env file: …/dev-stack/.env.dev
#
# misurato il 9 ottobre 2026. È della stessa famiglia del `command not found`
# del compose: un primo avvio che si ferma alla prima riga, su una macchina che
# non è quella di chi ha scritto lo script.
#
# NON lo copio io: `.env.dev` porta credenziali (senza valore, ma credenziali) e
# crearlo è un atto di una persona — la stessa ragione per cui `fcn-trust-ca.sh`
# stampa il comando `sudo` invece di eseguirlo. Qui si stampa la riga da
# incollare, che è una cosa sola.
sg_need_env_dev || exit 1

# QUALE compose. Era `docker-compose` scritto a mano: è il binario autonomo, e
# su una macchina nuova (Docker Engine su Linux, Docker Desktop su Windows) non
# c'è — la PRIMA riga risponde `command not found`. `sg_compose_array` chiede
# quale dei due esiste e riempie l'array; se non c'è nessuno dei due dice cosa
# manca invece di proseguire al buio.
sg_compose_array || exit 1
COMPOSE+=(--env-file .env.dev -f docker-compose.dev.yml)
[ "$FIELD" = "yes" ] && COMPOSE+=(-f docker-compose.field.yml)
if [ "$LOCAL_S3D" = "yes" ]; then
  COMPOSE+=(-f docker-compose.local-s3d.yml)
  #: E QUESTO È UN BIND MOUNT, NON UN `context:` — quindi il controllo dei
  #: fratelli qui sotto NON lo vede, perché `config` non lo elenca fra i
  #: contesti. Misurato l'8 settembre 2026: con la sorgente assente il mount
  #: RIESCE e monta una cartella VUOTA, il container parte sano, e
  #: `PYTHONPATH=/s3dgraphy-src` ricade sul wheel installato. Cioè
  #: `--local-s3d` non fa NIENTE, in silenzio: si edita s3Dgraphy, si riavvia,
  #: e non cambia niente. È la forma «funziona quasi», che costa ore.
  if [ ! -d ../../s3Dgraphy/src ]; then
    echo "✖ --local-s3d, ma \`../../s3Dgraphy/src\` non c'è." >&2
    echo "  Non è un \`context:\`, è un bind mount: docker monterebbe una" >&2
    echo "  cartella VUOTA, i container partirebbero sani e PYTHONPATH" >&2
    echo "  ricadrebbe sul wheel — cioè --local-s3d non farebbe niente, e" >&2
    echo "  senza dirlo." >&2
    echo >&2
    echo "      ./fcn-install.sh --local-s3d      (lo clona)" >&2
    exit 1
  fi
  echo "▶ modo s3Dgraphy LOCALE: StratiGraph Server/StratiGraph Catalog useranno ../../s3Dgraphy/src (edita e riavvia per testare)."
fi
# ── 4-bis · I FRATELLI, PRIMA DEI PULL ───────────────────────────────────────
#
# `fcn-install.sh` è il posto dove questo si prepara, ma `fcn-up.sh` è quello
# che la gente lancia — è il comando che sta nel README e nell'aiuto. Su un
# clone del solo `stratigraph-server`, misurato sul Pi il 7 settembre 2026:
#
#     unable to prepare context: path "/home/paul/stratigraph-chatbot" not found
#
# e quel messaggio è comparso DOPO cinque immagini scaricate. Il controllo costa
# un `test -d` per repository e va fatto qui, non solo nell'installer: un
# controllo che esiste solo sulla strada documentata protegge la strada
# documentata.
#
# I percorsi li chiede al compose — un solo posto che li sa, e sono già
# assoluti.
mancanti=""
for ctx in $("${COMPOSE[@]}" config 2>/dev/null              | sed -n 's/^[[:space:]]*context:[[:space:]]*//p' | sort -u); do
  [ -d "$ctx" ] || mancanti="$mancanti $ctx"
done
if [ -n "$mancanti" ]; then
  echo "✖ il compose costruisce da repository affiancati che non ci sono:" >&2
  for m in $mancanti; do echo "     $m" >&2; done
  echo >&2
  echo "  Non comincio a scaricare immagini: sul Pi lo stesso guaio è comparso" >&2
  echo "  dopo cinque pull, cioè dopo tutto il lavoro che rendeva inutile." >&2
  echo >&2
  echo "      ./fcn-install.sh$( [ "$LOCAL_S3D" = "yes" ] && echo " --local-s3d" )" >&2
  echo >&2
  echo "  li clona (gli indirizzi stanno in \`x-sibling-repos\`, nel compose)." >&2
  exit 1
fi

# ── 4-quater · EMSTUDIO: SI DECIDE ADESSO, SI ACCENDE DOPO `up` ───────────────
#
# Il dev server resta SULL'HOST e non diventa un container: `vite.config.ts` è
# scritto per passare da Caddy (`allowedHosts`), e un file-watcher dentro un
# bind mount di Colima perderebbe l'hot reload senza guadagnare niente. Quindi
# qui è supervisione, non containerizzazione.
#
# Il checkout lo prepara `fcn-install.sh` (clone, `npm install`, `build:reader`).
# Qui si guarda soltanto. `auto` = acceso se c'è, zitto se non c'è: un nodo di
# campo non ha EMStudio, e il compose lo dice già (`EM_EMSTUDIO_WEB_URL`,
# `EM_CATALOG_EMSTUDIO_URL` senza default). `--studio` invece lo pretende, e
# se manca si ferma QUI, prima dei pull — non dopo.
#
# `SG_STUDIO_DIR` e `SG_STUDIO_PIDFILE` esistono per le prove, come
# `SG_ANNOUNCE_PIDFILE`: girano su questo `dev-stack/` e non devono accendere
# (o spegnere) il Vite di chi le lancia.
STUDIO_DIR="${SG_STUDIO_DIR:-../../EMStudio}"
STUDIO_FRONTEND="$STUDIO_DIR/frontend"
STUDIO_PIDFILE="${SG_STUDIO_PIDFILE:-./emstudio-dev.pid}"
STUDIO_LOG="${STUDIO_PIDFILE%.pid}.log"
STUDIO_PROBE="http://localhost:5173/em/studio/"
studio_pronto="no"
[ -f "$STUDIO_FRONTEND/package.json" ] && [ -d "$STUDIO_FRONTEND/node_modules" ] \
  && command -v npm >/dev/null 2>&1 && studio_pronto="yes"
if [ "$STUDIO" = "auto" ]; then
  STUDIO="$studio_pronto"
elif [ "$STUDIO" = "yes" ] && [ "$studio_pronto" != "yes" ]; then
  echo "✖ --studio, ma il dev server di EMStudio non si può accendere:" >&2
  if [ ! -f "$STUDIO_FRONTEND/package.json" ]; then
    echo "     manca il checkout ($STUDIO_DIR)" >&2
  elif [ ! -d "$STUDIO_FRONTEND/node_modules" ]; then
    echo "     manca $STUDIO_FRONTEND/node_modules" >&2
  else
    echo "     npm non c'è su questa macchina (non lo installo io)" >&2
  fi
  echo >&2
  echo "      ./fcn-install.sh      (clona EMStudio e fa npm install)" >&2
  echo >&2
  echo "  oppure ./fcn-up.sh --no-studio. Non comincio a scaricare immagini." >&2
  exit 1
fi

# shellcheck disable=SC2086  # BUILD è vuoto con --offline, e allora non è un argomento
"${COMPOSE[@]}" --profile https up -d $BUILD

# ── 4-bis-campo · IL GESTORE ENTRA ───────────────────────────────────────────
#
# Sul nodo da campo il realm non ha account: quello del gestore lo crea qui
# `accredit.sh` dalla lista del nodo, appena Keycloak risponde. Idempotente
# (un account che c'è già si aggiorna, nessuno si toglie). Se Keycloak tarda,
# lo DICE con il comando da rilanciare e il resto prosegue.
if [ "$FIELD" = "yes" ]; then
  kc_port="$(env_dev_val KEYCLOAK_PORT)"; kc_port="${kc_port:-8085}"
  kc_pronto="no"
  for _ in $(seq 1 90); do
    curl -s -o /dev/null --max-time 2 -f "http://localhost:${kc_port}/auth/realms/em-dev" \
      && { kc_pronto="yes"; break; }
    sleep 2
  done
  if [ "$kc_pronto" = "yes" ] && ./accredit.sh accredited.field.yaml >/dev/null 2>&1; then
    echo "· nodo da campo: gli account della lista del nodo ci sono (accredited.field.yaml)"
  else
    echo "⚠ nodo da campo: non ho potuto creare gli account della lista. Fra un minuto:" >&2
    echo "    ./accredit.sh accredited.field.yaml" >&2
  fi
fi

# ── 4-quinquies · EMSTUDIO, ACCESO ───────────────────────────────────────────
#
# IDEMPOTENTE, e lo dice: se la 5173 risponde già (un `fcn-up` di prima, o un
# `npm run dev` lanciato a mano in un altro terminale) non se ne avvia un
# secondo — Vite ripiegherebbe sulla 5174, che Caddy non guarda.
#
# `set -m` intorno al lancio: il processo nasce in un GRUPPO SUO, e il pid
# scritto è quello del gruppo. `npm run dev` è npm → sh → node, e
# `fcn-down.sh` spegne il gruppo intero: uccidere solo npm lascerebbe vite
# orfano e la porta occupata.
studio_attivo="no"
if [ "$STUDIO" = "yes" ]; then
  pid_vecchio="$(cat "$STUDIO_PIDFILE" 2>/dev/null || true)"
  if curl -s -o /dev/null --max-time 2 "$STUDIO_PROBE"; then
    studio_attivo="yes"
    if [ -n "$pid_vecchio" ] && kill -0 "$pid_vecchio" 2>/dev/null; then
      echo "· EMStudio: il dev server è già attivo su :5173 (pid $pid_vecchio): non ne avvio un secondo."
    else
      echo "· EMStudio: sulla :5173 risponde già un dev server che non ho acceso io: non ne avvio un secondo."
    fi
  elif [ -n "$pid_vecchio" ] && kill -0 "$pid_vecchio" 2>/dev/null; then
    studio_attivo="yes"
    echo "· EMStudio: il dev server è già avviato (pid $pid_vecchio) e non risponde ancora: non ne avvio un secondo."
    echo "  Il suo log: $STUDIO_LOG"
  else
    set -m
    ( cd "$STUDIO_FRONTEND" && exec nohup npm run dev ) >"$STUDIO_LOG" 2>&1 < /dev/null &
    pid_studio=$!
    set +m
    echo "$pid_studio" > "$STUDIO_PIDFILE"
    #: 30s: Vite parte in un paio di secondi, ma la prima volta ottimizza le
    #: dipendenze. Se non risponde lo DICE e prosegue — il resto del nodo è su.
    for _ in $(seq 1 30); do
      curl -s -o /dev/null --max-time 1 "$STUDIO_PROBE" && { studio_attivo="yes"; break; }
      kill -0 "$pid_studio" 2>/dev/null || break
      sleep 1
    done
    if [ "$studio_attivo" = "yes" ]; then
      echo "· EMStudio: dev server acceso su :5173 (pid $pid_studio, log $STUDIO_LOG)."
    else
      echo "⚠ EMStudio: ho lanciato \`npm run dev\` (pid $pid_studio) ma la :5173 non risponde." >&2
      echo "  Guarda il log: $STUDIO_LOG — il resto del nodo è acceso." >&2
    fi
  fi
fi

# ── 4-ter · L'ANNUNCIO SULLA RETE LOCALE ─────────────────────────────────────
#
# Solo se il nodo è stato aperto «per l'altro computer», cioè con un host
# primario: senza argomenti il nodo è di questa macchina e non si annuncia
# (e un annuncio rimasto da un avvio precedente si spegne). La porta è quella
# di Caddy e l'API sta sotto `/em`: il TXT lo dice, `node_finder` lo legge.
# In background; lo ferma `./fcn-down.sh`. Vedi `sg_announce_*` in platform.sh.
if [ "$PRIMARY" != "em.localhost" ]; then
  nome_annuncio="${BONJOUR%.local}"; nome_annuncio="${nome_annuncio:-${PRIMARY%.local}}"
  sg_announce_start "StratiGraph (${nome_annuncio})" "$HTTPS_PORT" /em https
else
  sg_announce_stop
fi

# ── 4-bis · --demo: aspetta, poi popola ──────────────────────────────────────
#
# Il pulsantone è un FLAG, non uno script nuovo: `up` accendeva già tutto e
# stampava gli indirizzi, ma restavano tre `python dev-stack/seed_*.py` da
# ricordare. Qui vengono eseguiti quelli che ci sono già.
#
# I seed sono idempotenti per costruzione (riusano per id/nome invece di
# creare), quindi due `--demo` di fila lasciano lo stesso stato. Non è una
# proprietà da rompere: se un seed comincia a duplicare, si aggiusta lui.
if [ "$DEMO" = "yes" ]; then
  HEALTH="https://${PRIMARY}:${HTTPS_PORT}/em/v1/health"
  echo
  echo "▶ --demo: aspetto che il nodo risponda (${HEALTH})…"
  # 90s: la PRIMA accensione costruisce le immagini e Keycloak importa il realm.
  # Se scade lo DICE e si ferma qui — proseguire al buio significherebbe tre
  # seed che falliscono uno dopo l'altro con tre errori diversi, nessuno dei
  # quali è la causa.
  ready="no"
  for _ in $(seq 1 45); do
    if curl -sk -o /dev/null --max-time 2 "$HEALTH"; then ready="yes"; break; fi
    sleep 2
  done
  if [ "$ready" != "yes" ]; then
    echo "✗ il nodo non ha risposto entro 90s. NON popolo: guarda i log con"
    echo "  ${COMPOSE[0]}${COMPOSE[1]:+ ${COMPOSE[1]}} -f docker-compose.dev.yml logs --tail=40 stratigraph-server"
    exit 1
  fi
  echo "✔ nodo su. Popolo…"
  # L'ORDINE conta: le immagini prima, perché seed-demo cita gli asset che
  # smoke_iiif mette nel bucket.
  for step in smoke_iiif.py seed_rooms.py seed-demo.py; do
    echo
    echo "── $step ──────────────────────────────────────────────"
    if ! python3 "$step"; then
      echo "✗ $step è fallito. Gli altri passi NON sono stati eseguiti."
      exit 1
    fi
  done
fi

# ── 5 · indirizzi + promemoria ───────────────────────────────────────────────
cat <<EOF

✔ FCN acceso$( [ "$LOCAL_S3D" = "yes" ] && echo " (s3Dgraphy locale)" ). Caddy serve: ${EM_SITE}
  Su questo computer:   https://${PRIMARY}:${HTTPS_PORT}/em/v1/health
  Le mie stanze:        https://${PRIMARY}:${HTTPS_PORT}/em/rooms/
  Console del nodo:     https://${PRIMARY}:${HTTPS_PORT}/em/admin/
  Catalogo:             https://${PRIMARY}:${HTTPS_PORT}/catalog/ui/
  Assistente di campo:  https://${PRIMARY}:${HTTPS_PORT}/chat/
$( [ "$studio_attivo" = "yes" ] && echo "  EMStudio (dev):       https://${PRIMARY}:${HTTPS_PORT}/em/studio/" )
$( # ── PER L'ALTRO COMPUTER: PROVATO, NON PROMESSO ─────────────────────────
   #
   # Misurato il 7 settembre 2026: avahi è attivo sul Pi e PUBBLICA, e da un Mac
   # sulla stessa LAN `ping fcn.local` risponde `cannot resolve`. La causa non è
   # il Pi: è l'access point che non propaga il multicast fra i client, che sugli
   # AP di consumo è la norma. Quindi quella riga era un indirizzo che non
   # funziona, stampato come se funzionasse — la stessa forma del `curl` senza
   # `-f`.
   #
   # Adesso si prova, e si dice COSA si è trovato. E si dice anche il limite
   # della sonda, che è il punto: da qui si può misurare solo che QUESTA macchina
   # risolve il nome. Che lo risolva l'altra è la cosa che serve e che da qui non
   # si vede.
   if [ -n "$BONJOUR" ] && [ "$BONJOUR" != "$PRIMARY" ]; then
     esito="$(sg_reaches "https://${BONJOUR}:${HTTPS_PORT}/em/v1/health" 4)"
     if [ "$esito" = "si" ]; then
       echo "  Per l'ALTRO computer: https://${BONJOUR}:${HTTPS_PORT}/em/v1/health"
       echo "      ✔ questo nome risponde DA QUI. Che risponda dall'altra macchina"
       echo "        dipende dal multicast fra i client del vostro access point,"
       echo "        e molti AP di consumo non lo propagano: da qui non lo vedo."
     else
       echo "  Per l'ALTRO computer: ⚠ \`${BONJOUR}\` NON risponde nemmeno da qui"
       echo "      ($([ "$esito" = "nome" ] && echo "il nome non si risolve" || echo "si risolve ma non risponde")) — non lo stampo come indirizzo buono."
       ip="$(sg_lan_ip)"
       if [ -n "$ip" ]; then
         echo "      Il ripiego è insegnare il nome all'ALTRA macchina, UNA riga:"
         echo "          $ip  ${BONJOUR}      → nel suo /etc/hosts"
         echo "        (su Windows: C:\\Windows\\System32\\drivers\\etc\\hosts)"
         echo "      E poi https://${BONJOUR}:${HTTPS_PORT}/em/v1/health da lì."
         echo "      NON l'IP nudo: la CA interna di Caddy non firma per un IP,"
         echo "      quindi il nome serve comunque — si insegna, non si aggira."
       fi
     fi
   fi )

Note:
  · la ROOT (/) è un cartello: elenca le rotte vere. Tutto il resto dà 404 (e non
    più 200 con un banner, che faceva sembrare "irraggiungibile" un nodo acceso).
  · certificato: se il browser lo rifiuta → ./fcn-trust-ca.sh (una volta; e dopo ogni --wipe).
$( # RILEVATO, mai eseguito: fcn-trust-ca.sh chiede una password di sistema, e uno
   # script che si blocca su un prompt dentro un giro non presidiato è una trappola.
   # La sonda è diretta — curl SENZA -k riesce solo se il sistema si fida della CA.
   # Se l'host non risponde affatto stampa comunque l'avviso: un promemoria in più
   # costa una riga, un blocco silenzioso costa un pomeriggio.
   if ! curl -s -o /dev/null --max-time 4 "https://${PRIMARY}:${HTTPS_PORT}/em/v1/health"; then
     # «su questo Mac» stampato su Debian, misurato sul Pi l'8 settembre 2026.
     # Piccolo, ed è la famiglia: una frase che afferma un fatto sulla macchina
     # senza chiederglielo. `sg_os` lo sa, e sta in `platform.sh` da due notti.
     # `if`/`elif` E NON `case`: questo blocco vive dentro un `$( … )` di un
     # heredoc, e là il `)` di un pattern (`macos)`) CHIUDE la sostituzione.
     # `bash -n` non lo vede, perché un heredoc si analizza solo quando si
     # espande — trovato eseguendo, con 13 prove rosse in una volta.
     sistema="$(sg_os)"
     dove="su questa macchina"
     if [ "$sistema" = "macos" ]; then dove="su questo Mac"
     elif [ "$sistema" = "wsl" ]; then dove="dentro WSL — e il negozio che conta è quello di Windows"
     elif [ "$sistema" = "windows" ]; then dove="su questo Windows"
     fi
     echo "  · ⚠ LA CA NON È FIDATA ${dove}: il browser rifiuterà la pagina e"
     echo "      un service worker non si registrerà. Rimedio, UNA volta:  ./fcn-trust-ca.sh"
     echo "      (chiede la password di sistema, per questo non lo faccio io.)"
   fi )
$( # ── GLI INDIRIZZI RESI, CHIESTI ALL'AMBIENTE CHE ESISTE ─────────────────
   #
   # La regola sugli indirizzi pubblici era scritta, provata e applicata — ma
   # all'ambiente che il repository si ASPETTA. L'8 settembre 2026, sul Pi,
   # dopo `./fcn-up.sh fcn.local`, il catalogo ha servito
   #
   #     web → http://localhost:5173/?study=studio-x&emjson=x
   #
   # cioè la macchina di chi clicca, perché quella macchina aveva un `.env.dev`
   # GIÀ ESISTENTE, germogliato dall'example quando la riga era attiva.
   # Correggere il seme non tocca la pianta.
   #
   # Quindi qui si chiede all'ambiente RESO. `check_addresses.py` legge le
   # esenzioni da `x-public-addresses.exempt` nel compose — la stessa lista che
   # legge la prova generale, non una copia — DICE e non corregge, non blocca, e
   # su un avvio pulito non stampa niente.
   #
   # `|| true` due volte: sotto `set -euo pipefail` un compose che non conosce
   # `--format json` farebbe morire il nodo dopo che è salito, per un controllo.
   if [ -f check_addresses.py ]; then
     reso_json="$("${COMPOSE[@]}" config --format json 2>/dev/null || true)"
     if [ -n "$reso_json" ]; then
       printf '%s' "$reso_json" \
         | python3 check_addresses.py --primario "$PRIMARY" --reso - \
                   --env-file .env.dev 2>/dev/null | sed 's/^/  /' || true
     fi
   fi )
  · dati: studi/stanze/asset/corpus PERSISTONO fra i riavvii (volumi named). ./fcn-down.sh li
    tiene; solo ./fcn-down.sh --wipe li cancella.
  · altro computer: serve un HOSTNAME (mai IP nudo, rompe il TLS della CA interna) e che le
    due macchine si vedano in rete (hotspot che isola → travel-router · Internet-Sharing · Tailscale).
    Per usarlo come primario:  ./fcn-up.sh ${BONJOUR:-<mac>.local}
$( [ "$LOCAL_S3D" = "yes" ] && echo "  · dopo aver editato s3Dgraphy:  ${COMPOSE[0]}${COMPOSE[1]:+ ${COMPOSE[1]}} -f docker-compose.dev.yml -f docker-compose.local-s3d.yml restart stratigraph-server stratigraph-catalog" )
Giù:  ./fcn-down.sh   (o --stop / --wipe$( [ "$(sg_os)" = "macos" ] && command -v colima >/dev/null 2>&1 && echo " / --colima" ) )
EOF
