"""Il cestino e la soglia sulle operazioni in blocco (E.D., 31 ott 2026).

Due decisioni, prese insieme dopo una mattina in cui sette stanze di prova e
nove gigabyte di file sono spariti con due clic e senza ritorno:

* **il cestino di 30 giorni.** Cancellare una stanza o un file del nodo li
  mette nel cestino: un segno, nient'altro si muove. Per trenta giorni chi li
  ha tolti (o l'operatore) li riprende; dopo li vuota il nodo. Prima dei trenta
  giorni li vuota solo una persona, con un secondo gesto.
* **la soglia sul blocco.** Oltre 20 stanze, o oltre 5 GB di file, tolti dalla
  stessa persona nell'arco di un'ora, il nodo chiede una conferma esplicita
  (`bulk=true`, che la console manda solo dopo una frase digitata). Vale anche
  per chi scrive uno script: è il nodo a contare, non la pagina.

Qui stanno i numeri e il contatore; i gesti stanno in `main.py`.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, Optional, Tuple

#: i giorni nel cestino prima che il nodo lo vuoti da sé
TRASH_DAYS = int(os.environ.get("EM_TRASH_DAYS", "30"))
#: la soglia sul blocco: stanze e byte per persona nell'arco di `BULK_WINDOW`
BULK_ROOMS = int(os.environ.get("EM_BULK_ROOMS", "20"))
BULK_BYTES = int(os.environ.get("EM_BULK_BYTES", str(5 * 1024 ** 3)))
BULK_WINDOW = 3600.0


def _parse(at: str) -> Optional[datetime]:
    try:
        when = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def purge_after(at: Optional[str]) -> Optional[str]:
    """Quando il nodo vuoterà da sé quello che è entrato nel cestino ad `at`."""
    when = _parse(at or "")
    if when is None:
        return None
    return (when + timedelta(days=TRASH_DAYS)).isoformat().replace("+00:00", "Z")


def due(at: Optional[str], now: Optional[datetime] = None) -> bool:
    """Se è passato il tempo del cestino. Una data illeggibile non scade mai:
    nel dubbio si tiene."""
    when = _parse(at or "")
    if when is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now >= when + timedelta(days=TRASH_DAYS)


class BulkGuard:
    """Quante stanze e quanti byte ha tolto ciascuno nell'ultima ora."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: Dict[str, Deque[Tuple[float, int, int]]] = defaultdict(deque)

    def _window(self, who: str, now: float) -> Tuple[int, int]:
        q = self._seen[who]
        while q and now - q[0][0] > BULK_WINDOW:
            q.popleft()
        return sum(r for _, r, _ in q), sum(b for _, _, b in q)

    def over(self, who: str, *, rooms: int = 0, size: int = 0) -> Optional[str]:
        """La frase da dire se questo gesto passa la soglia, altrimenti None."""
        with self._lock:
            done_rooms, done_bytes = self._window(who, time.monotonic())
        if rooms and done_rooms + rooms > BULK_ROOMS:
            return (f"this is an operation in bulk: {done_rooms + rooms} rooms "
                    f"in the last hour, over the threshold of {BULK_ROOMS}. "
                    f"Confirm it explicitly (bulk=true).")
        if size and done_bytes + size > BULK_BYTES:
            gb = (done_bytes + size) / 1024 ** 3
            return (f"this is an operation in bulk: {gb:.1f} GB of files in "
                    f"the last hour, over the threshold of "
                    f"{BULK_BYTES / 1024 ** 3:.0f} GB. Confirm it explicitly "
                    f"(bulk=true).")
        return None

    def count(self, who: str, *, rooms: int = 0, size: int = 0) -> None:
        with self._lock:
            self._seen[who].append((time.monotonic(), rooms, size))

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()


BULK = BulkGuard()
