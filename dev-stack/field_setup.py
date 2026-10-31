#!/usr/bin/env python3
"""Prepara un NODO DA CAMPO: la configurazione, in un comando (E.D., 31 ott 2026).

    ./fcn-field-setup.sh            # chiede: ORCID, nome, nome del nodo, client ORCID, avvio automatico
    ./fcn-field-setup.sh --orcid 0000-0002-1825-0097 --name "Nome Cognome" \
        --node-name scavo-2027 --host scavo-mac.local --no-autostart

La guida del nodo da campo aveva due passi che un archeologo non dovrebbe fare
a mano: cambiare i segreti di sviluppo in `.env.dev` prima del primo avvio, e
spegnere uno per uno, nella console di Keycloak, i cinque account dimostrativi.
Questo script fa il primo e prepara il secondo (il realm del campo nasce senza
account: `render_realm.py --campo`, chiamato da `fcn-up.sh`).

COSA SCRIVE, e solo questo:

* `.env.dev` — lo crea da `.env.dev.example` se manca. Poi:
    · i SEGRETI (`KEYCLOAK_ADMIN_PASSWORD`, `RUSTFS_ACCESS_KEY`,
      `RUSTFS_SECRET_KEY`, `DEV_CLIENT_SECRET`) li genera SOLO dove c'è ancora
      il valore di sviluppo. Un segreto già cambiato non si tocca: rilanciare lo
      script non rompe un nodo che funziona;
    · il TIPO e il GESTORE: `EM_NODE_KIND=field`, `EM_ALLOW_TEST_PEOPLE=0`,
      `DEV_OPERATOR_ORCID` e `DEV_CURATOR_ORCID` = l'iD dato, `EM_NODE_NAME`;
    · `ORCID_ISSUER=https://orcid.org` se nessuno l'ha scelto (il default del
      dev-stack è la sandbox).
* `accredited.field.yaml` — la lista del nodo, con il gestore. Se c'è già, il
  gestore si aggiunge e gli altri restano.

COSA NON FA, MAI: stampare un segreto (dice dove sta), avviare o fermare
container, scrivere fuori da `dev-stack/`.

UNA CAUTELA, misurata e non supposta: la password dell'amministratore di
Keycloak vale quando il suo database nasce. Se il volume del nodo da campo
esiste già, quella password NON si rigenera (il nodo continuerebbe a usare la
vecchia, e la console non saprebbe più parlargli): lo script lo dice.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

HERE = pathlib.Path(__file__).resolve().parent

#: i valori di sviluppo, come stanno in `.env.dev.example` (e, per il client,
#: nel realm committato): dove c'è ancora uno di questi, il segreto si genera.
DEV_DEFAULTS = {
    "KEYCLOAK_ADMIN_PASSWORD": {"admin", ""},
    "RUSTFS_ACCESS_KEY": {"em-dev-s3", ""},
    "RUSTFS_SECRET_KEY": {"em-dev-s3-secret", ""},
    "DEV_CLIENT_SECRET": {"em-dev-secret", ""},
}

#: il volume dove Keycloak tiene i suoi dati sul nodo da campo
#: (`docker-compose.field.yml`; il progetto compose si chiama `em-dev`)
KC_VOLUME = "em-dev_keycloak_field_data"
#: …e quello del file store: le sue chiavi valgono per i dati che ci sono
RUSTFS_VOLUME = "em-dev_rustfs_data"

#: quale volume «fissa» ciascun segreto: se esiste già, il segreto resta
BORN_WITH = {"KEYCLOAK_ADMIN_PASSWORD": KC_VOLUME, "DEV_CLIENT_SECRET": KC_VOLUME,
             "RUSTFS_ACCESS_KEY": RUSTFS_VOLUME, "RUSTFS_SECRET_KEY": RUSTFS_VOLUME}


def orcid_ok(text: str) -> Optional[str]:
    """L'iD normalizzato se la cifra di controllo torna (ISO 7064 11,2)."""
    raw = re.sub(r"[^0-9Xx]", "", text or "").upper()
    if len(raw) != 16 or not raw[:15].isdigit():
        return None
    total = 0
    for ch in raw[:15]:
        total = (total + int(ch)) * 2
    check = (12 - total % 11) % 11
    if raw[15] != ("X" if check == 10 else str(check)):
        return None
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def read_env(path: pathlib.Path) -> Tuple[List[str], Dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    values: Dict[str, str] = {}
    for line in lines:
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if m:
            values[m.group(1)] = m.group(2)
    return lines, values


def set_env(lines: List[str], key: str, value: str) -> List[str]:
    """Sostituisce l'ULTIMA riga attiva di `key` (è quella che vale), o ne
    aggiunge una in fondo. I commenti restano dove sono."""
    for i in range(len(lines) - 1, -1, -1):
        if re.match(rf"^{key}=", lines[i]):
            lines[i] = f"{key}={value}"
            return lines
    lines.append(f"{key}={value}")
    return lines


def volume_exists(name: str) -> Optional[bool]:
    """None quando docker non risponde: lo script non indovina."""
    if not shutil.which("docker"):
        return None
    try:
        out = subprocess.run(["docker", "volume", "inspect", name], capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.returncode == 0


def write_accredited(path: pathlib.Path, orcid: str, name: str) -> str:
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if orcid in text:
            return "già nella lista"
        if not text.endswith("\n"):
            text += "\n"
        text += f"  - orcid: {orcid}\n    name: {name}\n    profile: super\n"
        path.write_text(text, encoding="utf-8")
        return "aggiunto alla lista"
    path.write_text(
        "# THE FIELD NODE'S LIST OF ACCREDITED ORCID iDs — written by fcn-field-setup.sh.\n"
        "# Who works on this node. The node manager is the first. Add the others\n"
        "# here, one entry each, and restart the node (./fcn-up.sh --offline):\n"
        "#   - orcid: 0000-0000-0000-0000\n"
        "#     name: First Last\n"
        "#     profile: editor              # super · editor (creates rooms and teams) · user\n"
        "#     groups: [Excavation team]    # teams, created if missing\n"
        "# Nobody is ever removed by this file: that is done in the console.\n"
        "# Same format as accredited.yaml. It holds no secret.\n"
        "accredited:\n"
        f"  - orcid: {orcid}\n"
        f"    name: {name}\n"
        f"    profile: super\n", encoding="utf-8")
    return "lista creata"


def _interactive_ask(prompt: str, *, secret: bool = False) -> str:
    """Chiede alla persona, quando c'è una persona: senza un terminale, niente."""
    if not sys.stdin.isatty():
        return ""
    if secret:
        import getpass
        return getpass.getpass(prompt).strip()
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _default_host() -> str:
    import socket
    short = socket.gethostname().split(".")[0]
    return f"{short}.local".lower() if short else ""


def _run_autostart(here: pathlib.Path) -> bool:
    return subprocess.run([str(here / "fcn-autostart.sh"), "on"]).returncode == 0


def main(argv: Optional[List[str]] = None, *, here: pathlib.Path = HERE,
         volume_check=volume_exists, ask=_interactive_ask, autostart=_run_autostart) -> int:
    ap = argparse.ArgumentParser(
        description="Prepara la configurazione di un nodo da campo, una volta. Senza argomenti "
                    "chiede quello che serve.")
    ap.add_argument("--orcid", default="", help="l'ORCID iD di chi gestisce il nodo")
    ap.add_argument("--name", default="", help="il suo nome, come comparirà nella console")
    ap.add_argument("--node-name", default="", help="il nome con cui gli altri nodi lo conosceranno")
    ap.add_argument("--host", default="", help="il nome di rete del nodo (default: <macchina>.local)")
    ap.add_argument("--orcid-client-id", default="",
                    help="il client ORCID del nodo (il segreto lo chiede, o lo legge da "
                         "ORCID_CLIENT_SECRET nell'ambiente: mai sulla riga di comando)")
    auto = ap.add_mutually_exclusive_group()
    auto.add_argument("--autostart", dest="autostart", action="store_true", default=None,
                      help="il nodo parte da solo all'accensione (fcn-autostart.sh on)")
    auto.add_argument("--no-autostart", dest="autostart", action="store_false")
    a = ap.parse_args(argv)

    env_path = here / ".env.dev"
    _, before = read_env(env_path)

    # ── chi, e come si chiama il nodo: dagli argomenti, o chiesto ──────────────
    orcid = orcid_ok(a.orcid) if a.orcid else None
    if a.orcid and not orcid:
        print(f"✖ «{a.orcid}» non è un ORCID iD: la cifra di controllo non torna.", file=sys.stderr)
        return 2
    if not orcid and before.get("EM_NODE_KIND") == "field":
        #: rilanciato su un nodo già preparato: il gestore è quello di prima
        orcid = orcid_ok(before.get("DEV_OPERATOR_ORCID", "").split(",")[0])
    tries = 0
    while not orcid and tries < 3:
        given = ask("Il tuo ORCID iD (es. 0000-0002-1825-0097): ")
        if not given:
            break
        orcid = orcid_ok(given)
        if not orcid:
            print("  ✖ la cifra di controllo non torna: riscrivilo.")
        tries += 1
    if not orcid:
        print("✖ serve l'ORCID iD di chi gestisce il nodo (--orcid).", file=sys.stderr)
        return 2
    listed = (here / "accredited.field.yaml")
    already = listed.is_file() and orcid in listed.read_text(encoding="utf-8")
    name = " ".join((a.name or ("-" if already else "")
                     or ask("Il tuo nome, come comparirà nella console: ")).split())
    if not name or ":" in name or "#" in name:
        print("✖ serve un nome (--name), senza «:» né «#».", file=sys.stderr)
        return 2
    node_name = a.node_name.strip() or before.get("EM_NODE_NAME", "") \
        or ask("Un nome per il nodo, come lo leggeranno gli altri nodi (es. scavo-2027): ")
    host = (a.host.strip() or before.get("FCN_HOST", "")).lower()
    if not host:
        suggested = _default_host()
        host = ask(f"Il nome di rete del nodo [{suggested}]: ") or suggested
    if not host:
        print("✖ serve il nome di rete del nodo (--host).", file=sys.stderr)
        return 2

    example = here / ".env.dev.example"
    said: List[str] = []
    if not env_path.is_file():
        if not example.is_file():
            print("✖ non trovo né .env.dev né .env.dev.example: checkout incompleto.", file=sys.stderr)
            return 1
        shutil.copyfile(example, env_path)
        said.append("✚ .env.dev creato dal modello")
    lines, values = read_env(env_path)

    born = {v: volume_check(v) for v in set(BORN_WITH.values())}
    for key, defaults in DEV_DEFAULTS.items():
        current = values.get(key, "")
        if current not in defaults:
            said.append(f"✔ {key}: già cambiato, lo lascio")
            continue
        if born.get(BORN_WITH[key]):
            said.append(f"⚠ {key}: i dati che questo segreto protegge esistono già (volume "
                        f"{BORN_WITH[key]}) e lo portano con il valore di prima: non lo cambio, "
                        "il nodo smetterebbe di riconoscersi. Per ripartire puliti: "
                        "./fcn-down.sh --wipe, che CANCELLA i dati del nodo.")
            continue
        lines = set_env(lines, key, secrets.token_urlsafe(24))
        said.append(f"✚ {key}: generato")

    for key, value in (("EM_NODE_KIND", "field"), ("EM_ALLOW_TEST_PEOPLE", "0"),
                       ("DEV_OPERATOR_ORCID", orcid), ("DEV_CURATOR_ORCID", orcid),
                       ("FCN_HOST", host)):
        lines = set_env(lines, key, value)
    said.append(f"✚ nodo da campo «{host}», gestito da {orcid}; persone di prova spente")
    if node_name:
        lines = set_env(lines, "EM_NODE_NAME", node_name.strip())
        said.append(f"✚ nome del nodo per gli altri nodi: {node_name.strip()}")
    if "ORCID_ISSUER" not in values:
        lines = set_env(lines, "ORCID_ISSUER", "https://orcid.org")
        said.append("✚ ORCID: quello vero (orcid.org), non la sandbox")

    # ── il client ORCID: una volta, e il segreto non passa mai per la riga di comando
    redirect = f"https://{host}:8443/auth/realms/em-dev/broker/orcid/endpoint"
    has_client = values.get("ORCID_CLIENT_ID", "") not in ("", "APP-…") and bool(values.get("ORCID_CLIENT_SECRET"))
    if not has_client:
        client_id = a.orcid_client_id.strip()
        if not client_id and sys.stdin.isatty():
            print()
            print("  Il client ORCID del nodo (orcid.org → Developer tools → public API client),")
            print("  con questo redirect URI:")
            print(f"    {redirect}")
        client_id = client_id or ask("  ORCID client ID (APP-…, Invio per farlo dopo): ")
        if client_id:
            import os
            client_secret = os.environ.get("ORCID_CLIENT_SECRET", "") or \
                ask("  ORCID client secret (non si vede mentre scrivi): ", secret=True)
            if client_secret:
                lines = set_env(lines, "ORCID_CLIENT_ID", client_id)
                lines = set_env(lines, "ORCID_CLIENT_SECRET", client_secret)
                has_client = True
                said.append("✚ client ORCID registrato nel nodo")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        env_path.chmod(0o600)
    except OSError:
        pass
    said.append(f"✚ accredited.field.yaml: {write_accredited(here / 'accredited.field.yaml', orcid, name)}")

    # ── l'avvio automatico all'accensione ──────────────────────────────────────
    want = a.autostart
    if want is None:
        answer = ask("Il nodo deve accendersi da solo quando si accende la macchina? [S/n] ")
        want = sys.stdin.isatty() and answer.lower() not in ("n", "no")
    if want:
        said.append("✚ avvio automatico acceso" if autostart(here)
                    else "⚠ avvio automatico non acceso: ./fcn-autostart.sh on")

    print()
    print("▶ nodo da campo · configurazione")
    for line in said:
        print(f"  {line}")
    print()
    print("  I segreti sono in dev-stack/.env.dev (leggibile solo da te). Tienine una")
    print("  copia in un posto sicuro: senza, il nodo non si ricostruisce.")
    if not has_client:
        print()
        print("  MANCA ancora il client ORCID. Quando lo hai (orcid.org → Developer tools,")
        print(f"  redirect URI {redirect}),")
        print("  rilancia ./fcn-field-setup.sh: chiede solo quello.")
    print()
    print("  Adesso:   ./fcn-up.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
