"""Fenêtre « Dossiers surveillés » : réglages et tâche planifiée de Windows."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QVBoxLayout,
)

from ..i18n import tr
from .. import watch


def _interval_text(minutes: int) -> str:
    if minutes < 60:
        return tr("gui.watch.every_min", n=minutes)
    if minutes < 1440:
        return tr("gui.watch.every_hours", n=minutes // 60)
    return tr("gui.watch.every_day")


class WatchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("gui.watch.title"))
        self.resize(760, 640)
        config = watch.WatchConfig.load()

        intro = QLabel(tr("gui.watch.intro"))
        intro.setWordWrap(True)
        self.enabled_box = QCheckBox(tr("gui.watch.enabled"))
        self.enabled_box.setChecked(watch.task_installed())

        self.folders = QListWidget()
        self.folders.addItems(config.folders)
        add = QPushButton(tr("gui.source.add_folder"))
        remove = QPushButton(tr("gui.source.remove"))
        add.clicked.connect(self._add_folder)
        remove.clicked.connect(lambda: [self.folders.takeItem(self.folders.row(i))
                                        for i in self.folders.selectedItems()])
        folder_buttons = QHBoxLayout()
        folder_buttons.addWidget(add)
        folder_buttons.addWidget(remove)
        folder_buttons.addStretch(1)

        from ..settings import PROFILES, user_profiles

        self.profile_combo = QComboBox()
        for name in PROFILES:
            self.profile_combo.addItem(tr("profile." + name), name)
        for name in user_profiles():
            self.profile_combo.addItem(name, name)
        index = self.profile_combo.findData(config.profile)
        self.profile_combo.setCurrentIndex(max(0, index))

        self.keep_radio = QRadioButton(tr("gui.convert.keep"))
        self.replace_radio = QRadioButton(tr("gui.convert.replace"))
        self.replace_confirm = QCheckBox(tr("gui.convert.replace_confirm"))
        self.replace_confirm.setStyleSheet("margin-left: 24px;")
        (self.replace_radio if config.originals == "replace" else self.keep_radio).setChecked(True)
        self.replace_confirm.setChecked(config.originals == "replace")
        self.replace_radio.toggled.connect(self._refresh)
        self.replace_confirm.toggled.connect(self._refresh)

        self.interval_combo = QComboBox()
        for minutes in watch.INTERVALS_MIN:
            self.interval_combo.addItem(_interval_text(minutes), minutes)
        self.interval_combo.setCurrentIndex(max(0, self.interval_combo.findData(config.interval_min)))
        note = QLabel(tr("gui.watch.note"))
        note.setWordWrap(True)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(200)

        self.run_button = QPushButton(tr("gui.watch.run_now"))
        self.save_button = QPushButton(tr("gui.watch.save"))
        close = QPushButton(tr("gui.dupes.close"))
        self.run_button.clicked.connect(self._run_now)
        self.save_button.clicked.connect(self.save)
        close.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addWidget(self.run_button)
        bottom.addStretch(1)
        bottom.addWidget(self.save_button)
        bottom.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.enabled_box)
        layout.addWidget(QLabel(tr("gui.watch.folders")))
        layout.addWidget(self.folders, 1)
        layout.addLayout(folder_buttons)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("gui.watch.profile")))
        row.addWidget(self.profile_combo, 1)
        row.addWidget(QLabel(tr("gui.watch.interval")))
        row.addWidget(self.interval_combo)
        layout.addLayout(row)
        layout.addWidget(self.keep_radio)
        layout.addWidget(self.replace_radio)
        layout.addWidget(self.replace_confirm)
        layout.addWidget(note)
        layout.addWidget(QLabel(tr("gui.watch.log")))
        layout.addWidget(self.log_view, 1)
        layout.addLayout(bottom)
        self._load_log()
        self._refresh()

    def _refresh(self) -> None:
        self.replace_confirm.setVisible(self.replace_radio.isChecked())
        ok = not self.replace_radio.isChecked() or self.replace_confirm.isChecked()
        self.save_button.setEnabled(ok)
        self.run_button.setEnabled(watch.task_installed())

    def _load_log(self) -> None:
        lines = watch.read_log(30)
        self.log_view.setPlainText("\n".join(lines) if lines else tr("gui.watch.log_empty"))

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("gui.source.add_folder"))
        if folder and not self.folders.findItems(folder, self._exact()):
            self.folders.addItem(folder)

    @staticmethod
    def _exact():
        from PySide6.QtCore import Qt

        return Qt.MatchFlag.MatchFixedString

    def config(self) -> watch.WatchConfig:
        return watch.WatchConfig(
            folders=[self.folders.item(i).text() for i in range(self.folders.count())],
            profile=self.profile_combo.currentData(),
            originals="replace" if self.replace_radio.isChecked() else "keep",
            interval_min=self.interval_combo.currentData(),
        )

    def save(self) -> bool:
        config = self.config()
        config.save()
        try:
            if self.enabled_box.isChecked() and config.folders:
                watch.install_task(config)
            else:
                watch.remove_task()
        except OSError as exc:
            QMessageBox.warning(self, tr("gui.watch.title"), tr("gui.watch.task_failed", error=str(exc)))
            return False
        self._refresh()
        return True

    def _run_now(self) -> None:
        try:
            watch.run_task_now()
        except OSError as exc:
            QMessageBox.warning(self, tr("gui.watch.title"), tr("gui.watch.task_failed", error=str(exc)))
            return
        QMessageBox.information(self, tr("gui.watch.title"), tr("gui.watch.started"))
