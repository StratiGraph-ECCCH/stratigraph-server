#!/usr/bin/env bash
# fcn-install — prepara una macchina fresca, poi cede il passo a fcn-up.sh.
#
#   ./fcn-install.sh                # controlla e prepara, poi dice cosa lanciare
#   ./fcn-install.sh fcn.local      # …e insegna QUEL nome anche al realm
#   ./fcn-install.sh --local-s3d    # …e serve anche il checkout di s3Dgraphy
#   ./fcn-install.sh --dry-run      # dice cosa farebbe e non fa niente
#   ./fcn-install.sh --field        # NODO DA CAMPO: installa anche quello che
#                                   #   manca al sistema (Docker, avahi, la riga
#                                   #   di /etc/hosts), con sudo — vedi «0 · …»
#
# COSA GARANTISCE, e sono le cose che hanno fatto fallire il primo avvio sul
# Raspberry Pi il 7 settembre 2026:
#
#   1  i quattro repository affiancati    — se ne manca uno, lo clona
#      …e di EMStudio anche `node_modules` e la `dist` del reader (con npm)
#   2  .env.dev esiste                    — non lo crea: dice la riga
#   3  Docker risponde e un compose c'è   — non li installa: dice cosa manca
#   4  em.localhost si risolve            — non tocca /etc/hosts: dice la riga
#   5  il nome primario lo impara il realm, non solo Caddy
#
# LA PROPRIETÀ CHE RIASSUME TUTTO: **fallisce prima dei pull, non dopo.**
# Sul Pi il messaggio
#
#     unable to prepare context: path "/home/paul/stratigraph-chatbot" not found
#
# è comparso DOPO cinque immagini scaricate, minuti di rete e di disco. Un
# controllo che costa un millisecondo arrivava dopo tutto il lavoro che rendeva
# inutile. Qui i controlli stanno prima, in ordine di costo.
#
# COSA NON FA, MAI:
#   · `sudo` — la riga di /etc/hosts si stampa, non si scrive. È la dottrina di
#     `fcn-trust-ca.sh`, che stampa il comando di sistema invece di eseguirlo.
#   · installare Docker, npm, o aggiungere un repository apt: aggiungere una
#     sorgente di pacchetti alla macchina di qualcuno è un atto di quella persona.
#   · toccare i container: questo script non ne accende e non ne spegne nessuno.
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} /^[[:space:]]*$/{next} {exit}' "$0"; exit 0
fi
set -euo pipefail
cd "$(dirname "$0")"                     # stratigraph-server/dev-stack
. ./platform.sh

HTTPS_PORT="${HTTPS_PORT:-8443}"
LOCAL_S3D="no"; DRY="no"; ARG_HOST=""; FIELD="no"
for a in "$@"; do
  case "$a" in
    --local-s3d) LOCAL_S3D="yes" ;;
    --dry-run|-n) DRY="yes" ;;
    --field) FIELD="yes" ;;
    -*) echo "flag sconosciuto: $a (usa --local-s3d | --dry-run | --field)"; exit 2 ;;
    *) ARG_HOST="$a" ;;
  esac
done
#: il nome scelto una volta (`FCN_HOST` in .env.dev), come in fcn-up.sh; e su un
#: nodo da campo, senza niente, il nome di rete della macchina (`<host>.local`)
FCN_HOST_SAVED="$( [ -f .env.dev ] && grep -E '^FCN_HOST=' .env.dev | tail -1 | cut -d= -f2- || true)"
if [ -z "$ARG_HOST" ] && [ -z "$FCN_HOST_SAVED" ] && [ "$FIELD" = "yes" ]; then
  _h="$(sg_local_hostname)"; [ -n "$_h" ] && ARG_HOST="${_h}.local"
