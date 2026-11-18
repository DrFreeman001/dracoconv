"""Passage de surveillance lancé par la tâche planifiée : aucune fenêtre, une notification si des fichiers ont
été convertis, puis fin du processus."""
from __future__ import annotations

import sys


def notify(summary: dict, wait_ms: int = 8000) -> None:
    from PySide6.QtCore import QFileInfo, QTimer
    from PySide6.QtWidgets import QApplication, QFileIconProvider, QStyle, QSystemTrayIcon

    from ..i18n import format_size, tr

    app = QApplication.instance() or QApplication([])
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return
    icon = QFileIconProvider().icon(QFileInfo(sys.executable))
    if icon.isNull():
        icon = app.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
    body = tr("gui.notify.body", done=summary["done"], failed=summary["failed"], skipped=summary["skipped"])
    saved = summary["bytes_before"] - summary["bytes_after"]
    if saved > 0:
        body += " " + tr("gui.notify.saved", size=format_size(saved))
    tray = QSystemTrayIcon(icon)
    tray.setToolTip("dracoconv")
    tray.show()
    tray.showMessage(tr("gui.watch.notify_title"), body, QSystemTrayIcon.MessageIcon.Information, wait_ms)
    QTimer.singleShot(wait_ms, app.quit)
    app.exec()
    tray.hide()


def run() -> int:
    from ..watch import WatchConfig, run_once

    summary = run_once(WatchConfig.load())
    if summary["done"] or summary["failed"]:
        notify(summary)
    return 1 if summary["failed"] else 0
