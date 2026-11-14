"""Étape 1 : choix des fichiers et recensement (lecture seule)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...i18n import format_size, tr
from ...io.sniff import FileKind
from ...scan import DEFAULT_EXCLUDES, Inventory, ScanOptions, scan
from ..state import AppState
from ..workers import Worker
from ..activity import ActivityBar

_KINDS = (FileKind.STL, FileKind.OBJ, FileKind.PLY, FileKind.THREEMF, FileKind.ZIP, FileKind.DRC)
_ENCODE_KINDS = {FileKind.STL, FileKind.OBJ, FileKind.PLY, FileKind.THREEMF, FileKind.ZIP}
_DECODE_KINDS = {FileKind.DRC, FileKind.ZIP}


class SourcePage(QWidget):
    scanned = Signal(object)
    direction_changed = Signal(str)

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._worker: Worker | None = None
        self._status: tuple[str, dict] = ("gui.source.empty", {})

        self.intro_label = QLabel()
        self.intro_label.setWordWrap(True)
        self.direction_label = QLabel()
        self.direction_combo = QComboBox()
        self.direction_combo.addItem("", "encode")
        self.direction_combo.addItem("", "decode")
        direction_row = QHBoxLayout()
        direction_row.addWidget(self.direction_label)
        direction_row.addWidget(self.direction_combo, 1)

        self.roots_group = QGroupBox()
        self.roots_list = QListWidget()
        self.add_folder_button = QPushButton()
        self.add_files_button = QPushButton()
        self.remove_button = QPushButton()
        buttons = QHBoxLayout()
        for button in (self.add_folder_button, self.add_files_button, self.remove_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        roots_layout = QVBoxLayout(self.roots_group)
        roots_layout.addWidget(self.roots_list)
        roots_layout.addLayout(buttons)

        self.kinds_group = QGroupBox()
        kinds_layout = QHBoxLayout(self.kinds_group)
        self.kind_boxes: dict[FileKind, QCheckBox] = {}
        for kind in _KINDS:
            box = QCheckBox()
            box.setChecked(True)
            self.kind_boxes[kind] = box
            kinds_layout.addWidget(box)
        kinds_layout.addStretch(1)
        self.open_zips_box = QCheckBox()
        self.open_zips_box.setChecked(True)
        self.exclude_label = QLabel()
        self.exclude_edit = QLineEdit()
        exclude_row = QHBoxLayout()
        exclude_row.addWidget(self.exclude_label)
        exclude_row.addWidget(self.exclude_edit, 1)

        self.scan_button = QPushButton()
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        scan_row = QHBoxLayout()
        scan_row.addWidget(self.scan_button)
        scan_row.addWidget(self.status_label, 1)

        self.result_group = QGroupBox()
        self.table = QTableWidget(0, 3)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.ignored_label = QLabel()
        self.ignored_label.setWordWrap(True)
        result_layout = QVBoxLayout(self.result_group)
        result_layout.addWidget(self.table)
        result_layout.addWidget(self.ignored_label)

        self.activity = ActivityBar()
        layout = QVBoxLayout(self)
        layout.addWidget(self.activity)
        layout.addWidget(self.intro_label)
        layout.addLayout(direction_row)
        layout.addWidget(self.roots_group, 1)
        layout.addWidget(self.kinds_group)
        layout.addWidget(self.open_zips_box)
        layout.addLayout(exclude_row)
        layout.addLayout(scan_row)
        layout.addWidget(self.result_group, 2)

        self.add_folder_button.clicked.connect(self._pick_folder)
        self.add_files_button.clicked.connect(self._pick_files)
        self.remove_button.clicked.connect(self._remove_selected)
        self.scan_button.clicked.connect(self.start_scan)
        self.direction_combo.currentIndexChanged.connect(self._direction_chosen)
        self._pending_scan = QTimer(self)
        self._pending_scan.setSingleShot(True)
        self._pending_scan.setInterval(600)
        self._pending_scan.timeout.connect(self._scan_when_idle)
        self._apply_direction()
        self.retranslate()

    # -- sources -------------------------------------------------------------------------------

    def add_root(self, path: Path) -> None:
        path = Path(path)
        if path not in self.state.roots:
            self.state.roots.append(path)
            self.roots_list.addItem(str(path))

    def open_paths(self, paths, direction: str) -> None:
        """Ajoute des chemins venus de l'Explorateur, règle le sens et relance l'analyse un peu plus tard,
        pour qu'une sélection de plusieurs fichiers arrivant un par un ne lance qu'une analyse."""
        index = self.direction_combo.findData(direction)
        if index >= 0 and index != self.direction_combo.currentIndex():
            self.direction_combo.setCurrentIndex(index)
        for path in paths:
            self.add_root(Path(path))
        self._pending_scan.start()

    def _scan_when_idle(self) -> None:
        if self._worker is not None:
            self._pending_scan.start()
        else:
            self.start_scan()

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("gui.source.add_folder"))
        if folder:
            self.add_root(Path(folder))

    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, tr("gui.source.add_files"))
        for name in files:
            self.add_root(Path(name))

    def _remove_selected(self) -> None:
        for item in self.roots_list.selectedItems():
            row = self.roots_list.row(item)
            self.roots_list.takeItem(row)
            del self.state.roots[row]

    # -- sens de conversion --------------------------------------------------------------------

    def _direction_chosen(self, _index: int) -> None:
        self.state.direction = self.direction_combo.currentData()
        self._apply_direction()
        self.direction_changed.emit(self.state.direction)

    def _apply_direction(self) -> None:
        wanted = _ENCODE_KINDS if self.state.direction == "encode" else _DECODE_KINDS
        for kind, box in self.kind_boxes.items():
            box.setEnabled(kind in wanted)

    def selected_kinds(self) -> frozenset[FileKind]:
        wanted = _ENCODE_KINDS if self.state.direction == "encode" else _DECODE_KINDS
        return frozenset(k for k, box in self.kind_boxes.items() if box.isChecked() and k in wanted)

    # -- analyse -------------------------------------------------------------------------------

    def scan_options(self) -> ScanOptions:
        extra = tuple(name.strip() for name in self.exclude_edit.text().split(",") if name.strip())
        return ScanOptions(kinds=self.selected_kinds(), exclude_dirs=DEFAULT_EXCLUDES + extra,
                           look_inside_zips=self.open_zips_box.isChecked())

    def start_scan(self) -> None:
        if self._worker is not None or not self.state.roots:
            return
        self.activity.start()
        self.scan_button.setEnabled(False)
        self._set_status("gui.source.scanning", n=0)
        self._worker = Worker(scan, list(self.state.roots), self.scan_options(),
                              progress_arg="on_progress", stop_arg="stop", parent=self)
        self._worker.progress.connect(lambda n: self._set_status("gui.source.scanning", n=n))
        self._worker.finished_ok.connect(self._scan_done)
        self._worker.failed.connect(self._scan_failed)
        self._worker.start()

    def _scan_failed(self, message: str) -> None:
        self._worker = None
        self.activity.stop()
        self.scan_button.setEnabled(True)
        self.status_label.setText(message)

    def _scan_done(self, inventory: Inventory) -> None:
        self._worker = None
        self.activity.stop()
        self.scan_button.setEnabled(True)
        self.state.inventory = inventory
        self.state.projection = None
        self._set_status("gui.source.done", n=inventory.count(), size=inventory.total_bytes())
        self._fill_table()
        self.scanned.emit(inventory)

    def _set_status(self, key: str, **values) -> None:
        self._status = (key, values)
        shown = dict(values)
        if "size" in shown:
            shown["size"] = format_size(shown["size"])
        self.status_label.setText(tr(key, **shown))

    def _fill_table(self) -> None:
        inventory = self.state.inventory
        self.table.setRowCount(0)
        self.ignored_label.setText("")
        if inventory is None:
            return
        rows = [(tr(f"kind.{kind.value}"), len(entries), sum(e.size for e in entries))
                for kind, entries in sorted(inventory.by_kind().items(), key=lambda kv: _KINDS.index(kv[0]))]
        rows.append((tr("cli.total"), inventory.count(), inventory.total_bytes()))
        for label, count, size in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, text in enumerate((label, str(count), format_size(size))):
                self.table.setItem(row, column, QTableWidgetItem(text))
        if inventory.ignored:
            details = ", ".join(f"{n} ({tr('reason.' + reason)})" for reason, n in sorted(inventory.ignored.items()))
            self.ignored_label.setText(tr("gui.source.ignored", details=details))

    # -- langue --------------------------------------------------------------------------------

    def retranslate(self) -> None:
        self.intro_label.setText(tr("gui.source.intro"))
        self.direction_label.setText(tr("gui.source.direction"))
        self.direction_combo.setItemText(0, tr("gui.source.encode"))
        self.direction_combo.setItemText(1, tr("gui.source.decode"))
        self.roots_group.setTitle(tr("gui.source.roots"))
        self.add_folder_button.setText(tr("gui.source.add_folder"))
        self.add_files_button.setText(tr("gui.source.add_files"))
        self.remove_button.setText(tr("gui.source.remove"))
        self.kinds_group.setTitle(tr("gui.source.kinds"))
        for kind, box in self.kind_boxes.items():
            box.setText(tr(f"kind.{kind.value}"))
        self.open_zips_box.setText(tr("gui.source.open_zips"))
        self.exclude_label.setText(tr("gui.source.exclude"))
        self.scan_button.setText(tr("gui.source.scan"))
        self.result_group.setTitle(tr("gui.source.result"))
        self.table.setHorizontalHeaderLabels([tr("cli.col.kind"), tr("cli.col.files"), tr("cli.col.size")])
        self._set_status(self._status[0], **self._status[1])
        self._fill_table()