fi
PRIMARY="${ARG_HOST:-${FCN_HOST_SAVED:-em.localhost}}"
#: IN MINUSCOLO (31 ottobre 2026): il browser scrive l'host in minuscolo
#: («macbook-pro-di-emanuel.local») e Keycloak confronta le redirect URI come
#: stringhe, quindi un realm reso per «MacBook-Pro-di-Emanuel.local» — il nome
#: che `scutil` restituisce — rispondeva «Invalid parameter: redirect_uri» al
#: primo telefono. Un nome host non distingue maiuscole: lo si scrive una volta.
PRIMARY="$(printf '%s' "$PRIMARY" | tr '[:upper:]' '[:lower:]')"

#: Il conto di cosa è cambiato: serve per la frase finale, perché
#: «idempotente» vuol dire anche DIRE che non si è fatto niente.
CAMBIATO=0
GUAI=0
say()  { printf '%s\n' "$*"; }
ok()   { printf '  ✔ %s\n' "$*"; }
fatto(){ printf '  ✚ %s\n' "$*"; CAMBIATO=$((CAMBIATO+1)); }
male() { printf '  ✖ %s\n' "$*" >&2; GUAI=$((GUAI+1)); }
nota() { printf "      %s\n" "$*" >&2; }

say ""
say "▶ fcn-install · $(sg_os) · $(uname -m)"
[ "$DRY" = "yes" ] && say "  (--dry-run: non cambio niente)"
say ""

# ══ 1 · I REPOSITORY FRATELLI ════════════════════════════════════════════════
#
# PRIMO, perché è il controllo che sul Pi è arrivato ultimo. E costa un
# `test -d`.
#
# GLI INDIRIZZI STANNO IN UN POSTO SOLO. Quali cartelle servono lo dice il
# compose, con le sue `context:`; da dove si clonano lo dice `x-sibling-repos`
# nello STESSO file. Non c'è nessuna lista qui dentro da tenere allineata, e se
# un `context:` nuovo non ha il suo URL questo script lo dice invece di
# clonare il nulla.
# ══ 0 · IL SISTEMA, SOLO PER IL NODO DA CAMPO (31 ottobre 2026) ══════════════
#
# Per il dev-stack la dottrina resta quella scritta in testa: niente sudo, si
# stampa la riga. Per un NODO DA CAMPO no, e per una ragione precisa: chi lo
# installa è un archeologo che prepara una macchina dedicata, e «installa Docker
# da te, poi rientra, poi aggiungi una riga a /etc/hosts» sono tre posti dove
# fermarsi (E.D.: «l'install pensa lui a tutto»). `--field` è il consenso,
# scritto da chi lo lancia; sudo chiede la password una volta, e ogni passo dice
# cosa fa prima di farlo. Idempotente: quello che c'è già non si tocca.
if [ "$FIELD" = "yes" ] && [ "$DRY" != "yes" ]; then
  say "0 · il sistema (nodo da campo)"
  case "$(sg_os)" in
    linux)
      if ! command -v apt-get >/dev/null 2>&1; then
        male "questo Linux non ha apt: installa a mano Docker, git, python3 e avahi."
      else
        mancano=""
        for pkg in git curl python3 avahi-daemon; do
          dpkg -s "$pkg" >/dev/null 2>&1 || mancano="$mancano $pkg"
        done
        if [ -n "$mancano" ]; then
          say "  ⇣ installo:$mancano"
          sudo apt-get update -qq && sudo apt-get install -y -qq $mancano \
            && fatto "installati:$mancano" || male "apt non ha installato:$mancano"
        else
          ok "git, curl, python3, avahi"
        fi
        sudo systemctl enable --now avahi-daemon >/dev/null 2>&1 || true
        if ! command -v docker >/dev/null 2>&1; then
          say "  ⇣ installo Docker (lo script ufficiale, get.docker.com)…"
          curl -fsSL https://get.docker.com | sudo sh >/dev/null \
            && fatto "Docker installato" || male "l'installazione di Docker è fallita"
        else
          ok "docker"
        fi
        sudo systemctl enable --now docker >/dev/null 2>&1 || true
        if ! id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
          sudo usermod -aG docker "$USER" && fatto "$USER nel gruppo docker"
          #: il gruppo vale dalla prossima sessione: questa giro lo si
          #: riprende sotto il gruppo nuovo, così nessuno deve uscire e rientrare
          if command -v sg >/dev/null 2>&1 && [ -z "${FCN_REGROUPED:-}" ]; then
            say "  ↻ riprendo con il gruppo docker attivo…"
            export FCN_REGROUPED=1
            exec sg docker -c "$(printf '%q ' "$0" "$@")"
          fi
        fi
        if ! getent hosts em.localhost >/dev/null 2>&1; then
          echo "127.0.0.1 em.localhost" | sudo tee -a /etc/hosts >/dev/null \
            && fatto "em.localhost in /etc/hosts"
        fi
      fi
      ;;
    macos)
      if ! command -v brew >/dev/null 2>&1; then
        male "su questo Mac manca Homebrew: installalo da https://brew.sh, poi rilancia."
      else
        mancano=""
        for f in git colima docker docker-compose; do
          command -v "$f" >/dev/null 2>&1 || mancano="$mancano $f"
        done
        if [ -n "$mancano" ]; then
          say "  ⇣ brew install$mancano"
          brew install $mancano && fatto "installati:$mancano" || male "brew non ha installato:$mancano"
        else
          ok "git, colima, docker, docker-compose"
        fi
      fi
      ;;
    *) male "il nodo da campo si installa su Linux o su macOS." ;;
  esac
  say ""
