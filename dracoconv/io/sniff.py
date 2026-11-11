"""Reconnaissance du vrai type d'un fichier."""
from __future__ import annotations

from enum import Enum
from pathlib import Path, PurePosixPath

from .paths import long_path


class FileKind(str, Enum):
    STL = "stl"
    OBJ = "obj"
    PLY = "ply"
    THREEMF = "3mf"
    ZIP = "zip"
    DRC = "drc"
    COMPILER_OBJ = "compiler_obj"
    GCODE_3MF = "gcode_3mf"  # impression déjà tranchée (.gcode.3mf) : du G-code, pas un modèle
    UNKNOWN = "unknown"


_BY_EXTENSION = {
    ".stl": FileKind.STL,
    ".obj": FileKind.OBJ,
    ".ply": FileKind.PLY,
    ".3mf": FileKind.THREEMF,
    ".zip": FileKind.ZIP,
    ".drc": FileKind.DRC,
}

#: Types qui contiennent un modèle convertible vers Draco.
MODEL_KINDS = frozenset({FileKind.STL, FileKind.OBJ, FileKind.PLY, FileKind.THREEMF})
SNIFF_BYTES = 96


def kind_from_name(name: str) -> FileKind:
    if name.lower().endswith(".gcode.3mf"):
        return FileKind.GCODE_3MF
    return _BY_EXTENSION.get(PurePosixPath(name.replace("\\", "/")).suffix.lower(), FileKind.UNKNOWN)


def detect_kind_from_bytes(name: str, head: bytes) -> FileKind:
    kind = kind_from_name(name)
    if kind is FileKind.OBJ and any(b < 9 for b in head[:SNIFF_BYTES]):
        # Un .obj Wavefront est du texte ; un octet de contrôle trahit un fichier objet de compilateur.
        return FileKind.COMPILER_OBJ
    return kind


def detect_kind(path: Path) -> FileKind:
    kind = kind_from_name(Path(path).name)
    if kind is not FileKind.OBJ:
        return kind
    try:
        with open(long_path(path), "rb") as f:
            head = f.read(SNIFF_BYTES)
    except OSError:
        return kind
    return detect_kind_from_bytes(Path(path).name, head)
