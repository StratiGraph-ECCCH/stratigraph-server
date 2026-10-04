#!/usr/bin/env python3
"""N2 · a StratiGraph node on THIS computer, with one click (E.D., 4 Oct 2026).

    python scripts/personal_node.py start --root ~/Scavi/Tempio   # this computer only
    python scripts/personal_node.py start --root … --lan           # open to the local network
    python scripts/personal_node.py status
    python scripts/personal_node.py stop

The «personal» profile, measured against the dev stack (8 containers, ~2.8 GB of
RAM — Keycloak 1.5 GB, Cantaloupe 0.75 GB —, Docker required): ONE process, no
Docker, no Keycloak, no MinIO, no Postgres. What a person alone needs is the
graph, the rooms and the web tools; what stays off is identity (a node that
listens to this computer only has one person in front of it: the dev-mode
«open» door), the IIIF server and the object store.

* it listens on **127.0.0.1 only** by definition; ``--lan`` is the explicit
  choice to open it to the local network, and only then it announces itself
  with DNS-SD (``_stratigraph._tcp``, through ``dns-sd`` on macOS or
  ``avahi-publish`` on Linux — no new dependency);
* it does **not keep the files**: «Upload to the room» registers a file of the
  project's tree by reference (``EM_PERSONAL_ROOT``), the folders stay the
  custody — keep them on a backed-up disk;
* its data (rooms, snapshots, the few bytes uploaded from outside the tree) live
  in ``--data`` (default: the user's application-support folder).

The desks call this script (EMStudio through its bridge, EM Tools directly) for
«Turn on a node on this computer». Prints one JSON line.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PORT = 8777
SERVICE = "_stratigraph._tcp"


def data_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "StratiGraph" / "personal-node"


def _state(data: Path) -> Path:
    return data / "node.json"


def _read(data: Path) -> dict:
    try:
        return json.loads(_state(data).read_text())
    except (OSError, ValueError):
        return {}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _health(url: str, timeout: float = 1.0):
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


def lan_address() -> str:
    """This computer's address on the local network (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))           # TEST-NET: routing table only
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _announce(name: str, port: int):
    """DNS-SD announcement while the node is open to the network."""
    if shutil.which("dns-sd"):
        return subprocess.Popen(["dns-sd", "-R", name, SERVICE, "local.", str(port), "path=/"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if shutil.which("avahi-publish"):
        return subprocess.Popen(["avahi-publish", "-s", name, SERVICE, str(port), "path=/"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None


def start(root: str, data: Path, port: int, lan: bool, name: str) -> dict:
    data.mkdir(parents=True, exist_ok=True)
    was = _read(data)
    if was.get("pid") and _alive(was["pid"]):
        if bool(was.get("lan")) == lan:
            return {"ok": True, "already": True, **was}
        stop(data)                              # the same node, another door
    host = "0.0.0.0" if lan else "127.0.0.1"
    env = dict(os.environ)
    for k in ("OIDC_ISSUER", "OIDC_AUDIENCE", "TOKEN_ENDPOINT", "CLIENT_ID_em",
              "S3_ENDPOINT", "MINIO_ENDPOINT", "EM_SNAPSHOT_DSN", "DATABASE_URL"):
        env.pop(k, None)                         # personal: nothing of the stack
    env.update({"EM_NODE_PROFILE": "personal", "EM_PERSONAL_ROOT": os.path.abspath(root),
                "EM_SNAPSHOT_DIR": str(data / "snapshots"), "EM_ASSET_DIR": str(data / "assets"),
                "EM_NODE_NAME": name, "EM_SERVER_HOST": host, "EM_SERVER_PORT": str(port),
                "EM_CORS_ORIGINS": "*"})
    log = open(data / "node.log", "ab")
    t0 = time.monotonic()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", host,
                             "--port", str(port)], cwd=str(HERE), env=env, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    url = f"http://127.0.0.1:{port}"
    health = None
    while time.monotonic() - t0 < 60 and proc.poll() is None:
        health = _health(url)
        if health:
            break
        time.sleep(0.25)
    if not health:
        return {"ok": False, "error": f"the node did not answer in 60 s (see {data / 'node.log'})"}
    announcer = _announce(name, port) if lan else None
    state = {"pid": proc.pid, "url": url, "port": port, "lan": lan, "root": os.path.abspath(root),
             "announcer": announcer.pid if announcer else None,
             "lan_url": f"http://{lan_address()}:{port}" if lan else None,
             "started_in_s": round(time.monotonic() - t0, 2), "profile": health.get("profile")}
    _state(data).write_text(json.dumps(state, indent=1))
    who = ("everybody on this local network can reach it — its door is open (no "
           "password): close it when you are done" if lan else
           "only this computer can reach it")
    return {"ok": True, **state, "who": who}


def stop(data: Path) -> dict:
    was = _read(data)
    for key in ("announcer", "pid"):
        pid = was.get(key)
        if pid and _alive(pid):
            try:
                os.killpg(pid, signal.SIGTERM) if key == "pid" else os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    # wait until the port is free: a start right after must not be answered
    # by the process that is going away
    t0 = time.monotonic()
    while was.get("url") and _health(was["url"], 0.3) and time.monotonic() - t0 < 10:
        time.sleep(0.2)
    _state(data).unlink(missing_ok=True)
    return {"ok": True, "stopped": bool(was)}


def status(data: Path) -> dict:
    was = _read(data)
    alive = bool(was.get("pid") and _alive(was["pid"]))
    return {"ok": True, "running": alive, **(was if alive else {}),
            "health": _health(was["url"]) if alive else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=("start", "stop", "status"))
    ap.add_argument("--root", default=".", help="the EM project tree whose files are referenced")
    ap.add_argument("--data", default=str(data_dir()))
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--lan", action="store_true", help="open it to the local network (and announce it)")
    ap.add_argument("--name", default=f"StratiGraph ({socket.gethostname().split('.')[0]})")
    a = ap.parse_args()
    data = Path(a.data)
    out = (start(a.root, data, a.port, a.lan, a.name) if a.action == "start"
           else stop(data) if a.action == "stop" else status(data))
    print(json.dumps(out))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