fi

say "1 · i repository affiancati"

#: I `context:` risolti in percorsi assoluti — li stampa compose, che è la cosa
#: che poi userà quei percorsi. Misurato: funziona su un clone in cui i fratelli
#: NON ci sono ancora e `.env.dev` non esiste, che è esattamente il momento in
#: cui serve.
sg_compose_array || exit 1
#: UNA lettura del compose per tutto: i `context:` e la mappa nome→URL vengono
#: dalla stessa stampa. Erano due chiamate a `config`, che è la stessa domanda
#: fatta due volte.
reso="$("${COMPOSE[@]}" -f docker-compose.dev.yml config 2>/dev/null || true)"
contesti="$(printf '%s\n' "$reso" \
            | sed -n 's/^[[:space:]]*context:[[:space:]]*//p' | sort -u)"
if [ -z "$contesti" ]; then
  male "non riesco a leggere i \`context:\` dal compose."
  nota "\`${COMPOSE[*]} -f docker-compose.dev.yml config\` non ha stampato niente:"
  nota "senza quello non so quali repository servono, e non tiro a indovinare."
  exit 1
fi

#: e la mappa nome→URL, dallo stesso file
urls="$(printf '%s\n' "$reso" \
        | awk '/^x-sibling-repos:/{f=1;next} f&&/^[^[:space:]]/{f=0} f' \
        | sed -n 's/^[[:space:]]*\([^:]*\):[[:space:]]*\(.*\)$/\1 \2/p')"

#: EMStudio, SEMPRE — e con un'eccezione dichiarata, come s3Dgraphy qui sotto,
#: perché non ha un `context:` da cui dedurlo: non si costruisce come immagine.
#: Ma il catalogo ne monta la `dist` e Caddy ne instrada il dev server, quindi
#: è una dipendenza della stack quanto gli altri tre. L'URL resta in
#: `x-sibling-repos`; qui si aggiunge solo la cartella.
RADICE="$(cd .. && cd .. && pwd)"
EMSTUDIO="$RADICE/EMStudio"
contesti="$contesti
$EMSTUDIO"

#: con --local-s3d serve anche s3Dgraphy, che non ha un `context:` (è un volume
#: in docker-compose.local-s3d.yml). Un requisito in più, dichiarato dal flag.
if [ "$LOCAL_S3D" = "yes" ]; then
  contesti="$contesti
$RADICE/s3Dgraphy"
fi

