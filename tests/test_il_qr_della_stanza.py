"""La porta «telefono»: il QR della porta del browser, con la libreria venduta
nel nodo (un nodo da campo non ha rete per un CDN). 31 ottobre 2026."""
import pathlib

UI = pathlib.Path(__file__).resolve().parents[1] / "app" / "rooms_ui"


def test_la_libreria_e_nel_nodo_e_dice_la_sua_licenza():
    lib = (UI / "vendor" / "qrcode-generator-1.4.4.js").read_text()
    assert "MIT license" in lib and "Kazuhiko Arase" in lib


def test_la_porta_telefono_accompagna_ogni_porta_del_browser():
    js = (UI / "rooms.js").read_text()
    assert 't("door.phone")' in js
    assert "./vendor/qrcode-generator-1.4.4.js" in js
    assert "cdn" not in js[js.index("function loadQr"):js.index("async function showQr")].lower().replace("un cdn", "")
