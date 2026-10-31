#!/usr/bin/env bash
# fcn-get — il PRIMO comando di un nodo da campo: scarica il codice e installa.
#
#   curl -fsSL https://raw.githubusercontent.com/StratiGraph-ECCCH/stratigraph-server/main/dev-stack/fcn-get.sh | bash
#
# E.D., 31 ottobre 2026: «anche scaricare il codice è parte della procedura; si
# clona con un comando e l'install pensa lui a tutto». Questo script fa due
# cose e poi passa la mano:
#
#   1 · il codice: `stratigraph-server` in ~/stratigraph (o in $STRATIGRAPH_HOME),
#       clonato la prima volta, aggiornato le volte dopo (solo fast-forward: un
#       nodo con modifiche locali lo DICE invece di inventare una fusione);
#   2 · `fcn-install.sh --field`, che installa quello che manca al sistema,
#       scarica i repository compagni e controlla tutto.
#
# Rilanciarlo è il modo di aggiornare il nodo, a casa, con la rete.
# Poi, una volta sola: ./fcn-field-setup.sh — e da lì in avanti ./fcn-up.sh.
set -euo pipefail

REPO="${STRATIGRAPH_REPO:-https://github.com/StratiGraph-ECCCH/stratigraph-server.git}"
DOVE="${STRATIGRAPH_HOME:-$HOME/stratigraph}"
SERVER="$DOVE/stratigraph-server"

echo ""
echo "▶ StratiGraph · nodo da campo · il codice in $DOVE"

if ! command -v git >/dev/null 2>&1; then
  case "$(uname -s)" in
    Linux)
      echo "  ⇣ git non c'è: lo installo (sudo apt-get install git)…"
      sudo apt-get update -qq && sudo apt-get install -y -qq git ;;
    Darwin)
      echo "  ✖ git non c'è: su un Mac lo dà «xcode-select --install» (o Homebrew)," >&2
      echo "    poi rilancia questo comando." >&2
      exit 1 ;;
    *) echo "  ✖ git non c'è, e non so installarlo su questo sistema." >&2; exit 1 ;;
  esac
fi

mkdir -p "$DOVE"
if [ -d "$SERVER/.git" ]; then
  echo "  ↻ aggiorno stratigraph-server…"
  git -C "$SERVER" pull --ff-only --quiet || {
    echo "  ✖ stratigraph-server ha modifiche locali o si è allontanato da GitHub:" >&2
    echo "    non lo fondo io. Guarda con: git -C \"$SERVER\" status" >&2
    exit 1
  }
else
  echo "  ⇣ scarico stratigraph-server…"
  git clone --quiet "$REPO" "$SERVER"
fi
echo "  ✔ $(git -C "$SERVER" log -1 --format='%h %s' | cut -c1-70)"

#: gli altri repository del nodo, se ci sono già: aggiornati allo stesso modo
#: (quelli che mancano li clona fcn-install, che sa dal compose quali servono)
for altro in stratigraph-chatbot stratigraph-catalog; do
  if [ -d "$DOVE/$altro/.git" ]; then
    git -C "$DOVE/$altro" pull --ff-only --quiet \
      && echo "  ✔ $altro aggiornato" \
      || echo "  ⚠ $altro non si aggiorna da solo (modifiche locali?): lo lascio com'è" >&2
  fi
done

cd "$SERVER/dev-stack"
#: `< /dev/tty`: quando questo script arriva da `curl … | bash`, il suo stdin è
#: la pipe; l'installazione può chiedere (la password di sudo, per esempio) e
#: deve chiederlo alla persona, non alla pipe
#: …e solo se un terminale c'è DAVVERO: `-r /dev/tty` è vero anche dentro una
#: sessione senza terminale (ssh senza -t, un servizio), dove poi aprirlo
#: fallisce. Misurato sul Pi il 31 ottobre 2026; la prova è aprirlo.
if (: < /dev/tty) 2>/dev/null; then
  exec ./fcn-install.sh --field "$@" < /dev/tty
fi
exec ./fcn-install.sh --field "$@"