for ctx in $contesti; do
  nome="$(basename "$ctx")"
  if [ -d "$ctx" ]; then
    ok "$nome"
    continue
  fi
  url="$(echo "$urls" | awk -v n="$nome" '$1==n{print $2; exit}')"
  if [ -z "$url" ]; then
    male "manca \`$nome\` ($ctx) e non so da dove clonarlo."
    nota "Il compose lo costruisce e \`x-sibling-repos\` non lo elenca:"
    nota "aggiungi la riga \`$nome: <url>\` là, accanto agli altri."
    continue
  fi
  if [ "$DRY" = "yes" ]; then
    fatto "clonerei $nome da $url"
    continue
  fi
  if ! command -v git >/dev/null 2>&1; then
    male "manca \`$nome\` e non c'è \`git\` per clonarlo."
    nota "Installa git, o clona a mano:  git clone $url \"$ctx\""
    continue
  fi
  #: `${nome}` CON LE GRAFFE, e non `$nome`, perché il carattere dopo è `…`.
  #: Trovato eseguendo, e il verso è il contrario di quello che si penserebbe:
  #:
  #:     LC_CTYPE=C            →  clono x…            (funziona)
  #:     LC_CTYPE=en_US.UTF-8  →  nome<?>: unbound variable
  #:     LC_CTYPE=C.UTF-8      →  nome<?>: unbound variable
  #:
  #: In una locale UTF-8 — cioè quella GIUSTA — bash 3.2 accetta i byte di `…`
  #: dentro il nome della variabile, e sotto `set -u` muore. Su una macchina
  #: senza locale funziona; su una configurata a modo, no. bash 5.2 (Debian 12,
  #: il Pi) non ha il difetto: quindi era un guasto che si sarebbe visto sul
  #: Mac di chi sviluppa e non sul nodo, cioè nel modo più lento da capire.
  #: Le graffe sono corrette in ogni locale e in ogni versione — misurato.
  say "  ⇣ clono ${nome}…"
  if git clone --depth 1 "$url" "$ctx"; then
    fatto "$nome clonato"
  else
    male "il clone di $nome è fallito."
    nota "A mano:  git clone $url \"$ctx\""
  fi
done

# ── 1-bis · EMStudio: le dipendenze e la dist del reader ─────────────────────
#
# Una cartella non basta. `fcn-up.sh` accende il dev server solo se
# `frontend/node_modules` c'è, e il catalogo monta `frontend/dist`: senza
# quella risponde 501 su `/study/{id}/narrative`. Tutti e due si fanno con npm,
# e npm NON lo installo io — è la stessa dottrina di Docker, qui sotto.
#
# Un `npm` che manca è un avviso e non un guaio: la stack sale lo stesso, e
# quello che si perde (l'editor, il reader, la narrativa) lo si dice per nome.
# Un nodo di campo non ha EMStudio, e fermargli l'installazione per questo
# vorrebbe dire non installarlo mai.
avviso(){ printf '  ⚠ %s\n' "$*" >&2; }
FRONTEND="$EMSTUDIO/frontend"
if [ "$FIELD" = "yes" ]; then
  #: un nodo da campo non serve l'editor dal suo dev server: niente npm
  ok "EMStudio: sul nodo da campo non serve il suo dev server (npm saltato)"
elif [ ! -d "$EMSTUDIO" ]; then
  #: in --dry-run (o se il clone è fallito) non c'è niente da guardare: il clone
  #: l'ha già detto sopra, e i due passi npm verranno al giro dopo
  [ "$DRY" = "yes" ] && nota "(dopo il clone: npm install e npm run build:reader in EMStudio/frontend)"
elif [ ! -f "$FRONTEND/package.json" ]; then
  avviso "\`$EMSTUDIO\` c'è ma non ha \`frontend/package.json\`: non lo tocco."
