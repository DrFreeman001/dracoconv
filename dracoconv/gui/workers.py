"""Exécution des traitements hors du fil de l'interface."""
from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QThread, Signal


class Worker(QThread):
    """Lance ``fn(*args, **kwargs)`` dans un fil séparé.

    ``progress_arg`` et ``stop_arg`` nomment, s'ils sont donnés, les paramètres de ``fn`` qui
    reçoivent la fonction de progression et l'événement d'arrêt.
    """

    progress = Signal(object)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, progress_arg: str | None = None, stop_arg: str | None = None, parent=None, **kwargs):
        super().__init__(parent)
        self._fn, self._args, self._kwargs = fn, args, kwargs
        self.stop_event = threading.Event()
        if progress_arg:
            self._kwargs[progress_arg] = self._report
        if stop_arg:
            self._kwargs[stop_arg] = self.stop_event

    def _report(self, *values) -> None:
        self.progress.emit(values[0] if len(values) == 1 else values)

    def request_stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:  # noqa: D401 - API Qt
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # l'erreur est remontée à l'interface, jamais avalée
            traceback.print_exc()
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished_ok.emit(result)
