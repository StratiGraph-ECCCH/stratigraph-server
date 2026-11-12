"""La porta «telefono»: il QR di StratiField, con la libreria venduta nel nodo
(un nodo da campo non ha rete per un CDN). 31 ottobre 2026.

11 novembre 2026: la libreria ha lasciato `rooms_ui/vendor/` — quella cartella
esisteva ormai solo per lei — ed è in `app/vendor/`, montata su `/vendor`. La
porta la disegna la casa (`node_admin/modules/home.js`), non più `rooms.js`."""
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def test_la_libreria_e_nel_nodo_e_dice_la_sua_licenza():
    lib = (APP / "vendor" / "qrcode-generator-1.4.4.js").read_text()
    assert "MIT license" in lib and "Kazuhiko Arase" in lib


def test_la_porta_telefono_accompagna_ogni_porta_del_browser():
    js = (APP / "node_admin" / "modules" / "home.js").read_text()
    assert 't("home.door.phone")' in js
    assert '"../../vendor/qrcode-generator-1.4.4.js"' in js
    assert "cdn" not in js[js.index("function loadQr"):js.index("async function showQr")].lower()


def test_la_libreria_si_serve_da_vendor_e_la_casa_vecchia_no():
    from fastapi.testclient import TestClient
    from app import main
    with TestClient(main.app) as client:
        assert client.get("/vendor/qrcode-generator-1.4.4.js").status_code == 200
        assert client.get("/rooms/vendor/qrcode-generator-1.4.4.js").status_code == 404
