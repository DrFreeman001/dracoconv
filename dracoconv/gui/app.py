"""Point d'entrée de la fenêtre."""
from __future__ import annotations

import multiprocessing
import sys


def main(argv: list[str] | None = None) -> int:
    """dracoconv-gui [--encode|--decode|--slicer|--watch] [chemins...]"""
    multiprocessing.freeze_support()
    from .launch import claim_or_forward, parse

    direction, paths = parse(sys.argv[1:] if argv is None else argv)
    if direction in ("slicer", "watch"):
        from ..config import load_prefs
        from ..i18n import LANGUAGES, set_language, system_language

        language = load_prefs().get("language")
        set_language(language if language in LANGUAGES else system_language())
        if direction == "watch":  # passage de la tâche planifiée « dossiers surveillés »
            from .watch_run import run as watch_run

            return watch_run()
        from .slicer_open import run

        return run(paths)
    channel = claim_or_forward(direction, paths)
    if channel is True:  # une fenêtre déjà ouverte a reçu les chemins
        return 0
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from ..config import load_prefs
    from ..i18n import LANGUAGES, set_language, system_language
    from .main_window import MainWindow

    language = load_prefs().get("language")
    set_language(language if language in LANGUAGES else system_language())
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("dracoconv")
    window = MainWindow()
    window.show()
    window.open_paths(paths, direction)
    if channel is not None:
        def receive() -> None:
            while not channel.requests.empty():
                window.open_paths(*reversed(channel.requests.get_nowait()))

        timer = QTimer(window)
        timer.timeout.connect(receive)
        timer.start(200)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
