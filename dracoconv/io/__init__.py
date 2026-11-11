"""Lecture et écriture des formats de modèles."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..mesh import Mesh, MeshReadError
from .obj import obj_from_bytes, obj_to_bytes, read_obj, write_obj
from .paths import long_path
from .ply import ply_from_bytes, ply_to_bytes, read_ply, write_ply
from .sniff import MODEL_KINDS, FileKind, detect_kind, detect_kind_from_bytes
from .stl import read_stl, stl_from_bytes, stl_to_bytes, write_stl
from .threemf import read_3mf, threemf_from_bytes

#: Formats dont la conversion vers Draco perd des données autres que la géométrie.
LOSSY_KINDS = {FileKind.THREEMF}

OutputFormat = Literal["stl", "obj", "ply"]

_FROM_BYTES = {
    FileKind.STL: stl_from_bytes,
    FileKind.OBJ: obj_from_bytes,
    FileKind.PLY: ply_from_bytes,
    FileKind.THREEMF: threemf_from_bytes,
}
_TO_BYTES = {"stl": stl_to_bytes, "obj": obj_to_bytes, "ply": ply_to_bytes}


def mesh_from_bytes(kind: FileKind, data: bytes) -> Mesh:
    if kind is FileKind.COMPILER_OBJ:
        raise MeshReadError("compiler_obj")
    reader = _FROM_BYTES.get(kind)
    if reader is None:
        raise MeshReadError("unsupported", kind.value)
    if len(data) == 0:
        raise MeshReadError("empty")
    return reader(data)


def load_mesh_from_bytes(name: str, data: bytes) -> Mesh:
    return mesh_from_bytes(detect_kind_from_bytes(name, data[:96]), data)


def load_mesh(path: Path, kind: FileKind | None = None) -> Mesh:
    path = Path(path)
    kind = kind or detect_kind(path)
    with open(long_path(path), "rb") as f:
        data = f.read()
    mesh = mesh_from_bytes(kind, data)
    mesh.source_path = path
    return mesh


def mesh_to_bytes(mesh: Mesh, fmt: OutputFormat) -> bytes:
    return _TO_BYTES[fmt](mesh)


def save_mesh(mesh: Mesh, path: Path, fmt: OutputFormat) -> None:
    with open(long_path(path), "wb") as f:
        f.write(mesh_to_bytes(mesh, fmt))


__all__ = [
    "LOSSY_KINDS", "MODEL_KINDS", "FileKind", "Mesh", "MeshReadError", "detect_kind", "detect_kind_from_bytes",
    "load_mesh", "load_mesh_from_bytes", "mesh_from_bytes", "mesh_to_bytes", "save_mesh",
    "read_stl", "write_stl", "read_obj", "write_obj", "read_ply", "write_ply", "read_3mf",
]
