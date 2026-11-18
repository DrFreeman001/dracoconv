"""Fenêtre « Doublons » : recherche, liste par groupe, corbeille des fichiers cochés après confirmation."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from ..i18n import format_size, tr
from .workers import Worker

_PATH_ROLE = Qt.ItemDataRole.UserRole


def search(roots: list[Path], workers: int, on_progress=None, stop=None):
    """Recense puis compare (exécuté hors du fil de l'interface)."""
    from ..duplicates import KINDS, find_duplicates
    from ..io.sniff import FileKind
    from ..scan import ScanOptions, scan

    if on_progress is not None:
        on_progress(-1, 0)
    inventory = scan(roots, ScanOptions(kinds=frozenset(KINDS | {FileKind.ZIP}), look_inside_zips=False), stop=stop)
    return find_duplicates(inventory.entries, workers=workers, on_progress=on_progress, stop=stop)


class DuplicatesDialog(QDialog):
    def __init__(self, roots: list[Path], workers: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("gui.dupes.title"))
        self.resize(1100, 700)
        self.roots = list(roots)
        self.workers = workers
        self.report = None
        self._worker: Worker | None = None

        intro = QLabel(tr("gui.dupes.intro"))
        intro.setWordWrap(True)
        self.folders_label = QLabel()
        self.folders_label.setWordWrap(True)
        self.choose_button = QPushButton(tr("gui.dupes.choose"))
        self.start_button = QPushButton(tr("gui.dupes.start"))
        self.stop_button = QPushButton(tr("gui.dupes.stop"))
        top = QHBoxLayout()
        top.addWidget(self.folders_label, 1)
        top.addWidget(self.choose_button)
        top.addWidget(self.start_button)
        top.addWidget(self.stop_button)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([tr("gui.dupes.col.file"), tr("gui.dupes.col.size"), tr("gui.dupes.col.folder")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(lambda item, _col: self._show(item))

        self.open_button = QPushButton(tr("gui.dupes.open"))
        self.trash_button = QPushButton(tr("gui.dupes.trash"))
        self.export_button = QPushButton(tr("gui.dupes.export"))
        close = QPushButton(tr("gui.dupes.close"))
        bottom = QHBoxLayout()
        for button in (self.open_button, self.export_button):
            bottom.addWidget(button)
        bottom.addStretch(1)
        bottom.addWidget(self.trash_button)
        bottom.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(top)
        layout.addWidget(self.status_label)
        layout.addWidget(self.tree, 1)
        layout.addLayout(bottom)

        self.choose_button.clicked.connect(self._choose)
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self._stop)
        self.open_button.clicked.connect(lambda: self._show(self.tree.currentItem()))
        self.trash_button.clicked.connect(self.trash_checked)
        self.export_button.clicked.connect(self._export)
        close.clicked.connect(self.close)
        self._refresh()

    # -- recherche -------------------------------------------------------------------------------

    def _refresh(self) -> None:
        running = self._worker is not None
        self.folders_label.setText(tr("gui.dupes.folders", paths=", ".join(str(p) for p in self.roots))
                                   if self.roots else tr("gui.dupes.no_folder"))
        self.start_button.setEnabled(bool(self.roots) and not running)
        self.choose_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        has_groups = bool(self.report and self.report.groups)
        self.trash_button.setEnabled(has_groups and not running)
        self.export_button.setEnabled(has_groups and not running)
        self.open_button.setEnabled(has_groups)

    def _choose(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("gui.dupes.choose"))
        if folder:
            self.roots = [Path(folder)]
            self._refresh()

    def start(self) -> None:
        if self._worker is not None or not self.roots:
            return
        self.tree.clear()
        self.report = None
        self._worker = Worker(search, self.roots, self.workers, progress_arg="on_progress", stop_arg="stop",
                              parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()
        self._refresh()

    def _stop(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()

    def _on_progress(self, values) -> None:
        done, total = values
        self.status_label.setText(tr("gui.dupes.scanning") if done < 0 else
                                  tr("gui.dupes.reading", done=done, total=total))

    def _on_failed(self, message: str) -> None:
        self._worker = None
        self.status_label.setText(message)
        self._refresh()

    def _on_finished(self, report) -> None:
        self._worker = None
        self.report = report
        self._fill()
        self._refresh()

    def _fill(self) -> None:
        report = self.report
        self.tree.clear()
        lines = [tr("gui.dupes.summary", files=report.examined, groups=len(report.groups),
                    size=format_size(report.recoverable)) if report.groups
                 else tr("gui.dupes.none", files=report.examined)]
        if report.failed:
            lines.append(tr("gui.dupes.failed", n=len(report.failed)))
        if report.skipped_zips:
            lines.append(tr("gui.dupes.zips", n=report.skipped_zips))
        self.status_label.setText(" ".join(lines))
        for number, group in enumerate(report.groups, 1):
            kind = tr("cli.duplicates.identical" if group.identical else "cli.duplicates.same_model")
            head = QTreeWidgetItem([tr("gui.dupes.group", n=number, kind=kind, count=len(group.files),
                                       size=format_size(group.recoverable)), "", ""])
            head.setFirstColumnSpanned(True)
            for entry in group.files:
                child = QTreeWidgetItem([entry.path.name, format_size(entry.size), self._folder_text(entry.path)])
                child.setToolTip(2, str(entry.path.parent))
                child.setData(0, _PATH_ROLE, str(entry.path))
                child.setCheckState(0, Qt.CheckState.Unchecked)
                child.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                head.addChild(child)
            self.tree.addTopLevelItem(head)
            head.setExpanded(True)
            head.setFirstColumnSpanned(True)

    def _folder_text(self, path: Path) -> str:
        """Dossier du fichier vu depuis le dossier examiné (« Modèles 3D\\Figurines ») ; chemin complet sinon."""
        parent = path.parent
        for root in self.roots:
            try:
                relative = parent.relative_to(root)
            except ValueError:
                continue
            name = root.name or str(root)
            return name if str(relative) == "." else str(Path(name) / relative)
        return str(parent)

    # -- actions ---------------------------------------------------------------------------------

    def _show(self, item) -> None:
        path = item.data(0, _PATH_ROLE) if item is not None else None
        if path is None and item is not None and item.childCount():
            path = item.child(0).data(0, _PATH_ROLE)
        if path and os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    def checked(self) -> list[tuple[QTreeWidgetItem, Path]]:
        found = []
        for g in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(g)
            for c in range(head.childCount()):
                child = head.child(c)
                if child.checkState(0) == Qt.CheckState.Checked:
                    found.append((child, Path(child.data(0, _PATH_ROLE))))
        return found

    def _keeps_one_per_group(self) -> bool:
        for g in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(g)
            states = [head.child(c).checkState(0) for c in range(head.childCount())]
            if states and all(s == Qt.CheckState.Checked for s in states):
                return False
        return True

    def trash_checked(self, confirm: bool = True) -> int:
        """Envoie les fichiers cochés à la corbeille ; rend le nombre de fichiers envoyés."""
        from send2trash import send2trash

        from ..batch import recycle_bin_available

        chosen = self.checked()
        if not chosen:
            return 0
        if not self._keeps_one_per_group():
            QMessageBox.warning(self, tr("gui.dupes.title"), tr("gui.dupes.keep_one"))
            return 0
        size = sum(p.stat().st_size for _, p in chosen if p.exists())
        if confirm and QMessageBox.question(
                self, tr("gui.dupes.title"), tr("gui.dupes.confirm", n=len(chosen), size=format_size(size)),
        ) != QMessageBox.StandardButton.Yes:
            return 0
        moved, no_bin = 0, 0
        for item, path in chosen:
            if not recycle_bin_available(path):
                no_bin += 1
                continue
            try:
                send2trash(str(path))
            except OSError:
                continue
            moved += 1
            head = item.parent()
            head.removeChild(item)
            if head.childCount() < 2:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(head))
        message = tr("gui.dupes.trashed", n=moved)
        if no_bin:
            message += " " + tr("gui.dupes.no_bin", n=no_bin)
        self.status_label.setText(message)
        return moved

    def _export(self) -> None:
        from ..duplicates import write_csv

        path, _ = QFileDialog.getSaveFileName(self, tr("gui.dupes.export"), "doublons.csv", "CSV (*.csv)")
        if path and self.report is not None:
            write_csv(self.report, Path(path))

    def closeEvent(self, event) -> None:  # noqa: N802 - API Qt
        if self._worker is not None:
            self._worker.request_stop()
            self._worker.wait()
        super().closeEvent(event)
