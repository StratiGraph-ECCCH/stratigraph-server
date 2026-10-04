# platform.sh — che macchina è questa, e cosa serve davvero accendere.
#
# Sourced, non eseguito:  . "$(dirname "$0")/platform.sh"
#
# ════════════════════════════════════════════════════════════════════════════
# ## PERCHÉ ESISTE, E IL MOTIVO NON È TEORICO
#
# Nicolò Paraciani non ha un Mac, e deve potersi fare un'idea dei servizi **come
# amministratore** — la console del nodo, la salute, lo storage. Misurato il
# 7 ottobre 2026, prima di qualunque package manager:
#
#     fcn-up.sh:39      `colima status` chiamato SEMPRE, senza chiedersi dove gira
#     fcn-up.sh:47      `scutil --get LocalHostName`, macOS e basta
#     fcn-down.sh:53    `colima stop`, idem
#     fcn-trust-ca.sh:30  `sudo security add-trusted-cert`, il portachiavi di macOS
#
# Su Linux Docker gira nativo e colima non serve. Su Windows colima non esiste, e
# lo script gira in WSL o in Git Bash — ma il browser che deve fidarsi della CA
# è quello di **Windows**: due negozi di certificati diversi, ed è la trappola
# che nessuno vede finché non ci sbatte.
#
# ## LA REGOLA: RILEVARE, NON ASSUMERE
#
# E per Docker la domanda vera non è «che sistema è questo» ma **«docker
# risponde?»**. `sg_docker_ready` la fa; colima resta il RIMEDIO su macOS quando
# la risposta è no, non un passo obbligatorio prima di averla chiesta.
#
# ## NESSUN PACKAGE MANAGER
#
# Non brew, non chocolatey: chiedono diritti di amministratore su un portatile
# istituzionale, ed è il punto in cui un IT dice di no. Sull'host servono Docker
# e una shell; tutto il resto è già nei container.

#: Che sistema è questo — `macos` | `linux` | `wsl` | `windows` | `unknown`.
#:
#: `wsl` è separato da `linux` di proposito: `uname -s` dice `Linux` e i comandi
#: sono quelli di Linux, ma il BROWSER è di Windows e la CA va aggiunta dall'altro
#: lato. Chiamarlo `linux` sarebbe la risposta giusta a una domanda diversa.
sg_os() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    Darwin) echo macos ;;
    Linux)
      #: `/proc/version` porta «microsoft» sotto WSL1 e WSL2. `WSL_DISTRO_NAME`
      #: è più leggibile ma non c'è quando lo script è lanciato da un servizio.
      if [ -n "${WSL_DISTRO_NAME:-}" ] || \
         grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then
        echo wsl
      else
        echo linux
      fi
      ;;
    MINGW*|MSYS*|CYGWIN*) echo windows ;;
    *) echo unknown ;;
  esac
}

#: Docker risponde? La domanda che decide, e l'unica che non dipende dal sistema.
sg_docker_ready() { docker info >/dev/null 2>&1; }

#: Il nome Bonjour di questa macchina, o "" — su macOS `scutil`, altrove il
#: nome che l'host dichiara. Mai un IP: la CA interna di Caddy non fa
#: certificati per un IP nudo.
sg_local_hostname() {
  case "$(sg_os)" in
    macos) scutil --get LocalHostName 2>/dev/null || true ;;
    linux|wsl)
      #: `hostname -s` c'è su ogni distribuzione; `hostnamectl` no (systemd).
      hostname -s 2>/dev/null || true
      ;;
    *) echo "" ;;
  esac
}

