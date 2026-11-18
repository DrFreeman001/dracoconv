"""Captures d'écran de la fenêtre pour les README, en PNG net (rendu Qt, sans capture de l'écran).

Usage : python tools/screenshots.py <dossier de sortie> [--lang fr|en] [--theme dark|light]
Génère une collection de démonstration (tools/demo_models.py) dans un dossier temporaire, puis parcourt les
étapes : analyse, réglages, gain et qualité (avec échantillonnage), conversion, journal, doublons.
Les réglages et le cache de l'utilisateur ne sont pas touchés (APPDATA et LOCALAPPDATA temporaires).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("fr", "en"), default="fr")
    parser.add_argument("--theme", choices=("dark", "light"), default="dark")
    parser.add_argument("--models", type=Path, help="dossier de démonstration à copier (sinon généré)")
    parser.add_argument("--drive", help="lettre libre (ex. R:) : la collection y est montrée par « subst », "
                                        "pour des chemins courts à l'écran ; retirée à la fin")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="dracoconv-captures-"))
    os.environ["APPDATA"] = str(work / "appdata")
    os.environ["LOCALAPPDATA"] = str(work / "localappdata")
    os.environ["DRACOCONV_NO_UPDATE_CHECK"] = "1"
    shown = work / "shown"
    shown.mkdir()
    if args.drive:
        import subprocess

        subprocess.run(["subst", args.drive, str(shown)], check=True)
        base = Path(args.drive + "\\")
    else:
        base = shown
    try:
        return capture(args, work, base / ("Modèles 3D" if args.lang == "fr" else "3D models"))
    finally:
        if args.drive:
            import subprocess

            subprocess.run(["subst", args.drive, "/d"], check=False)
        shutil.rmtree(work, ignore_errors=True)


def capture(args, work: Path, folder: Path) -> int:
    if args.models:
        shutil.copytree(args.models, folder)
    else:
        import demo_models

        demo_models.collection(folder, args.lang)

    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from dracoconv.config import save_prefs
    from dracoconv.i18n import set_language

    save_prefs({"theme": args.theme, "language": args.lang})
    set_language(args.lang)
    app = QApplication(sys.argv)
    app.setApplicationName("dracoconv")
    from dracoconv.gui.main_window import MainWindow

    args.out.mkdir(parents=True, exist_ok=True)

    def settle(ms: int = 400) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait(signal, timeout_ms: int) -> None:
        loop = QEventLoop()
        signal.connect(loop.quit)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()

    def save(widget, name: str) -> None:
        # Même écran, même taille pour toutes les captures (une fenêtre qui change d'écran change d'échelle).
        screen = app.primaryScreen().availableGeometry()
        size = (1280, 860) if widget is window else (1080, 640)
        widget.resize(*size)
        widget.move(screen.topLeft())
        settle()
        path = args.out / f"{name}.png"
        widget.grab().save(str(path))
        print(path)

    window = MainWindow()
    window.resize(1280, 860)
    window.show()
    window.convert_page.workers_spin.setValue(2)
    settle(800)

    window.source_page.add_root(folder)
    window.source_page.start_scan()
    wait(window.source_page.scanned, 60_000)
    save(window, "source")

    window.steps.setCurrentRow(1)
    save(window, "settings")

    window.steps.setCurrentRow(2)
    page = window.projection_page
    page.budget_spin.setValue(30)
    page.start_sampling()
    wait(page.quality_ready, 180_000)
    save(window, "projection")

    window.steps.setCurrentRow(3)
    convert = window.convert_page
    convert.refresh_plan()
    save(window, "convert")  # le plan, avant de lancer
    convert.start_button.click()
    wait(convert.finished, 600_000)

    window.steps.setCurrentRow(4)
    save(window, "journal")

    window.steps.setCurrentRow(0)
    dialog = window.show_duplicates()
    dialog.resize(1080, 640)
    dialog.start()
    while dialog.report is None:
        settle(300)
    save(dialog, "duplicates")
    dialog.close()
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
