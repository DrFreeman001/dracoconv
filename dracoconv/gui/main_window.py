"""Fenêtre principale : cinq étapes, changement de langue sans redémarrage."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QFileInfo, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices
from PySide6.QtWidgets import (
    QLabel,
    QApplication, QFileIconProvider, QHBoxLayout, QListWidget, QMainWindow, QPushButton, QStackedWidget, QStyle,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from ..config import load_prefs, save_prefs
from .taskbar import TaskbarProgress
from .theme import THEMES, apply_theme
from ..i18n import format_size, get_language, set_language, tr
from .pages.convert import ConvertPage
from .pages.journal import JournalPage
from .pages.projection import ProjectionPage
from .pages.settings import SettingsPage
from .pages.source import SourcePage
from .state import AppState

class _UpdateNotice(QObject):
    """Vérification en arrière-plan ; le signal found arrive sur le fil de l'interface."""

    found = Signal(str)

    def start(self) -> None:
        import threading

        from .. import updates

        def run() -> None:
            version = updates.newer_version()
            if version:
                self.found.emit(version)

        threading.Thread(target=run, daemon=True).start()


_STEPS = ("source", "settings", "projection", "convert", "journal")
_LANGUAGE_NAMES = {"fr": "Français", "en": "English"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.state = AppState()
        self.settings_page = SettingsPage()
        self.source_page = SourcePage(self.state)
        self.projection_page = ProjectionPage(self.state, self.settings_page.settings, self.settings_page.engine)
        self.convert_page = ConvertPage(self.state, self.settings_page.settings, self.settings_page.engine)
        self.journal_page = JournalPage()

        self.steps = QListWidget()
        self.steps.setFixedWidth(210)
        self.steps.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.steps.setSpacing(4)
        self.pages = QStackedWidget()
        for page in (self.source_page, self.settings_page, self.projection_page, self.convert_page,
                     self.journal_page):
            self.pages.addWidget(page)
            self.steps.addItem("")
        self.previous_button = QPushButton()
        self.next_button = QPushButton()
        navigation = QHBoxLayout()
        navigation.addStretch(1)
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.next_button)
        right = QVBoxLayout()
        right.addWidget(self.pages, 1)
        right.addLayout(navigation)
        central = QWidget()
        body = QHBoxLayout(central)
        body.addWidget(self.steps)
        body.addLayout(right, 1)
        self.setCentralWidget(central)
        self.resize(1280, 860)

        self.language_menu = self.menuBar().addMenu("")
        group = QActionGroup(self)
        self.language_actions: dict[str, QAction] = {}
        for code, name in _LANGUAGE_NAMES.items():
            action = QAction(name, self, checkable=True)
            action.setChecked(code == get_language())
            action.triggered.connect(lambda _checked=False, code=code: self.set_language(code))
            group.addAction(action)
            self.language_menu.addAction(action)
            self.language_actions[code] = action

        self.theme_menu = self.menuBar().addMenu("")
        theme_group = QActionGroup(self)
        self.theme_actions = {}
        for name in THEMES:
            action = QAction("", self, checkable=True)
            action.triggered.connect(lambda _checked=False, name=name: self.set_theme(name))
            theme_group.addAction(action)
            self.theme_menu.addAction(action)
            self.theme_actions[name] = action
        self._theme = "system"
        QApplication.styleHints().colorSchemeChanged.connect(self._system_theme_changed)
        self.set_theme(load_prefs().get("theme", "system"), persist=False)

        from .. import updates

        self.help_menu = self.menuBar().addMenu("")
        self.updates_action = QAction("", self, checkable=True)
        self.updates_action.setChecked(updates.enabled())
        self.updates_action.toggled.connect(updates.set_enabled)
        self.project_action = QAction("", self)
        self.project_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/DrFreeman001/dracoconv")))
        self.help_menu.addAction(self.updates_action)
        self.help_menu.addAction(self.project_action)
        self._new_version = None
        self._update_notice = _UpdateNotice(self)
        self._update_notice.found.connect(self._show_new_version)
        if updates.due():
            self._update_notice.start()

        self.steps.currentRowChanged.connect(self._show_step)
        self.previous_button.clicked.connect(lambda: self.steps.setCurrentRow(max(0, self.steps.currentRow() - 1)))
        self.next_button.clicked.connect(
            lambda: self.steps.setCurrentRow(min(len(_STEPS) - 1, self.steps.currentRow() + 1)))
        self.source_page.scanned.connect(self._inventory_changed)
        self.source_page.direction_changed.connect(self._direction_changed)
        self.settings_page.changed.connect(self._settings_changed)
        self.projection_page.quality_ready.connect(
            lambda _q: self.settings_page.set_reference_extent(self.state.reference_extent))
        self.convert_page.journal_changed.connect(self.journal_page.load)
        self._taskbar = TaskbarProgress()
        self.convert_page.progressed.connect(self._batch_progress)
        self.convert_page.finished.connect(self._batch_finished)
        self.journal_page.retry_requested.connect(self.convert_page.retry_failed)

        self.steps.setCurrentRow(0)
        self.retranslate()
        # Glisser-déposer : fichiers et dossiers lâchés n'importe où sur la fenêtre, comme le clic droit.
        self.setAcceptDrops(True)

    @staticmethod
    def _dropped_paths(mime) -> list[Path]:
        if not mime.hasUrls():
            return []
        return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile() and url.toLocalFile()]

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - API Qt
        if self._dropped_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - API Qt
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - API Qt
        paths = self._dropped_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.open_paths(paths)

    def open_paths(self, paths, direction: str | None = None) -> None:
        """Ouvre des fichiers ou dossiers (clic droit de l'Explorateur) et ramène la fenêtre devant."""
        from .launch import infer_direction

        paths = list(paths)
        if not paths:
            return
        self.steps.setCurrentRow(0)
        self.source_page.open_paths(paths, direction or infer_direction(paths))
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _batch_progress(self, done: int, total: int) -> None:
        hwnd = int(self.winId())
        if done < 0:
            self._taskbar.clear(hwnd)
        else:
            self._taskbar.set_value(hwnd, done, total)

    def _batch_finished(self, summary: dict) -> None:
        self._taskbar.clear(int(self.winId()))
        if not self.isActiveWindow():
            self._notify(summary)

    def _notify(self, summary: dict) -> None:
        """Notification Windows de fin de lot, quand la fenêtre n'est pas au premier plan."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = QFileIconProvider().icon(QFileInfo(sys.executable))
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        title = tr("gui.notify.paused" if summary.get("paused") else "gui.notify.finished")
        body = tr("gui.notify.body", done=summary.get("done", 0), failed=summary.get("failed", 0),
                  skipped=summary.get("skipped", 0))
        saved = summary.get("bytes_before", 0) - summary.get("bytes_after", 0)
        if saved > 0:
            body += " " + tr("gui.notify.saved", size=format_size(saved))
        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip("dracoconv")
        tray.messageClicked.connect(self._bring_to_front)
        tray.activated.connect(lambda _reason: self._bring_to_front())
        tray.show()
        tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 10_000)
        self._last_notification = (title, body)
        # L'icône ne sert qu'à porter la notification : elle disparaît ensuite.
        QTimer.singleShot(20_000, tray.deleteLater)

    def _bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _show_step(self, row: int) -> None:
        self.pages.setCurrentIndex(row)
        self.previous_button.setEnabled(row > 0)
        self.next_button.setEnabled(row < len(_STEPS) - 1)
        page = self.pages.widget(row)
        if page is self.projection_page:
            self.projection_page.refresh_instant()
        elif page is self.convert_page:
            self.convert_page.refresh_plan()

    def _inventory_changed(self, _inventory) -> None:
        self.settings_page.paths = list(self.state.roots)
        self.projection_page.settings_changed()
        self.convert_page.refresh_plan()

    def _settings_changed(self) -> None:
        self.projection_page.settings_changed()
        self.convert_page.refresh_plan()

    def _direction_changed(self, direction: str) -> None:
        self.state.inventory = None
        self.state.projection = None
        self.settings_page.decode_note.setVisible(direction == "decode")
        self.projection_page.refresh_instant()
        self.convert_page.direction_changed()

    def set_theme(self, name: str, persist: bool = True) -> None:
        name = name if name in THEMES else "system"
        self._theme = name
        QApplication.instance().setProperty("dracoconvTheme", name)
        apply_theme(name)
        self.theme_actions[name].setChecked(True)
        if persist:
            save_prefs({"theme": name})
        self._refresh_theme_details()

    def _system_theme_changed(self, scheme) -> None:
        if QApplication.instance().property("dracoconvTheme") == "system":
            apply_theme("system", system_scheme=scheme)
            self._refresh_theme_details()

    def _refresh_theme_details(self) -> None:
        dark = QApplication.palette().color(self.backgroundRole()).lightness() < 128
        warning = "#efb45e" if dark else "#b45309"
        self.convert_page.warning_label.setStyleSheet(f"color: {warning}; font-weight: 600;")
        self.projection_page._draw_chart()

    def set_language(self, lang: str) -> None:
        set_language(lang)
        save_prefs({"language": lang})
        self.language_actions[lang].setChecked(True)
        self.retranslate()

    def _show_new_version(self, version: str) -> None:
        from .. import updates

        self._new_version = version
        label = QLabel()
        label.setOpenExternalLinks(True)
        label.setText(f'<a href="{updates.RELEASES}">' + tr("gui.update.available", version=version) + "</a>")
        self.statusBar().addPermanentWidget(label)

    def retranslate(self) -> None:
        self.setWindowTitle(tr("gui.title"))
        self.help_menu.setTitle(tr("gui.menu.help"))
        self.updates_action.setText(tr("gui.update.check"))
        self.project_action.setText(tr("gui.update.project"))
        self.theme_menu.setTitle(tr("gui.menu.theme"))
        for name, action in self.theme_actions.items():
            action.setText(tr("gui.theme." + name))
        self.language_menu.setTitle(tr("gui.menu.language"))
        for row, step in enumerate(_STEPS):
            self.steps.item(row).setText(tr(f"gui.step.{step}"))
        self.previous_button.setText(tr("gui.nav.previous"))
        self.next_button.setText(tr("gui.nav.next"))
        for page in (self.source_page, self.settings_page, self.projection_page, self.convert_page,
                     self.journal_page):
            page.retranslate()

    def closeEvent(self, event) -> None:  # noqa: N802 - API Qt
        self.projection_page.stop()
        self.convert_page.wait()
        super().closeEvent(event)
