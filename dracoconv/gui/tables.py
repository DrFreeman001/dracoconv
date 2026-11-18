"""Réglages communs des tableaux de fichiers."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget


def paths_first(table: QTableWidget, path_columns: int) -> None:
    """Les premières colonnes (chemins) prennent la place, les autres s'ajustent à leur contenu.

    Un chemin trop long est raccourci au milieu, sur une seule ligne : le nom du fichier reste lisible.
    """
    header = table.horizontalHeader()
    for column in range(table.columnCount()):
        mode = QHeaderView.ResizeMode.Stretch if column < path_columns else QHeaderView.ResizeMode.ResizeToContents
        header.setSectionResizeMode(column, mode)
    table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    table.setWordWrap(False)
