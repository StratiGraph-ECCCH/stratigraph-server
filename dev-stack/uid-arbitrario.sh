#!/bin/sh
# uid-arbitrario · le tre immagini partono con un UID che non esiste dentro di loro
#
# LA DOMANDA. OpenShift — che è quello che gira a PSNC — NON rispetta `USER
# <nome>`: assegna al pod un UID a caso preso dall'intervallo del progetto e lo
# mette nel gruppo 0 come gruppo supplementare. Il processo diventa quindi un
# utente che non possiede niente. Leggere il Dockerfile e dire «adesso è a
# posto» non misura questo: lo misura un AVVIO.
#
# Perciò ogni immagine viene avviata con `--user 12345:0`, dove 12345 non
# compare nel `/etc/passwd` dell'immagine — la prova lo VERIFICA invece di
# darlo per buono — e poi si guarda, dall'ESTERNO e dall'interno:
#
#   1. il processo parte e resta su
#   2. /health risponde 200 a chi interroga da fuori
#   3. il processo SCRIVE dove deve scrivere (la cartella dei dati)
#   4. HOME è scrivibile (una libreria che vuole una dot-directory non muore)
#   5. il testo della licenza è dentro l'immagine, in /licenses/LICENSE
#   6. `USER` dell'immagine è un NUMERO (Kubernetes valuta runAsNonRoot
#      sull'UID, e un nome non lo sa verificare)
#
# LA MUTAZIONE che la rende una prova: rimetti `chown <utente>:<utente>` e
# togli `chmod g=u` nel Dockerfile e ricostruisci → il punto 3 deve diventare
# ROSSO. Se resta verde, questa prova sta misurando che il container esiste,
# non che l'utente casuale può lavorarci.
#
#   ./uid-arbitrario.sh              usa le immagini :uidtest già costruite
#   ./uid-arbitrario.sh --build      le costruisce prima
#
set -eu

UID_FINTO=12345
VERSIONE="${S3DGRAPHY_VERSION:-1.6.0.dev17}"
QUI="$(cd "$(dirname "$0")" && pwd)"
RADICE="$(cd "$QUI/../.." && pwd)"

rosse=0
verdi=0
ok()   { verdi=$((verdi+1)); printf "  \033[32m✓\033[0m %s\n" "$*"; }
male() { rosse=$((rosse+1)); printf "  \033[31m✗\033[0m %s\n" "$*"; }

# nome:cartella-dati:porta-host
SERVIZI="stratigraph-server:/srv/em-data:18401
stratigraph-chatbot:/srv/chatbot-data:18402
stratigraph-catalog:/srv/em-catalog-data:18403"

if [ "${1:-}" = "--build" ]; then
  for riga in $SERVIZI; do
    nome="${riga%%:*}"
    printf "▶ costruisco %s\n" "$nome"
    docker build --build-arg "S3DGRAPHY_VERSION=$VERSIONE" \
                 -t "$nome:uidtest" "$RADICE/$nome" >/dev/null
  done
fi

SHA_LICENZA="$(shasum -a 256 "$RADICE/stratigraph-server/LICENSE" 2>/dev/null | cut -d' ' -f1 \
               || sha256sum "$RADICE/stratigraph-server/LICENSE" | cut -d' ' -f1)"

for riga in $SERVIZI; do
  nome="${riga%%:*}"; resto="${riga#*:}"
  dati="${resto%%:*}"; porta="${resto##*:}"
  img="$nome:uidtest"
  printf "\n▶ %s  (--user %s:0, dati in %s)\n" "$nome" "$UID_FINTO" "$dati"

  # 0 · l'UID dev'essere DAVVERO assente, sennò la prova non prova niente
  if docker run --rm --entrypoint sh "$img" -c "getent passwd $UID_FINTO" >/dev/null 2>&1; then
    male "$UID_FINTO esiste nel /etc/passwd dell'immagine: la prova è vuota"
    continue
  else
    ok "$UID_FINTO non esiste nel /etc/passwd dell'immagine"
  fi

  # 6 · USER numerico, letto dall'IMMAGINE COSTRUITA e non dal Dockerfile
  u="$(docker image inspect --format '{{.Config.User}}' "$img")"
  case "$u" in
    ''|*[!0-9]*) male "USER dell'immagine è «$u», non un numero" ;;
    *)           ok "USER dell'immagine è il numero $u" ;;
  esac

  # 5 · la licenza dentro l'immagine, provata con un `cat` e non con il COPY
  dentro="$(docker run --rm --user "$UID_FINTO:0" --entrypoint sh "$img" \
            -c 'sha256sum /licenses/LICENSE 2>/dev/null | cut -d" " -f1' || true)"
  if [ "$dentro" = "$SHA_LICENZA" ]; then
    ok "/licenses/LICENSE c'è ed è lo stesso file del repo"
  else
    male "/licenses/LICENSE assente o diverso (dentro: ${dentro:-niente})"
  fi

  # 1+2 · parte, e /health risponde da FUORI. Volume anonimo sulla cartella
  # dati: è la forma in cui il compose la monta, ed è quella che un tempo
  # arrivava root-owned.
  c="$(docker run -d --rm --user "$UID_FINTO:0" -p "$porta:8000" -v "$dati" "$img")"
  vivo=no
  i=0
  while [ $i -lt 40 ]; do
    if curl -fsS -m 2 "http://127.0.0.1:$porta/health" >/dev/null 2>&1; then vivo=sì; break; fi
    if [ -z "$(docker ps -q -f id="$c")" ]; then break; fi
    i=$((i+1)); sleep 0.5
  done
  if [ "$vivo" = "sì" ]; then
    ok "parte e /health risponde 200 dall'esterno (porta $porta)"
  else
    male "non risponde su /health — ultime righe:"
    docker logs "$c" 2>&1 | tail -12 | sed 's/^/      /'
    docker rm -f "$c" >/dev/null 2>&1 || true
    continue
  fi

  # 3 · SCRIVE dove deve scrivere, come l'utente che l'orchestratore ha inventato
  if docker exec "$c" sh -c "printf ciao > $dati/.prova-uid && cat $dati/.prova-uid" >/dev/null 2>&1; then
    ok "scrive in $dati"
  else
    male "NON riesce a scrivere in $dati — $(docker exec "$c" sh -c "ls -ldn $dati" 2>&1)"
  fi

  # 4 · HOME scrivibile: con un UID che non è nel passwd, HOME sarebbe `/`
  h="$(docker exec "$c" sh -c 'echo $HOME')"
  if docker exec "$c" sh -c 'touch "$HOME/.prova-uid"' >/dev/null 2>&1; then
    ok "HOME ($h) è scrivibile"
  else
    male "HOME ($h) NON è scrivibile — $(docker exec "$c" sh -c 'ls -ldn "$HOME"' 2>&1)"
  fi

  docker rm -f "$c" >/dev/null 2>&1 || true
done

printf "\n── %d verdi · %d rosse ──\n" "$verdi" "$rosse"
[ "$rosse" -eq 0 ]