else
  serve_npm=""
  [ -d "$FRONTEND/node_modules" ] || serve_npm="install"
  [ -d "$FRONTEND/dist" ] || serve_npm="$serve_npm build:reader"
  if [ -z "$serve_npm" ]; then
    ok "EMStudio: node_modules e dist del reader"
  elif ! command -v npm >/dev/null 2>&1; then
    avviso "EMStudio vuole npm ($serve_npm) e su questa macchina npm non c'è."
    nota "Non lo installo: è una sorgente di pacchetti, e aggiungerla è un atto tuo."
    nota "Senza, \`fcn-up.sh\` non accende il dev server (/em/studio/ dà 502) e,"
    nota "senza dist, il catalogo risponde 501 sulla narrativa. Il resto sale."
  else
    if [ ! -d "$FRONTEND/node_modules" ]; then
      if [ "$DRY" = "yes" ]; then
        fatto "farei npm install in EMStudio/frontend"
      else
        say "  ⇣ npm install in EMStudio/frontend…"
        if (cd "$FRONTEND" && npm install); then
          fatto "EMStudio: node_modules installati"
        else
          male "npm install in EMStudio/frontend è fallito."
          nota "A mano:  cd \"$FRONTEND\" && npm install"
        fi
      fi
    fi
    if [ ! -d "$FRONTEND/dist" ]; then
      #: la ragione in una riga, perché un `build` durante un'installazione
      #: sembra un di più finché non si sa a chi serve
      if [ "$DRY" = "yes" ]; then
        fatto "farei npm run build:reader (senza dist il catalogo dà 501 sulla narrativa)"
      elif [ ! -d "$FRONTEND/node_modules" ]; then
        nota "build:reader saltato: senza node_modules non si costruisce."
      else
        say "  ⚙ npm run build:reader — senza dist il catalogo risponde 501 sulla narrativa…"
        if (cd "$FRONTEND" && npm run build:reader); then
          fatto "EMStudio: dist del reader costruita"
        else
          male "npm run build:reader in EMStudio/frontend è fallito."
          nota "A mano:  cd \"$FRONTEND\" && npm run build:reader"
        fi
      fi
    fi
  fi
fi

# ══ 2 · .env.dev ═════════════════════════════════════════════════════════════
#
# Il controllo in `fcn-up.sh` c'è dal 9 ottobre e sul Pi NON è mai scattato,
# perché l'avevamo prevenuto a mano. Qui si verifica che la sua frase sia quella
# giusta, e si arriva alla stessa conclusione un passo prima.
say ""
say "2 · l'ambiente"
if [ -f .env.dev ]; then
  ok ".env.dev"
elif [ "$FIELD" = "yes" ]; then
  ok ".env.dev lo scrive il passo dopo, ./fcn-field-setup.sh"
elif [ ! -f .env.dev.example ]; then
  male "non c'è né \`.env.dev\` né \`.env.dev.example\`: checkout incompleto."
else
  male "manca \`.env.dev\` (è in .gitignore: porta i valori riempiti)."
  nota "Per il dev-stack il modello va bene com'è. UNA riga:"
  nota ""
  nota "    cp .env.dev.example .env.dev"
  nota ""
  nota "Non lo copio io: dentro ci sono credenziali (senza valore, ma"
  nota "credenziali) e crearlo è un atto di una persona."
fi

# ══ 3 · DOCKER E UN COMPOSE ══════════════════════════════════════════════════
#
# `platform.sh` risponde a entrambe, e questo script NON le riscrive.
say ""
say "3 · docker"
if sg_docker_ready; then
  ok "docker risponde"
else
  #: `sg_ensure_docker` stampa il rimedio giusto per QUESTO sistema. Qui non lo
  #: si chiama per avviare niente su una macchina di qualcun altro: si chiama
  #: perché la sua frase è la frase giusta, e si registra il guaio.
  sg_ensure_docker || true
  male "docker non risponde (vedi sopra)."
fi
#: il compose l'ha già trovato il passo 1 — dirlo qui è dove chi legge lo cerca
ok "compose: ${COMPOSE[*]}"

