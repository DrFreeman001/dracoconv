"""Étape 5 : résultats du lot, filtres, export, relance des échecs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ...batch import Journal
from ...i18n import format_size, reason_text, tr

_FILTERS = (None, "done", "skipped", "failed", "pending")
_MAX_ROWS = 2000


class JournalPage(QWidget):
    retry_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.journal: Journal | None = None
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.filter_label = QLabel()
        self.filter_combo = QComboBox()
        for state in _FILTERS:
            self.filter_combo.addItem("", state)
        self.export_button = QPushButton()
        self.retry_failed_button = QPushButton()
        top = QHBoxLayout()
        for widget in (self.filter_label, self.filter_combo):
            top.addWidget(widget)
        top.addStretch(1)
        top.addWidget(self.retry_failed_button)
        top.addWidget(self.export_button)
        self.table = QTableWidget(0, 6)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        self.filter_combo.currentIndexChanged.connect(lambda *_: self._fill())
        self.export_button.clicked.connect(self._ask_export)
        self.retry_failed_button.clicked.connect(self.retry_requested.emit)
        self.retranslate()

    def load(self, journal: Journal | None) -> None:
        self.journal = journal
        self._fill()

    def export_to(self, path: Path) -> None:
        if self.journal is not None:
            self.journal.export_csv(Path(path))

    def _ask_export(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, tr("gui.journal.export"), "journal.csv", "CSV (*.csv)")
        if name:
            self.export_to(Path(name))

    def _fill(self) -> None:
        self.table.setRowCount(0)
        journal = self.journal
        self.export_button.setEnabled(journal is not None)
        if journal is None:
            self.summary_label.setText(tr("gui.journal.empty"))
            self.retry_failed_button.setEnabled(False)
            return
        summary = journal.summary()
        self.summary_label.setText(tr(
            "gui.journal.summary", done=summary["done"], skipped=summary["skipped"], failed=summary["failed"],
            pending=summary["pending"], before=format_size(summary["bytes_before"]),
            after=format_size(summary["bytes_after"])))
        self.retry_failed_button.setEnabled(summary["failed"] > 0)
        for record in journal.rows(self.filter_combo.currentData())[:_MAX_ROWS]:
            reason = record["reason"] or record["note"]
            after = format_size(record["size_after"]) if record["size_after"] is not None else ""
            values = (record["src"], record["dst"] if record["state"] == "done" else "",
                      tr("state." + record["state"]), reason_text(reason) if reason else "",
                      format_size(record["size_before"] or 0), after)
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, text in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(text))

    def retranslate(self) -> None:
        self.filter_label.setText(tr("gui.journal.filter"))
        self.filter_combo.setItemText(0, tr("gui.journal.all"))
        for index, state in enumerate(_FILTERS[1:], start=1):
            self.filter_combo.setItemText(index, tr("state." + state))
        self.export_button.setText(tr("gui.journal.export"))
        self.retry_failed_button.setText(tr("gui.journal.retry"))
        self.table.setHorizontalHeaderLabels([
            tr("gui.convert.col.source"), tr("gui.convert.col.destination"), tr("gui.journal.col.state"),
            tr("gui.journal.col.reason"), tr("gui.journal.col.before"), tr("gui.journal.col.after")])
        self._fill()