#: Assicura che Docker risponda, con il rimedio giusto per QUESTA macchina.
#: Ritorna 0 quando risponde, 1 quando non c'è niente da fare da qui.
sg_ensure_docker() {
  if sg_docker_ready; then return 0; fi
  case "$(sg_os)" in
    macos)
      #: colima SOLO qui, e solo perché la risposta è stata no. Se non è
      #: installato lo si dice invece di far fallire un `command not found`
      #: dentro un `if`.
      if command -v colima >/dev/null 2>&1; then
        echo "▶ Docker non risponde: avvio Colima…"
        colima start --cpu 4 --memory 8 --network-address
        docker context use colima >/dev/null 2>&1 || true
        sg_docker_ready && return 0
      fi
      echo "✖ Docker non risponde su questo Mac." >&2
      echo "  Avvia Colima (\`colima start\`) o Docker Desktop, poi rilancia." >&2
      return 1
      ;;
    linux)
      echo "✖ Docker non risponde." >&2
      echo "  Su Linux il demone è di sistema: \`sudo systemctl start docker\`," >&2
      echo "  e l'utente deve stare nel gruppo \`docker\` (\`sudo usermod -aG docker \$USER\`," >&2
      echo "  poi riapri la sessione). NIENTE colima: qui non serve." >&2
      return 1
      ;;
    wsl)
      echo "✖ Docker non risponde dentro WSL." >&2
      echo "  Due strade, e sono diverse:" >&2
      echo "   · Docker Desktop su Windows, con l'integrazione WSL accesa per" >&2
      echo "     questa distribuzione (Settings → Resources → WSL integration);" >&2
      echo "   · oppure il demone dentro la distribuzione:" >&2
      echo "     \`sudo service docker start\`." >&2
      return 1
      ;;
    windows)
      echo "✖ Docker non risponde." >&2
      echo "  Questa shell è Git Bash/MSYS: serve Docker Desktop avviato su" >&2
      echo "  Windows. NIENTE colima: su Windows non esiste." >&2
      return 1
      ;;
    *)
      echo "✖ Docker non risponde, e non riconosco questo sistema" \
           "($(uname -s 2>/dev/null))." >&2
      return 1
      ;;
  esac
}

#: Quale compose c'è su QUESTA macchina — stampato in una riga, per riempire un
#: array. `docker compose` (il plugin) prima, `docker-compose` (il binario
#: autonomo) come ripiego. Ritorna 1 quando non c'è nessuno dei due.
#:
#: ## PERCHÉ LA SONDA È `docker compose version` E NON `command -v docker`
#:
#: Misurato sul Mac di E.D. il 9 ottobre 2026:
#:
#:     docker compose version  → docker: unknown command: docker compose
#:     docker-compose version  → Docker Compose version 5.3.0
#:
#: `docker` C'È e il sottocomando NO. Una sonda che guarda il binario `docker`
#: direbbe «plugin presente» su questa macchina e costruirebbe un comando che
#: non esiste. L'unica domanda che risponde è chiedere al sottocomando di
#: presentarsi.
#:
#: ## E IL RIPIEGO NON È NECESSARIAMENTE IL LEGACY
#:
#: L'ordine resta `docker compose` prima, perché è quello che una macchina nuova
#: installa. Ma il ripiego non si chiama «vecchio» in una frase all'utente: qui
#: il `docker-compose` di Homebrew è **Compose 5.3.0**, un binario autonomo
#: corrente, e sull'unica macchina su cui questa stack è mai salita è il ramo
#: che FUNZIONA. Preferire l'altro è una scelta sul futuro, non un giudizio su
#: quello che c'è.
sg_compose() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
    return 0
  fi
  echo "✖ Nessun Docker Compose su questa macchina." >&2
  echo "  Ho cercato, in quest'ordine:" >&2
  echo "   · \`docker compose\` — il plugin, quello che installano Docker" >&2
  echo "     Engine su Linux e Docker Desktop su Windows/macOS;" >&2
  echo "   · \`docker-compose\` — il binario autonomo." >&2
  echo "  Non c'è nessuno dei due. Se \`docker\` risponde ma il plugin manca," >&2
  echo "  è il pacchetto \`docker-compose-plugin\` (o \`docker-compose-v2\`)." >&2
  return 1
}

#: Riempie l'array `COMPOSE` col comando trovato. Esiste perché la parte
#: sbagliata è facilissima da scrivere:
#:
#:     COMPOSE=("$(sg_compose)")       # UN elemento con uno spazio dentro →
#:                                     # cerca un eseguibile chiamato
#:                                     # "docker compose" e non lo trova
#:
#: e perché `mapfile`, che sarebbe la risposta ovvia, **non esiste** nella bash
#: che gira questi script sul Mac di E.D.: misurato, GNU bash 3.2.57, dove
#: `mapfile` è un comando sconosciuto. `read -r -a` c'è da sempre.
#:
#: Uso:  sg_compose_array || exit 1   →  poi "${COMPOSE[@]}"
sg_compose_array() {
  local trovato
  trovato="$(sg_compose)" || return 1
  #: IFS locale: splitta sullo spazio e su nient'altro, e non lo lascia
  #: cambiato per il resto dello script.
  local IFS=' '
  read -r -a COMPOSE <<< "$trovato"
}

