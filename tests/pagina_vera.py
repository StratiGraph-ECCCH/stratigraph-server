"""LA PAGINA VERA, in un browser vero (9 novembre 2026).

Le prove di questa notte chiedono alla PORTA e non alla funzione che decide:
«nella pagina resa non compaiono le sezioni del nodo», «cambiata lingua il
testo del pannello cambia», «la vetrina disegna un servizio nuovo». Leggere il
sorgente di `console.js` direbbe che cosa il codice INTENDE; qui si guarda che
cosa il browser DISEGNA.

Come:

* il server vero (`app.main:app`) in un processo suo, su una porta libera, con
  una toppa scritta dalla prova (`patch`, codice Python eseguito dopo
  l'import: per esempio `ops.is_operator = lambda *a, **k: False`). Nessun file
  di pagina viene toccato;
* le pagine di prova della prova stessa (un `iframe` sulla pagina vera, che la
  guarda dallo STESSO ORIGIN e scrive quello che vede) montate su `/__prova__`;
* Chrome senza testa: `--dump-dom` con un budget di tempo virtuale, cioè il DOM
  dopo che gli script hanno finito.

Senza Chrome le prove si saltano e lo dicono. `SG_CHROME` sceglie il binario.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.request

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


def _chrome() -> str:
    for candidate in (os.environ.get("SG_CHROME", ""),
                      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                      shutil.which("google-chrome") or "", shutil.which("chromium") or "",
                      shutil.which("chromium-browser") or ""):
        if candidate and os.path.exists(candidate):
            return candidate
    return ""


CHROME = _chrome()
needs_chrome = pytest.mark.skipif(not CHROME, reason="niente Chrome: la pagina vera non si può rendere qui")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def server(tmp_path: pathlib.Path, *, patch: str = "", env: dict | None = None,
           pages: dict | None = None):
    """Il nodo vero su `http://127.0.0.1:<porta>`, e la sua base come valore."""
    harness = tmp_path / "prova"
    harness.mkdir(parents=True, exist_ok=True)
    for name, text in (pages or {}).items():
        (harness / name).write_text(text, encoding="utf-8")
    port = _free_port()
    launcher = tmp_path / "avvia_il_nodo.py"
    launcher.write_text(textwrap.dedent(f"""
        import sys
        sys.path[:0] = [{str(REPO)!r}, {str(REPO.parent / "s3Dgraphy" / "src")!r}]
        import uvicorn
        from starlette.staticfiles import StaticFiles
        import app.main as m
        from app import node_health
        ops = m.ops
    """) + textwrap.dedent(patch) + textwrap.dedent(f"""
        m.app.mount("/__prova__", StaticFiles(directory={str(harness)!r}, html=True))
        uvicorn.run(m.app, host="127.0.0.1", port={port}, log_level="warning")
    """), encoding="utf-8")
    full_env = dict(os.environ)
    for k in ("OIDC_ISSUER", "TOKEN_ENDPOINT", "CLIENT_ID_em", "OIDC_AUDIENCE"):
        full_env.pop(k, None)
    full_env.update(env or {})
    log = open(tmp_path / "nodo.log", "w")
    proc = subprocess.Popen([sys.executable, str(launcher)], cwd=str(tmp_path),
                            env=full_env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen(base + "/health", timeout=1)
                break
            except Exception:
                if proc.poll() is not None:
                    raise RuntimeError((tmp_path / "nodo.log").read_text())
                time.sleep(0.1)
        else:
            raise RuntimeError("il nodo non è salito: " + (tmp_path / "nodo.log").read_text())
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def dom(url: str, *, budget_ms: int = 8000) -> str:
    """Il DOM di `url` dopo che i suoi script hanno girato."""
    with tempfile.TemporaryDirectory() as profile:
        done = subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
             "--no-default-browser-check", f"--user-data-dir={profile}",
             "--lang=en-US", f"--virtual-time-budget={budget_ms}", "--dump-dom", url],
            capture_output=True, text=True, timeout=120)
    return done.stdout
