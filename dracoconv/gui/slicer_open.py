"""Clic droit « Ouvrir dans le trancheur » sur des .drc : décodage en STL temporaires, puis lancement du trancheur.

L'Explorateur lance un processus par fichier sélectionné : le premier recueille les chemins des autres pendant
un court instant, pour ouvrir toute la sélection dans une seule fenêtre du trancheur. Aucune fenêtre de dracoconv
ne s'ouvre, sauf un message en cas de problème.
"""
from __future__ import annotations

import queue
import time
from pathlib import Path

from .launch import SLICER, Channel, claim_or_forward

GATHER_IDLE_S = 0.8


def gather(channel: Channel | None, paths: list[Path], idle_s: float = GATHER_IDLE_S) -> list[Path]:
    """Chemins reçus des autres lancements, jusqu'à ``idle_s`` secondes sans nouvelle demande."""
    collected = list(paths)
    if channel is not None:
        deadline = time.monotonic() + idle_s
        while time.monotonic() < deadline:
            try:
                _kind, more = channel.requests.get(timeout=0.05)
            except queue.Empty:
                continue
            collected.extend(more)
            deadline = time.monotonic() + idle_s
        channel.close()
    unique, seen = [], set()
    for path in collected:
        key = str(Path(path).resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(Path(path))
    return unique


def _message(text: str, warning: bool = True) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from ..i18n import tr

    app = QApplication.instance() or QApplication([])
    box = QMessageBox(QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Information,
                      tr("slicer.title"), text)
    box.exec()
    del app


def run(paths: list[Path]) -> int:
    from ..i18n import reason_text, tr
    from ..slicer import chosen, launch, prepare

    channel = claim_or_forward(SLICER, paths, kind=SLICER)
    if channel is True:  # le premier lancement s'occupe de ce fichier
        return 0
    paths = gather(channel if isinstance(channel, Channel) else None, paths)
    slicer = chosen()
    if slicer is None:
        _message(tr("slicer.none"))
        return 1
    name, exe = slicer
    ready, failed = prepare(paths)
    if ready:
        try:
            launch(exe, ready)
        except OSError as exc:
            _message(tr("slicer.launch_failed", name=name, error=str(exc)))
            return 1
    if failed:
        details = "\n".join(f"• {p.name} : {reason_text(code)}" for p, code in failed)
        _message(tr("slicer.failed", n=len(failed), details=details))
    return 0 if ready else 1
