#!/usr/bin/env bash
# verifica-tirata-anonima · l'immagine si può tirare SENZA credenziali, ed è multi-arch
#
# LA TRAPPOLA CHE QUESTO SCRIPT ESISTE PER PRENDERE. Al primo push GHCR crea il
# pacchetto **privato**. Il workflow diventa verde, il push è riuscito davvero, e
# chi deve specchiare l'immagine non può tirare niente. Il job non se ne accorge
# perché è AUTENTICATO per costruzione: il suo `docker login` è la ragione per
# cui non vede il muro che vedono tutti gli altri.
#
# Quindi l'ultimo gesto della pubblicazione è fatto da un estraneo:
# `DOCKER_CONFIG` vergine, nessun `docker login`, e la domanda posta al registry
# come la porrebbe PSNC.
#
# E non basta che risponda: deve rispondere con ENTRAMBE le architetture. PSNC è
# amd64, il nodo di campo è un Raspberry arm64, e un'immagine con una sola
# architettura significa che una delle due parti non può tirare — cosa che si
# scopre sul posto, non qui.
#
#   ./verifica-tirata-anonima.sh ghcr.io/stratigraph-eccch/stratigraph-server:v1.2.3
#
# Le architetture attese si possono cambiare con ARCHITETTURE="linux/amd64 …".
#
# ROSSO se: il registry chiede le credenziali (pacchetto privato), il tag non
# esiste, o manca una delle architetture.
set -uo pipefail

RIF="${1:-}"
ARCHITETTURE="${ARCHITETTURE:-linux/amd64 linux/arm64}"

if [ -z "$RIF" ]; then
  echo "uso: $0 <registry/namespace/immagine:tag>" >&2
  exit 2
fi

# Un contesto docker PULITO, e non solo un `docker logout`: il logout toglie la
# voce dal file di configurazione, ma su una macchina con un credential helper
# (il Mac di chi sviluppa, per esempio) il helper la rimette. Una directory
# vuota non ha helper e non ha voci — è l'unico modo di essere sicuri che la
# domanda parta davvero senza nome.
CONFIG_PULITA="$(mktemp -d)"
trap 'rm -rf "$CONFIG_PULITA"' EXIT

#: ── UN CONTESTO PULITO NON È UNA CARTELLA VUOTA ─────────────────────────────
#:
#: La prima versione di questo script esportava `DOCKER_CONFIG` su una
#: directory vuota e basta. Misurato su questo Mac: `docker` smetteva di
#: funzionare del tutto —
#:
#:     docker: unknown command: docker buildx
#:
#: perché in `~/.docker` non ci sono solo le credenziali: ci sono anche i
#: CONTESTI, cioè l'indirizzo del demone (con colima, rancher o un host remoto
#: il demone NON è su `/var/run/docker.sock`), e la cartella dei plugin. Buttare
#: via tutto per togliere le credenziali è togliere il telefono per non far
#: chiamare nessuno — e il risultato era che il controllo delle etichette qui
#: sotto si dichiarava «saltato» per sempre, in silenzio.
#:
#: Quindi: si copia ciò che serve per PARLARE (contesti, plugin) e si lascia
#: fuori ciò che serve per essere RICONOSCIUTI (`auths`, `credsStore`,
#: `credHelpers`). Il `currentContext` resta, le credenziali no.
_ORIG="${DOCKER_CONFIG:-$HOME/.docker}"
for pezzo in cli-plugins contexts; do
  [ -d "$_ORIG/$pezzo" ] && cp -R "$_ORIG/$pezzo" "$CONFIG_PULITA/" 2>/dev/null
done
if [ -f "$_ORIG/config.json" ]; then
  ORIG="$_ORIG/config.json" DEST="$CONFIG_PULITA/config.json" python3 -c '
import json, os
try:
    d = json.load(open(os.environ["ORIG"]))
except Exception:
    d = {}
for chiave in ("auths", "credsStore", "credHelpers"):
    d.pop(chiave, None)
json.dump(d, open(os.environ["DEST"], "w"))
' 2>/dev/null || printf '{}' > "$CONFIG_PULITA/config.json"
fi
export DOCKER_CONFIG="$CONFIG_PULITA"
#: e il puntatore ESPLICITO ai plugin: misurato su docker 29.6.1, il client NON
#: deriva la cartella dei plugin da `DOCKER_CONFIG`.
[ -d "$CONFIG_PULITA/cli-plugins" ] && export DOCKER_CLI_PLUGIN_DIR="$CONFIG_PULITA/cli-plugins"

echo "▶ tirata ANONIMA di $RIF"
echo "  (DOCKER_CONFIG vergine: $CONFIG_PULITA — nessuna credenziale)"

