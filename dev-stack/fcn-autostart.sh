#!/usr/bin/env bash
# fcn-autostart — il nodo si accende da solo quando si accende la macchina.
#
#   ./fcn-autostart.sh on       # da ora in poi, a ogni accensione
#   ./fcn-autostart.sh off      # non più
#   ./fcn-autostart.sh status   # com'è adesso
#
# E.D., 31 ottobre 2026: «la macchina si spegne la sera sul cantiere o comunque
# si scollega: come torna online da sola?». Così:
#
#   · Linux (il Raspberry Pi): un servizio di systemd, `stratigraph-fcn`, che
#     dopo Docker lancia `./fcn-up.sh --offline` con l'utente che lo ha
#     installato. `--offline` vuol dire niente build (senza rete una build si
#     ferma) e niente dev server: le immagini le ha fatte il primo avvio, a
#     casa. Si spegne con la macchina: Docker ferma i container con garbo, e i
#     dati restano sui volumi.
#   · macOS: un LaunchAgent dell'utente, che parte al login (sul Mac del
#     cantiere conviene il login automatico: Impostazioni → Utenti e gruppi).
#
# Il nome del nodo lo legge fcn-up.sh da `.env.dev` (`FCN_HOST`), quindi qui
# non c'è niente da ripetere. Il registro dell'ultimo avvio: dev-stack/fcn-boot.log
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] || [ -z "${1:-}" ]; then
  awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} /^[[:space:]]*$/{next} {exit}' "$0"; exit 0
fi
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
. ./platform.sh

UNIT="stratigraph-fcn"
UNIT_FILE="/etc/systemd/system/${UNIT}.service"
PLIST="$HOME/Library/LaunchAgents/org.stratigraph.fcn.plist"
LOG="$HERE/fcn-boot.log"

linux_on() {
  local who; who="$(id -un)"
  sudo tee "$UNIT_FILE" >/dev/null <<EOF
[Unit]
Description=StratiGraph field node (fcn-up.sh --offline)
After=docker.service network-online.target avahi-daemon.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=${who}
WorkingDirectory=${HERE}
ExecStart=/bin/bash -c './fcn-up.sh --offline >${LOG} 2>&1'
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable "$UNIT" >/dev/null 2>&1
  echo "✔ all'accensione il nodo parte da solo (servizio ${UNIT}, utente ${who})."
  echo "  Registro dell'ultimo avvio: ${LOG}"
}

linux_off() {
  sudo systemctl disable "$UNIT" >/dev/null 2>&1 || true
  sudo rm -f "$UNIT_FILE"
  sudo systemctl daemon-reload
  echo "✔ avvio automatico tolto. Il nodo si accende con ./fcn-up.sh"
}

linux_status() {
  if systemctl is-enabled "$UNIT" >/dev/null 2>&1; then
    echo "acceso: il nodo parte all'accensione ($(systemctl is-active "$UNIT" 2>/dev/null || true))"
  else
    echo "spento: il nodo si accende con ./fcn-up.sh"
  fi
}

mac_on() {
  mkdir -p "$(dirname "$PLIST")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>org.stratigraph.fcn</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-lc</string>
    <string>cd '${HERE}' &amp;&amp; ./fcn-up.sh --offline</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>${LOG}</string>
  <key>StandardErrorPath</key><string>${LOG}</string>
</dict></plist>
EOF
  launchctl unload "$PLIST" >/dev/null 2>&1 || true
  launchctl load "$PLIST"
  echo "✔ al login il nodo parte da solo. Registro: ${LOG}"
}

mac_off() {
  launchctl unload "$PLIST" >/dev/null 2>&1 || true
  rm -f "$PLIST"
  echo "✔ avvio automatico tolto. Il nodo si accende con ./fcn-up.sh"
}

mac_status() {
  [ -f "$PLIST" ] && echo "acceso: il nodo parte al login" || echo "spento: il nodo si accende con ./fcn-up.sh"
}

case "$(sg_os):$1" in
  linux:on) linux_on ;;  linux:off) linux_off ;;  linux:status) linux_status ;;
  macos:on) mac_on ;;    macos:off) mac_off ;;    macos:status) mac_status ;;
  *:on|*:off|*:status) echo "✖ l'avvio automatico c'è per Linux e macOS." >&2; exit 1 ;;
  *) echo "✖ usa: on | off | status" >&2; exit 2 ;;
esac
