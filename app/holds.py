"""Chi tiene un `.blend` — la prenotazione (lease) nella stanza (31 ott 2026).

MICRO-BLEND-OFFICINA-2, decisioni di E.D. D7 e D8. Il grafo in stanza si
fonde fra più persone; i file binari (un `.blend`, un master) no. Chi apre un
`.blend` per modificarlo lo PRENDE nella stanza: «aperto da ‹persona› su
‹computer› dalle ‹ora›», visibile a tutti; gli altri lavorano in sola lettura
e un loro salvataggio diventa una versione nuova col loro nome (lo decidono i
client: il server dice solo chi tiene cosa).

IL VERBO È UNO, `hold`, con tre azioni:

* ``take`` — libero, scaduto o già mio → mio (``since`` resta se era già mio);
  di un altro e vivo → ``hold_refused`` a chi chiede, con chi lo tiene;
* ``renew`` — solo chi lo tiene; **un renew di una prenotazione che non c'è
  più, dalla stessa persona, vale come take** (vedi sotto, il riavvio);
* ``release`` — chi lo tiene, oppure con ``force`` chi amministra la stanza
  (owner o admin: `Role.can_manage`), dopo la conferma che chiede il client.

Un lettore (`viewer`) non prende niente, ma vede la lista.

SCADENZA: :data:`TTL_SECONDS` (15 minuti) dall'ultimo ``take``/``renew`` —
**non** da qualunque frame: un EMStudio che batte `still_here` non tiene vivo
il `.blend` di un Blender chiuso. Calcolata quando si legge (pigra), con
l'orologio monotòno per la durata, come `presence.py`; nel payload le ore
sono secondi dell'epoca (le legge una persona su un altro computer). Una
disconnessione NON libera: D8 dice «scade dopo 15 minuti senza segnale», e una
rete che cade per un minuto non deve regalare il file a un altro.

EFFIMERA COME LA PRESENZA: in RAM sulla `Room`, persa a un riavvio del server.
È voluto, e ha una conseguenza detta: **un riavvio libera ogni prenotazione**;
chi la teneva la riprende al suo prossimo ``renew`` (ogni 60 s da Blender),
che per questo vale come ``take``. Nella finestra fra il riavvio e il rinnovo
un altro può prenderla: lo vedrà chi rinnova (``hold_refused``).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from . import presence

#: D8 · senza un segno per questo tempo, la prenotazione cade
TTL_SECONDS = 15 * 60
#: la chiave più lunga accettata (un percorso relativo alla radice del progetto)
KEY_MAX = 512
#: un nome di client (``blender``, ``emstudio``…) non è un testo libero
CLIENT_MAX = 32
HOST_MAX = 128
ACTIONS = ("take", "renew", "release")


class HoldError(ValueError):
    """Una richiesta che non si può nemmeno valutare (chiave, azione)."""


def check_key(key: Any) -> str:
    if not isinstance(key, str) or not key.strip():
        raise HoldError("a hold needs a `key`: the .blend's path relative to the project")
    if len(key) > KEY_MAX:
        raise HoldError(f"a hold's key is at most {KEY_MAX} characters")
    if "\x00" in key:
        raise HoldError("a hold's key cannot contain NUL")
    return key


class Holds:
    """Le prenotazioni di una stanza: chiave → record."""

    def __init__(self, clock=presence.monotonic, wall=time.time):
        self._clock = clock
        self._wall = wall
        self._by_key: Dict[str, Dict[str, Any]] = {}
        #: quando (monotòno) ogni chiave è stata rinnovata: la durata
        self._mono: Dict[str, float] = {}

    def _alive(self, key: str) -> bool:
        at = self._mono.get(key)
        return at is not None and self._clock() - at <= TTL_SECONDS

    def _sweep(self) -> None:
        for key in [k for k in self._by_key if not self._alive(k)]:
            self._by_key.pop(key, None)
            self._mono.pop(key, None)

    def alive(self) -> List[Dict[str, Any]]:
        self._sweep()
        return [dict(v) for _k, v in sorted(self._by_key.items())]

    def holder(self, key: str) -> Optional[Dict[str, Any]]:
        self._sweep()
        got = self._by_key.get(key)
        return dict(got) if got else None

    def apply(self, action: str, key: str, *, person: str, display: str = "",
              host: str = "", client: str = "", connection_id: str = "",
              force: bool = False, may_manage: bool = False) -> Dict[str, Any]:
        """→ ``{ok, changed, hold?, reason?, holder?}``."""
        if action not in ACTIONS:
            raise HoldError(f"a hold's action is one of {', '.join(ACTIONS)}")
        key = check_key(key)
        self._sweep()
        current = self._by_key.get(key)
        mine = bool(current and current.get("person") == person)
        if action == "release":
            if current is None:
                return {"ok": True, "changed": False}
            if mine or (force and may_manage):
                self._by_key.pop(key, None)
                self._mono.pop(key, None)
                return {"ok": True, "changed": True}
            return {"ok": False, "holder": dict(current),
                    "reason": ("held by somebody else: only who holds it, or whoever "
                               "manages the room (force), may release it")}
        if action == "renew" and current is not None and not mine:
            return {"ok": False, "holder": dict(current),
                    "reason": "held by somebody else: you cannot renew it (did it lapse?)"}
        if action == "take" and current is not None and not mine:
            return {"ok": False, "holder": dict(current),
                    "reason": "already open by somebody else: read only"}
        now = float(self._wall())
        record = {"key": key, "person": person, "display": display or person,
                  "host": str(host or "")[:HOST_MAX], "client": str(client or "")[:CLIENT_MAX],
                  "since": float(current["since"]) if mine else now,
                  "renewed": now, "connection_id": connection_id}
        # a renew that says nothing new (same computer, same client) is not
        # broadcast: a Blender renews every 60 s, and the room hears it only
        # when somebody would SEE something change
        changed = not (mine and current.get("host") == record["host"]
                       and current.get("client") == record["client"])
        self._by_key[key] = record
        self._mono[key] = self._clock()
        return {"ok": True, "changed": changed, "hold": dict(record)}
