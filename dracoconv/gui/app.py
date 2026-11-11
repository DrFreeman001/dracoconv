"""Point d'entrée de la fenêtre."""
from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
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
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
