"""Le schermate del manuale, rifatte (19 novembre 2026).

    .venv/bin/python scripts/schermate_del_manuale.py           # tutte
    .venv/bin/python scripts/schermate_del_manuale.py catalogue # una

Le pagine del nodo (la porta, la casa, una stanza aperta) si prendono dal server
VERO acceso da `tests/pagina_vera.py`, con una persona che NON è operatore: la
casa che si vede è quella di chi lavora in una stanza, non della console. Il
catalogo si prende dallo stack di sviluppo acceso (`https://em.localhost:8443`),
perché è un altro servizio e `pagina_vera` accende solo il server.

Ogni schermata esce in `docs/img/` come PNG a 256 colori, ridotta a 1024 px di
larghezza e sotto i 150 KB che `tests/test_docs_img_peso.py` fa rispettare.
PNG e non WebP: il PDF di Read the Docs passa da XeLaTeX, che WebP non lo legge.
Servono Chrome e ImageMagick (`magick`).
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
from pagina_vera import CHROME, server  # noqa: E402

OUT = REPO / "docs" / "img"
STACK = "https://em.localhost:8443"
ROOM = "podere-sette-2026"

#: chi guarda non è operatore, e su questo nodo chiunque firmi crea stanze
NON_OPERATORE = "ops.is_operator = lambda *a, **k: False\n"
#: e il nodo sa il proprio indirizzo pubblico, senza il quale non scrive le
#: porte «Open in» (503, «Set EM_PUBLIC_BASE»)
ENV = {"EM_CREATE_POLICY": "anyone", "EM_EMSTUDIO_WEB_URL": "/em/studio/",
       "EM_PUBLIC_BASE": "https://em.localhost:8443/em"}

#: una pagina della prova che mette la lingua, apre la pagina vera in un
#: riquadro grande quanto la finestra e, se serve, clicca qualcosa
_RIQUADRO = """<!doctype html><html><head><style>
html,body{margin:0;background:#1d1b19}iframe{border:0;width:1280px;height:800px;display:block}
</style></head><body><iframe id="f"></iframe><script>
localStorage.setItem("sg.locale.v1", "en");
const f = document.getElementById("f");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
f.addEventListener("load", async () => {
  await wait(2500);
  const d = f.contentDocument;
  %(azione)s
}, { once: true });
f.src = "%(src)s";
</script></body></html>"""


def _scatta(url: str, png: pathlib.Path, *, budget_ms: int = 9000, insecure: bool = False) -> None:
    with tempfile.TemporaryDirectory() as profile:
        args = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                "--no-default-browser-check", "--hide-scrollbars",
                f"--user-data-dir={profile}", "--lang=en-US", "--accept-lang=en-US", "--window-size=1280,800",
                f"--virtual-time-budget={budget_ms}", f"--screenshot={png}", url]
        if insecure:
            args.insert(1, "--ignore-certificate-errors")
        subprocess.run(args, capture_output=True, timeout=120, check=True)


def _riduci(png: pathlib.Path, nome: str) -> pathlib.Path:
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{nome}.png"
    subprocess.run(["magick", str(png), "-resize", "1024x", "-strip", "-dither", "None",
                    "-colors", "256", f"PNG8:{out}"], check=True)
    print(f"{out.relative_to(REPO)}  {out.stat().st_size // 1024} KB")
    return out


def _chiedi(base: str, metodo: str, percorso: str, corpo: dict) -> dict:
    req = urllib.request.Request(base + percorso, data=json.dumps(corpo).encode(),
                                 headers={"Content-Type": "application/json"}, method=metodo)
    return json.loads(urllib.request.urlopen(req).read() or b"{}")


def pagine_del_nodo(tmp: pathlib.Path, quali: set) -> None:
    pagine = {
        "porta.html": _RIQUADRO % {"src": "/", "azione": ""},
        "casa.html": _RIQUADRO % {"src": "/home/", "azione": ""},
        "stanza.html": _RIQUADRO % {"src": f"/home/#room={ROOM}", "azione": ""},
    }
    with server(tmp, patch=NON_OPERATORE, env=ENV, pages=pagine) as base:
        _chiedi(base, "POST", "/v1/rooms", {"room_id": ROOM,
                "title": "Podere Sette — Area 2, campaign 2026"})
        _chiedi(base, "POST", "/v1/rooms", {"room_id": "villa-dei-gelsi-2025",
                "title": "Villa dei Gelsi — survey 2025"})
        for orcid, role in (("0000-0003-1111-1112", "editor"),
                            ("0000-0003-2222-2221", "viewer")):
            _chiedi(base, "PUT", f"/v1/rooms/{ROOM}/members/{orcid}", {"role": role})
        for pagina, nome in (("porta", "node-door"), ("casa", "your-rooms"),
                             ("stanza", "room-people-and-sharing")):
            if quali and nome not in quali:
                continue
            png = tmp / f"{nome}.png"
            _scatta(f"{base}/__prova__/{pagina}.html", png)
            _riduci(png, nome)


def catalogo(tmp: pathlib.Path) -> None:
    png = tmp / "catalogue.png"
    _scatta(f"{STACK}/catalog/", png, insecure=True)
    _riduci(png, "catalogue")


def main(argv: list) -> None:
    if not CHROME:
        sys.exit("niente Chrome: SG_CHROME sceglie il binario")
    quali = set(argv)
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d)
        if not quali or quali - {"catalogue"}:
            pagine_del_nodo(tmp, quali - {"catalogue"})
        if not quali or "catalogue" in quali:
            catalogo(tmp)


if __name__ == "__main__":
    main(sys.argv[1:])