# ══ 4 · em.localhost ═════════════════════════════════════════════════════════
#
# La predizione del 9 ottobre, confermata sul Pi: su Debian 12 la riga
# `hosts: files dns` non sintetizza `*.localhost`, e la stack sale con ogni
# container sano e ogni pagina morta.
say ""
say "4 · il nome su cui gira tutto"
risolve="no"
case "$(sg_os)" in
  macos) ping -c1 -t1 em.localhost >/dev/null 2>&1 && risolve="si" ;;
  *)     getent hosts em.localhost >/dev/null 2>&1 && risolve="si" ;;
esac
if [ "$risolve" = "si" ]; then
  ok "em.localhost si risolve"
else
  male "\`em.localhost\` NON si risolve su questa macchina."
  nota "Non è un guasto della stack: è la pila NSS. Su Debian/Ubuntu la riga"
  nota "\`hosts: files dns\` di fabbrica non sintetizza \`*.localhost\`."
  nota "Senza questo, la stack sale con tutti i container sani e OGNI pagina"
  nota "morta — il modo più confondente di fallire."
  nota ""
  nota "    echo \"127.0.0.1 em.localhost\" | sudo tee -a /etc/hosts"
  nota ""
  nota "Non la scrivo io: \`/etc/hosts\` è di sistema e questo script non fa sudo."
fi

# ══ 5 · IL NOME PRIMARIO, E IL REALM ═════════════════════════════════════════
say ""
say "5 · l'host primario"
if [ "$PRIMARY" = "em.localhost" ]; then
  ok "nessun host primario: si userà em.localhost (nessun realm da rendere)"
else
  #: Si RENDE qui, così un nome che il realm non sa imparare lo si scopre adesso
  #: e non dopo `up` — che è la forma del guasto misurato sul Pi: TLS a posto,
  #: pagina che arriva, e il login che muore per ultimo.
  if [ "$DRY" = "yes" ]; then
    fatto "renderei il realm per $PRIMARY"
  else
    set +e
    python3 render_realm.py --host "$PRIMARY" --porta "$HTTPS_PORT" --zitto \
            --out "keycloak/realm-em-dev.${PRIMARY}.json"
    rc=$?
    set -e
    case "$rc" in
      0) fatto "realm reso per $PRIMARY (redirect URI rispecchiate)" ;;
      3) ok "il realm già copre $PRIMARY" ;;
      *) male "il realm non può imparare \`$PRIMARY\` (vedi sopra)."
         nota "Caddy servirebbe quel nome e il login morirebbe con «Invalid"
         nota "parameter: redirect_uri» DOPO che tutto il resto ha funzionato." ;;
    esac
  fi
fi

# ══ E ADESSO ═════════════════════════════════════════════════════════════════
say ""
if [ "$GUAI" -gt 0 ]; then
  say "✖ $GUAI cosa/e da sistemare prima di accendere. Nessun pull è stato fatto."
  say "  (È il punto: sul Pi lo stesso guaio è comparso dopo cinque immagini"
  say "   scaricate. Qui costa niente.)"
  exit 1
fi
if [ "$CAMBIATO" -eq 0 ]; then
  say "✔ tutto già a posto: non ho cambiato niente."
else
  say "✔ pronto ($CAMBIATO cosa/e preparate)."
fi
say ""
if [ "$FIELD" = "yes" ] && ! grep -qE '^EM_NODE_KIND=field' .env.dev 2>/dev/null; then
  say "  Adesso, una volta sola (il tuo ORCID, il nome del nodo, l'avvio automatico):"
  say "    ./fcn-field-setup.sh"
  say "  e poi:"
  say "    ./fcn-up.sh"
else
  say "  Adesso:   ./fcn-up.sh$( [ "$PRIMARY" != "em.localhost" ] && [ "$PRIMARY" != "$FCN_HOST_SAVED" ] && echo " $PRIMARY" )$( [ "$LOCAL_S3D" = "yes" ] && echo " --local-s3d" )"
  say "  E la CA, una volta sola:   ./fcn-trust-ca.sh"
fi
say ""
