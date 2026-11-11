"""Archives ZIP : inventaire sans extraction et réécriture entrée par entrée."""
from __future__ import annotations

import zipfile
from pathlib import Path

from .paths import long_path
from .sniff import MODEL_KINDS, FileKind, kind_from_name

_LISTED = MODEL_KINDS | {FileKind.DRC}


def list_models(zip_path: Path) -> list[tuple[str, FileKind, int, int]]:
    """Modèles et fichiers .drc d'une archive : nom, type, taille décompressée, taille compressée.

    Lève ``zipfile.BadZipFile`` ou ``OSError`` si l'archive est illisible.
    """
    found = []
    with zipfile.ZipFile(long_path(zip_path)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            kind = kind_from_name(info.filename)
            if kind in _LISTED:
                found.append((info.filename, kind, info.file_size, info.compress_size))
    return found