#: `.env.dev` c'è? Se no lo dice — la riga da incollare compresa — e ritorna 1.
#:
#: Era dentro `fcn-up.sh` (9 ottobre 2026: un clone fresco moriva con
#: «couldn't find env file»). Sta qui dal 3 ottobre perché lo vuole anche
#: `bump-s3dgraphy.sh --build`, che il 2 ottobre ha ricreato il server SENZA
#: `--env-file`: niente chiavi di MinIO, e il server è andato in crash a
#: ripetizione. Due script, un solo messaggio. Va chiamata da `dev-stack/`.
sg_need_env_dev() {
  [ -f .env.dev ] && return 0
  echo "✖ Manca \`dev-stack/.env.dev\`, e \`--env-file\` lo vuole." >&2
  if [ -f .env.dev.example ]; then
    echo "  È in .gitignore di proposito: porta i valori riempiti. Il modello c'è," >&2
    echo "  e per il dev-stack va bene così com'è:" >&2
    echo >&2
    echo "      cp .env.dev.example .env.dev" >&2
    echo >&2
    echo "  (dentro ci sono minioadmin/minioadmin e un realm em-dev: valori che" >&2
    echo "   sarebbero una vulnerabilità su qualcosa di raggiungibile.)" >&2
  else
    echo "  E non trovo nemmeno \`.env.dev.example\`: questo checkout è incompleto." >&2
  fi
  return 1
}

#: L'indirizzo di questa macchina sulla LAN, o "". Serve SOLO come ripiego da
#: stampare quando un nome non regge — mai come indirizzo da usare: la CA
#: interna di Caddy non firma per un IP nudo, quindi con l'IP il TLS non
#: funziona e il nome serve comunque. È per la riga di `/etc/hosts` da mettere
#: sull'ALTRA macchina.
#:
#: Rilevato, non assunto: `ipconfig getifaddr` su macOS (che vuole il nome
#: dell'interfaccia, e quello lo chiede a `route`), `ip route get` su Linux e
#: WSL. Mai `hostname -I`, che su una macchina con Docker elenca anche gli
#: indirizzi dei bridge e ne dà uno che nessun altro può raggiungere.
sg_lan_ip() {
  case "$(sg_os)" in
    macos)
      local iface
      iface="$(route -n get 1.1.1.1 2>/dev/null \
               | awk '/interface:/{print $2; exit}')"
      [ -n "$iface" ] && ipconfig getifaddr "$iface" 2>/dev/null || true
      ;;
    linux|wsl)
      #: `src` è l'indirizzo che il kernel userebbe per uscire: quello vero.
      ip route get 1.1.1.1 2>/dev/null \
        | sed -n 's/.*[[:space:]]src[[:space:]]\([0-9.]*\).*/\1/p' | head -1
      ;;
    *) echo "" ;;
  esac
}

#: Un indirizzo https risponde? Stampa `si` | `nome` | `muto` e ritorna 0/1.
#:
#:   si     ha risposto
#:   nome   il nome non si risolve       (curl 6)
#:   muto   si risolve e non risponde    (tutto il resto)
#:
#: Tre esiti e non due, perché sono tre frasi diverse da dire a chi legge — e
#: perché «non risolve» è la sola per cui il rimedio è una riga di `/etc/hosts`
#: e non un container da guardare.
#:
#: `-k`: qui si misura la RAGGIUNGIBILITÀ, non la fiducia nella CA — quella ha
#: già la sua sonda, senza `-k`, alla fine di `fcn-up.sh`.
sg_reaches() {
  local url="$1" rc
  curl -sk -o /dev/null --max-time "${2:-4}" "$url"; rc=$?
  case "$rc" in
    0)  echo si;   return 0 ;;
    6)  echo nome; return 1 ;;
    *)  echo muto; return 1 ;;
  esac
}

