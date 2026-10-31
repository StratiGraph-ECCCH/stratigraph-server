#!/usr/bin/env bash
# fcn-down — spegni il Field Computing Node.
#
#   ./fcn-down.sh            # spegnimento pulito: rimuove i container, TIENE i dati
#                            #   (studi, stanze, bucket, realm, CA di Caddy) → riparte con ./fcn-up.sh
#   ./fcn-down.sh --stop     # solo pausa: container fermati ma non rimossi (ripartenza in secondi)
#   ./fcn-down.sh --wipe     # ⚠ AZZERA TUTTO: cancella anche i volumi (dati persi)
#   ./fcn-down.sh --colima   # dopo lo spegnimento, ferma anche la VM Colima (libera RAM)
#
# I flag si combinano: es.  ./fcn-down.sh --wipe --colima
#
# In ogni modo spegne PRIMA il dev server di EMStudio acceso da ./fcn-up.sh (il
# suo pid file in dev-stack/), poi i container. `--wipe` non cambia niente su
# questo: è un processo, non un volume. Un Vite lanciato a mano non lo tocca.
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} /^[[:space:]]*$/{next} {exit}' "$0"; exit 0
fi
set -euo pipefail
cd "$(dirname "$0")"                     # stratigraph-server/dev-stack
. ./platform.sh

# `--profile engine` here and NOT in fcn-up: the engine is opt-in to start
# (2.62 GB, see the compose) but "down" has to mean down — otherwise an
# engine somebody turned on by hand outlives the stack and keeps its volume.
# QUALE compose — vedi `sg_compose` in platform.sh: `docker compose` (plugin)
# prima, `docker-compose` (autonomo) come ripiego, e una frase se non c'è
# nessuno dei due. Era il secondo scritto a mano, che su una macchina nuova non
# esiste.
sg_compose_array || exit 1
COMPOSE+=(-f docker-compose.dev.yml --profile https --profile engine)
#: il nodo da campo (31 ott 2026): il suo file porta il volume di Keycloak, e
#: `--wipe` deve conoscerlo per cancellarlo; un `down` semplice lo conserva.
if [ "${EM_NODE_KIND:-$( [ -f .env.dev ] && grep -E '^EM_NODE_KIND=' .env.dev | tail -1 | cut -d= -f2- || true)}" = "field" ]; then
  COMPOSE+=(-f docker-compose.field.yml)
fi
MODE="down"; STOP_COLIMA="no"
for a in "$@"; do
  case "$a" in
    --stop)   MODE="stop" ;;
    --wipe|-v) MODE="wipe" ;;
    --colima) STOP_COLIMA="yes" ;;
    *) echo "flag sconosciuto: $a (usa --stop | --wipe | --colima)"; exit 2 ;;
  esac
done

#: L'annuncio `_stratigraph._tcp` acceso da `fcn-up.sh <host>`: un nodo spento
#: (o in pausa) non deve restare trovabile sulla rete. PRIMA di `wipe`, che chiede
#: conferma: anche se la conferma non arriva, un annuncio fermato non fa danni.
sg_announce_stop

#: Il dev server di EMStudio, PRIMA dei container: è un processo dell'host e non
#: dipende da loro, e spegnerlo per primo vuol dire che non c'è un istante in
#: cui Caddy è giù e Vite resta acceso a servire nessuno. Si spegne il GRUPPO
#: (`fcn-up.sh` lo lancia con `set -m`): npm → sh → node, e uccidere solo npm
#: lascerebbe vite orfano con la 5173 occupata.
#: `SG_STUDIO_PIDFILE` è per le prove, come in `fcn-up.sh`.
STUDIO_PIDFILE="${SG_STUDIO_PIDFILE:-./emstudio-dev.pid}"
pid_studio="$(cat "$STUDIO_PIDFILE" 2>/dev/null || true)"
if [ -n "$pid_studio" ] && kill -0 -- "-$pid_studio" 2>/dev/null; then
  kill -TERM -- "-$pid_studio" 2>/dev/null || true
  for _ in $(seq 1 50); do
    kill -0 -- "-$pid_studio" 2>/dev/null || break
    sleep 0.1
  done
  if kill -0 -- "-$pid_studio" 2>/dev/null; then
    kill -KILL -- "-$pid_studio" 2>/dev/null || true
    echo "· EMStudio: il dev server non è uscito con TERM in 5s: KILL (gruppo $pid_studio)."
  else
    echo "· EMStudio: dev server spento (pid $pid_studio), prima dei container."
  fi
  rm -f "$STUDIO_PIDFILE"
elif [ -n "$pid_studio" ]; then
  #: un pid file rimasto da un processo già morto (un riavvio, un kill a mano)
  rm -f "$STUDIO_PIDFILE"
  echo "· EMStudio: il pid file nominava un processo già uscito ($pid_studio): tolto."
fi

case "$MODE" in
  stop)
    echo "⏸  fermo i container (li tengo, ripartenza in secondi)…"
    "${COMPOSE[@]}" stop
    ;;
  down)
    echo "▶ spegnimento pulito: rimuovo i container, TENGO i dati…"
    # `--remove-orphans`, e non è profilassi: quando un servizio ESCE dal compose
    # il suo container resta addosso alla macchina, perché porta ancora la
    # `com.docker.compose.project=em-dev` e nessuno lo va a cercare. Misurato il
    # 7 ottobre con pyarchinit-mini: `docker-compose ps --all` lo elencava
    # ancora, come servizio `pyarchinit-mini`, ore dopo che il blocco era
    # uscito dal file. Un `down` che lo lascia in piedi vuol dire che il
    # prossimo `up` gira accanto a un fantasma che serve ancora la sua rotta.
    "${COMPOSE[@]}" down --remove-orphans
    echo "   i volumi (studi/stanze/bucket/realm/CA) restano; ./fcn-up.sh riparte da lì."
    ;;
  wipe)
    echo "⚠  --wipe: sto per CANCELLARE tutti i dati dell'FCN (studi, foto, utenti, e la CA di Caddy)."
    echo "   Dopo un wipe, l'altro computer dovrà RI-FIDARSI della nuova CA."
    read -r -p "   Scrivi 'wipe' per confermare: " ok
    [ "$ok" = "wipe" ] || { echo "annullato."; exit 1; }
    "${COMPOSE[@]}" down -v --remove-orphans
    echo "   tutto azzerato; il prossimo ./fcn-up.sh ri-semina bucket e realm da capo."
    ;;
esac

if [ "$STOP_COLIMA" = "yes" ]; then
  #: SOLO dove Colima esiste. `--colima` su Linux o su Windows chiedeva una
  #: cosa che non c'è, e `|| true` la rendeva un silenzio invece di una frase.
  if [ "$(sg_os)" = "macos" ] && command -v colima >/dev/null 2>&1; then
    echo "▶ fermo Colima…"
    colima stop || true
  else
    echo "· niente Colima su questo sistema ($(sg_os)): non c'è nulla da fermare."
  fi
fi

echo "✔ FCN spento (${MODE})."
