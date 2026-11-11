"""Fenêtre principale : cinq étapes, changement de langue sans redémarrage."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QHBoxLayout, QListWidget, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from ..config import save_prefs
from ..i18n import get_language, set_language, tr
from .pages.convert import ConvertPage
from .pages.journal import JournalPage
from .pages.projection import ProjectionPage
from .pages.settings import SettingsPage
from .pages.source import SourcePage
from .state import AppState

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
        self.journal_page.retry_requested.connect(self.convert_page.retry_failed)

        self.steps.setCurrentRow(0)
        self.retranslate()

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

    def set_language(self, lang: str) -> None:
        set_language(lang)
        save_prefs({"language": lang})
        self.language_actions[lang].setChecked(True)
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(tr("gui.title"))
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