# ════════════════════════════════════════════════════════════════════════════
# ## L'ANNUNCIO SULLA RETE LOCALE (`_stratigraph._tcp`)
#
# Misurato il 4 ottobre 2026: il Pi pubblica con avahi il NOME `fcn.local`, non
# un servizio, e il cercatore di nodi di s3Dgraphy (`tools/node_finder`,
# `dns-sd -B` / `avahi-browse -rpt _stratigraph._tcp`) non lo trovava. Il nodo
# personale (`scripts/personal_node.py --lan`) si annuncia già così; qui lo
# stesso meccanismo per lo stack, e SOLO quando `fcn-up.sh` riceve un host
# primario (cioè è stato aperto «per l'altro computer").
#
# La porta è quella di Caddy (https) e l'API sta sotto `/em`: il TXT lo dice
# (`scheme=https path=/em`), e `node_finder.url_of` lo legge — senza, il
# cercatore avrebbe costruito `http://host:8443`, che non risponde mai.
# Nessuna dipendenza nuova: `dns-sd` c'è su macOS, `avahi-publish` sui Linux
# con avahi (il Pi); senza nessuno dei due si dice e si va avanti.

SG_ANNOUNCE_SERVICE="_stratigraph._tcp"

#: Dove sta il pid dell'annuncio: fuori dal repository, sotto `$HOME` (le prove
#: girano con un `HOME` finto, quindi non possono fermare un annuncio vero), e
#: lo legge `fcn-down.sh`. `SG_ANNOUNCE_PIDFILE` lo sostituisce.
sg_announce_pidfile() { echo "${SG_ANNOUNCE_PIDFILE:-${HOME:-/tmp}/.cache/stratigraph/fcn-announce.pid}"; }

#: Il comando che annuncia, una parola per riga; ritorna 1 (e non stampa
#: niente) se questa macchina non ha né `dns-sd` né `avahi-publish`.
#:   sg_announce_cmd NOME PORTA PERCORSO SCHEMA
sg_announce_cmd() {
  local name="$1" port="$2" path="${3:-/}" scheme="${4:-https}"
  if command -v dns-sd >/dev/null 2>&1; then
    printf '%s\n' dns-sd -R "$name" "$SG_ANNOUNCE_SERVICE" local. "$port" \
      "path=$path" "scheme=$scheme"
  elif command -v avahi-publish >/dev/null 2>&1; then
    printf '%s\n' avahi-publish -s "$name" "$SG_ANNOUNCE_SERVICE" "$port" \
      "path=$path" "scheme=$scheme"
  else
    return 1
  fi
}

#: Ferma l'annuncio acceso da un `fcn-up.sh` precedente (se c'è). Silenzioso
#: quando non c'è niente da fermare; ritorna 0 sempre.
sg_announce_stop() {
  local pf pid
  pf="$(sg_announce_pidfile)"
  [ -f "$pf" ] || return 0
  pid="$(cat "$pf" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    echo "· annuncio ${SG_ANNOUNCE_SERVICE} fermato (pid $pid)."
  fi
  rm -f "$pf"
  return 0
}

#: Accende l'annuncio in background e scrive il pid. Stampa una frase in ogni
#: caso: annunciato, o perché no.
#:   sg_announce_start NOME PORTA PERCORSO SCHEMA
sg_announce_start() {
  local cmd=() line pid
  sg_announce_stop >/dev/null
  while IFS= read -r line; do cmd+=("$line"); done < <(sg_announce_cmd "$@" || true)
  if [ "${#cmd[@]}" -eq 0 ]; then
    echo "· nessun annuncio sulla rete locale: questa macchina non ha né dns-sd né"
    echo "  avahi-publish (gli altri ti trovano solo scrivendo l'indirizzo)."
    return 0
  fi
  nohup "${cmd[@]}" >/dev/null 2>&1 &
  pid=$!
  mkdir -p "$(dirname "$(sg_announce_pidfile)")" 2>/dev/null || true
  echo "$pid" > "$(sg_announce_pidfile)"
  echo "· annunciato sulla rete locale come «$1» (${SG_ANNOUNCE_SERVICE}, ${cmd[0]}, pid $pid)."
}
