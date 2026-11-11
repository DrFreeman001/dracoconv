"""Étape 4 : sort des originaux, plan, lancement et suivi de la conversion."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QProgressBar, QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...batch import BatchOptions, Journal, PlanItem, build_plan, check_free_space, run
from ...config import data_dir
from ...estimate import instant
from ...i18n import format_size, tr
from ...settings import EncodeSettings
from ..state import AppState
from ..workers import Worker

_MODES = ("keep", "mirror", "replace")
_FORMATS = ("stl", "obj", "ply")
_MAX_PLAN_ROWS = 500


class ConvertPage(QWidget):
    finished = Signal(object)
    journal_changed = Signal(object)

    def __init__(self, state: AppState, get_settings: Callable[[], EncodeSettings],
                 get_engine: Callable[[], str | None], parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._get_settings, self._get_engine = get_settings, get_engine
        self._worker: Worker | None = None
        self._items: list[PlanItem] = []
        self._status: tuple[str, dict] = ("gui.convert.idle", {})
        self._done = 0

        self.originals_group_box = QGroupBox()
        self.originals_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QRadioButton] = {}
        originals_layout = QVBoxLayout(self.originals_group_box)
        for mode in _MODES:
            button = QRadioButton()
            self.mode_buttons[mode] = button
            self.originals_group.addButton(button)
            originals_layout.addWidget(button)
        self.mode_buttons["keep"].setChecked(True)
        self.mirror_label = QLabel()
        self.mirror_edit = QLineEdit()
        self.browse_button = QPushButton()
        mirror_row = QHBoxLayout()
        for widget in (self.mirror_label, self.mirror_edit, self.browse_button):
            mirror_row.addWidget(widget)
        originals_layout.addLayout(mirror_row)
        self.replace_confirm = QCheckBox()
        originals_layout.addWidget(self.replace_confirm)

        self.workers_label = QLabel()
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, max(1, os.cpu_count() or 1))
        self.workers_spin.setValue(BatchOptions().resolved_workers())
        self.format_label = QLabel()
        self.format_combo = QComboBox()
        for fmt in _FORMATS:
            self.format_combo.addItem("", fmt)
        self.allow_no_gain = QCheckBox()
        options_row = QHBoxLayout()
        for widget in (self.workers_label, self.workers_spin, self.format_label, self.format_combo, self.allow_no_gain):
            options_row.addWidget(widget)
        options_row.addStretch(1)

        self.plan_group = QGroupBox()
        self.plan_label = QLabel()
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color: #b45309; font-weight: 600;")
        self.plan_table = QTableWidget(0, 4)
        self.plan_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.plan_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.plan_table.verticalHeader().hide()
        plan_layout = QVBoxLayout(self.plan_group)
        plan_layout.addWidget(self.plan_label)
        plan_layout.addWidget(self.warning_label)
        plan_layout.addWidget(self.plan_table)

        self.start_button = QPushButton()
        self.stop_button = QPushButton()
        self.stop_button.setEnabled(False)
        self.progress = QProgressBar()
        self.status_label = QLabel()
        run_row = QHBoxLayout()
        run_row.addWidget(self.start_button)
        run_row.addWidget(self.stop_button)
        run_row.addWidget(self.progress, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.originals_group_box)
        layout.addLayout(options_row)
        layout.addWidget(self.plan_group, 1)
        layout.addLayout(run_row)
        layout.addWidget(self.status_label)

        self.originals_group.buttonToggled.connect(lambda *_: self._options_changed())
        self.mirror_edit.textChanged.connect(lambda *_: self._options_changed())
        self.replace_confirm.toggled.connect(lambda *_: self._update_buttons())
        self.format_combo.currentIndexChanged.connect(lambda *_: self._options_changed())
        self.browse_button.clicked.connect(self._browse)
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.request_stop)
        self.retranslate()
        self._options_changed()

    # -- options -------------------------------------------------------------------------------

    def mode(self) -> str:
        return next(mode for mode, button in self.mode_buttons.items() if button.isChecked())

    def select_originals(self, mode: str) -> None:
        self.mode_buttons[mode].setChecked(True)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("gui.convert.mirror_dir"))
        if folder:
            self.mirror_edit.setText(folder)

    def options(self, for_display: bool = False) -> BatchOptions:
        mirror = self.mirror_edit.text().strip()
        return BatchOptions(
            direction=self.state.direction, originals=self.mode(), mirror_dir=Path(mirror) if mirror else None,
            # Le plan s'affiche avant la confirmation ; c'est le bouton de lancement qui la garantit.
            confirm_replace=True if for_display else self.replace_confirm.isChecked(),
            workers=self.workers_spin.value(), output_format=self.format_combo.currentData(),
            prefer_engine=self._get_engine(), skip_if_no_gain=not self.allow_no_gain.isChecked(),
        )

    def _options_changed(self) -> None:
        mode = self.mode()
        for widget in (self.mirror_label, self.mirror_edit, self.browse_button):
            widget.setVisible(mode == "mirror")
        self.replace_confirm.setVisible(mode == "replace")
        if mode != "replace":
            self.replace_confirm.setChecked(False)
        self.refresh_plan()

    def direction_changed(self) -> None:
        decoding = self.state.direction == "decode"
        self.format_label.setVisible(decoding)
        self.format_combo.setVisible(decoding)
        self.allow_no_gain.setVisible(not decoding)
        self.refresh_plan()

    # -- plan ----------------------------------------------------------------------------------

    def refresh_plan(self) -> None:
        self._items = []
        inventory = self.state.inventory
        ready = inventory is not None and not (self.mode() == "mirror" and not self.mirror_edit.text().strip())
        if ready:
            try:
                self._items = build_plan(inventory, list(self.state.roots), self._get_settings(),
                                         self.options(for_display=True))
            except ValueError:
                self._items = []
        self._fill_plan()
        self._update_buttons()

    def _todo(self) -> list[PlanItem]:
        return [item for item in self._items if not item.skip_reason]

    def _fill_plan(self) -> None:
        todo = self._todo()
        self.plan_table.setRowCount(0)
        self.plan_label.setText(tr(
            "gui.convert.plan_summary", n=len(todo), size=format_size(sum(i.size for i in todo)),
            skipped=len(self._items) - len(todo)))
        for item in self._items[:_MAX_PLAN_ROWS]:
            remark = ""
            if item.skip_reason:
                remark = tr("reason." + item.skip_reason)
            elif item.warning:
                remark = tr("warning." + item.warning)
            row = self.plan_table.rowCount()
            self.plan_table.insertRow(row)
            for column, text in enumerate((str(item.src), str(item.dst), format_size(item.size), remark)):
                self.plan_table.setItem(row, column, QTableWidgetItem(text))
        if len(self._items) > _MAX_PLAN_ROWS:
            row = self.plan_table.rowCount()
            self.plan_table.insertRow(row)
            self.plan_table.setItem(
                row, 0, QTableWidgetItem(tr("gui.convert.plan_truncated", n=len(self._items) - _MAX_PLAN_ROWS)))
        self.warning_label.setText("")
        if todo and self.state.direction == "encode" and self.mode() != "replace" and self.state.inventory is not None:
            needed = instant(self.state.inventory, self._get_settings()).projected_bytes
            target = Path(self.mirror_edit.text().strip()) if self.mode() == "mirror" else todo[0].dst.parent
            try:
                if not check_free_space(target, needed):
                    self.warning_label.setText(tr("gui.convert.free_space", needed=format_size(needed)))
            except OSError:
                pass

    def _update_buttons(self) -> None:
        running = self._worker is not None
        allowed = bool(self._todo()) and (self.mode() != "replace" or self.replace_confirm.isChecked())
        self.start_button.setEnabled(allowed and not running)
        self.stop_button.setEnabled(running)

    # -- exécution -----------------------------------------------------------------------------

    def start(self) -> None:
        if self._worker is not None or not self._todo():
            return
        if self.mode() == "replace" and not self.replace_confirm.isChecked():
            return
        settings, options = self._get_settings(), self.options()
        folder = data_dir() / "journals"
        folder.mkdir(parents=True, exist_ok=True)
        journal = Journal(folder / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{options.direction}.sqlite")
        journal.add_plan(self._items, settings)
        self._launch(journal, settings, options)

    def retry_failed(self) -> None:
        """Relance les fichiers en échec du dernier lot."""
        journal = self.state.journal
        if self._worker is not None or journal is None or journal.retry_failed() == 0:
            return
        self._launch(journal, journal.settings(), self.options())

    def _launch(self, journal: Journal, settings: EncodeSettings, options: BatchOptions) -> None:
        self.state.journal = journal
        total = len(journal.pending())
        self._done = 0
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(0)
        self._set_status("gui.convert.running", done=0, total=total)
        self._worker = Worker(run, journal, settings, options, progress_arg="on_progress", stop_arg="stop", parent=self)
        self._worker.progress.connect(lambda _result, total=total: self._on_progress(total))
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._update_buttons()
        self._worker.start()
        self._update_buttons()

    def request_stop(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()

    def _on_progress(self, total: int) -> None:
        self._done += 1
        self.progress.setValue(self._done)
        self._set_status("gui.convert.running", done=self._done, total=total)

    def _on_finished(self, summary: dict) -> None:
        self._worker = None
        if summary.get("paused"):
            self._set_status("gui.convert.paused", reason_code=summary["paused"])
        else:
            self._set_status("gui.convert.finished",
                             **{k: summary[k] for k in ("done", "skipped", "failed", "pending")})
        self.journal_changed.emit(self.state.journal)
        self.refresh_plan()
        self.finished.emit(summary)

    def _on_failed(self, message: str) -> None:
        self._worker = None
        self.status_label.setText(message)
        self._update_buttons()

    def _set_status(self, key: str, **values) -> None:
        self._status = (key, values)
        shown = dict(values)
        if "reason_code" in shown:
            shown["reason"] = tr("reason." + shown.pop("reason_code"))
        self.status_label.setText(tr(key, **shown))

    def wait(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()
            self._worker.wait()

    # -- langue --------------------------------------------------------------------------------

    def retranslate(self) -> None:
        self.originals_group_box.setTitle(tr("gui.convert.originals"))
        for mode, button in self.mode_buttons.items():
            button.setText(tr(f"gui.convert.{mode}"))
        self.mirror_label.setText(tr("gui.convert.mirror_dir"))
        self.browse_button.setText(tr("gui.convert.browse"))
        self.replace_confirm.setText(tr("gui.convert.replace_confirm"))
        self.workers_label.setText(tr("gui.convert.workers"))
        self.format_label.setText(tr("gui.convert.format"))
        for index, fmt in enumerate(_FORMATS):
            self.format_combo.setItemText(index, tr(f"gui.convert.format.{fmt}"))
        self.allow_no_gain.setText(tr("gui.convert.allow_no_gain"))
        self.plan_group.setTitle(tr("gui.convert.plan"))
        self.plan_table.setHorizontalHeaderLabels([
            tr("gui.convert.col.source"), tr("gui.convert.col.destination"), tr("gui.convert.col.size"),
            tr("gui.convert.col.remark")])
        self.start_button.setText(tr("gui.convert.start"))
        self.stop_button.setText(tr("gui.convert.stop"))
        self._set_status(self._status[0], **self._status[1])
        self._fill_plan()
        self.direction_changed_texts()

    def direction_changed_texts(self) -> None:
        decoding = self.state.direction == "decode"
        self.format_label.setVisible(decoding)
        self.format_combo.setVisible(decoding)
        self.allow_no_gain.setVisible(not decoding)