manifesto="$(docker manifest inspect "$RIF" 2>&1)"
stato=$?
if [ $stato -ne 0 ] || ! printf '%s' "$manifesto" | head -c 1 | grep -q '{'; then
  echo "  ✗ il registry NON risponde a chi non ha credenziali:"
  printf '%s\n' "$manifesto" | sed 's/^/      /' | head -5
  echo
  echo "  Se il push è riuscito, quasi certamente il pacchetto è PRIVATO: GHCR"
  echo "  crea privato al primo push. Vedi il README, «rendere pubblico il"
  echo "  pacchetto»: è un passo per-pacchetto, una volta sola."
  exit 1
fi

trovate="$(printf '%s' "$manifesto" | python3 -c '
import sys, json
d = json.load(sys.stdin)
viste = set()
for m in d.get("manifests", []):
    p = m.get("platform", {})
    so, arch = p.get("os"), p.get("architecture")
    # le voci unknown/unknown sono le attestazioni di buildx, non piattaforme
    if so and arch and "unknown" not in (so, arch):
        viste.add(f"{so}/{arch}")
if "manifests" not in d:
    # nessuna lista: è UNA immagine sola, di qualunque mediaType (v2 o OCI —
    # misurato, un digest di piattaforma risponde con quest ultimo)
    print("SINGOLA")
else:
    print(" ".join(sorted(viste)))
')"

if [ "$trovate" = "SINGOLA" ]; then
  echo "  ✗ il manifesto è di UNA SOLA immagine, non una lista multi-arch."
  echo "    Metà di chi deve tirarla non può."
  exit 1
fi

echo "  ✓ risponde senza credenziali"
echo "    architetture nel manifesto: $trovate"

mancanti=""
for a in $ARCHITETTURE; do
  case " $trovate " in *" $a "*) ;; *) mancanti="$mancanti $a" ;; esac
done

if [ -n "$mancanti" ]; then
  echo "  ✗ mancano:$mancanti"
  exit 1
fi

echo "  ✓ ci sono tutte le architetture attese ($ARCHITETTURE)"

# ── E LE ETICHETTE, LETTE DALLO STESSO POSTO E SENZA NOME ────────────────────
#
# `org.opencontainers.image.source` non è cortesia: è ciò che lega il pacchetto
# al repository (ed è perché la pagina del pacchetto mostra il README), e sotto
# GPL è il posto da cui si prende il sorgente corrispondente a questo binario.
# `revision` è il commit, e senza quello «riproducibile» è una parola.
#
# Si leggono con `buildx imagetools`, che le prende dalla CONFIG dell'immagine —
# misurato che risponde anche a chi non ha credenziali, come il manifesto.
# Dove buildx non c'è, questo controllo si dichiara saltato invece di fingere.
ETICHETTE_ATTESE="${ETICHETTE_ATTESE:-org.opencontainers.image.source org.opencontainers.image.revision org.opencontainers.image.version org.opencontainers.image.created org.opencontainers.image.licenses}"

if ! docker buildx version >/dev/null 2>&1; then
  echo "  ~ etichette: NON controllate (manca buildx su questa macchina)"
else
  cfg="$(docker buildx imagetools inspect "$RIF" --format '{{json .Image}}' 2>/dev/null)"
  mancanti="$(printf '%s' "$cfg" | ETICHETTE="$ETICHETTE_ATTESE" python3 -c '
import sys, os, json
d = json.load(sys.stdin)
# una piattaforma sola torna l’oggetto, più piattaforme una mappa
per_piattaforma = d if "config" not in d else {"(unica)": d}
mancanti = []
for nome, img in per_piattaforma.items():
    ha = (img.get("config") or {}).get("Labels") or {}
    for e in os.environ["ETICHETTE"].split():
        if not ha.get(e):
            mancanti.append(f"{nome}:{e}")
print(" ".join(mancanti))
' 2>/dev/null)"
  if [ -z "$cfg" ]; then
    echo "  ✗ non riesco a leggere la config dell'immagine da anonimo"
    exit 1
  elif [ -n "$mancanti" ]; then
    echo "  ✗ etichette OCI mancanti (prime 6):"
    printf '%s\n' $mancanti | head -6 | sed 's/^/      /'
    n="$(printf '%s\n' $mancanti | wc -l | tr -d " ")"
    [ "$n" -gt 6 ] && echo "      …e altre $((n - 6))"
    exit 1
  else
    echo "  ✓ le etichette OCI ci sono su ogni architettura"
  fi
fi

# ── E IL TAG NON PUÒ ESSERE SOLO `latest` ────────────────────────────────────
#
# Un mirror di `:latest` è un registry che nessuno può riprodurre: il nome non
# dice quale immagine è, e domani ne indica un'altra. `:latest` può esserci in
# aggiunta; non può essere il nome con cui si verifica una pubblicazione.
case "$RIF" in
  *:latest)
    echo "  ✗ la verifica sta guardando \`:latest\`, che non identifica niente."
    echo "    Il tag di versione è quello che si cita e quello che si specchia."
    exit 1 ;;
esac

