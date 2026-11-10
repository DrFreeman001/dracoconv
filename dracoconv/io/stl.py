"""STL : lecture texte et binaire, écriture binaire."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ..mesh import Mesh, MeshReadError
from .paths import long_path

_FACET = np.dtype([("normal", "<f4", 3), ("vertices", "<f4", (3, 3)), ("attr", "<u2")])
_VERTEX_RE = re.compile(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)")
_HEADER = b"dracoconv".ljust(80, b"\0")


def merge_vertices(triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fusionne les sommets identiques au bit près d'une soupe de triangles (K×3×3)."""
    flat = np.ascontiguousarray(triangles, dtype="<f4").reshape(-1, 3)
    as_rows = flat.view(np.dtype((np.void, 12))).ravel()
    _, first, inverse = np.unique(as_rows, return_index=True, return_inverse=True)
    return flat[first], inverse.reshape(-1, 3).astype(np.uint32)


def _parse_ascii(data: bytes) -> np.ndarray | None:
    found = _VERTEX_RE.findall(data)
    if not found or len(found) % 3:
        return None
    try:
        values = np.array(found, dtype=np.float64)
    except ValueError:
        return None
    return values.astype(np.float32).reshape(-1, 3, 3)


def stl_from_bytes(data: bytes) -> Mesh:
    size = len(data)
    if size == 0:
        raise MeshReadError("empty")
    declared = int(np.frombuffer(data, dtype="<u4", count=1, offset=80)[0]) if size >= 84 else -1
    triangles: np.ndarray | None = None
    if declared >= 0 and size == 84 + 50 * declared:
        # Binaire : la taille du fichier concorde avec le nombre de triangles annoncé,
        # quel que soit le contenu de l'en-tête (certains commencent par « solid »).
        triangles = np.frombuffer(data, dtype=_FACET, count=declared, offset=84)["vertices"]
    else:
        triangles = _parse_ascii(data)
        if triangles is None and declared > 0 and size > 84 + 50 * declared:
            # Binaire suivi d'octets en trop : on lit les triangles annoncés.
            triangles = np.frombuffer(data, dtype=_FACET, count=declared, offset=84)["vertices"]
    if triangles is None:
        raise MeshReadError("unreadable")
    if len(triangles) == 0:
        raise MeshReadError("empty")
    positions, faces = merge_vertices(triangles)
    mesh = Mesh(positions, faces, source_kind="stl", source_size=size)
    mesh.validate()
    return mesh


def read_stl(path: Path) -> Mesh:
    path = Path(path)
    with open(long_path(path), "rb") as f:
        data = f.read()
    mesh = stl_from_bytes(data)
    mesh.source_path = path
    return mesh


def stl_to_bytes(mesh: Mesh) -> bytes:
    triangles = mesh.positions[mesh.faces].astype("<f4")
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    length = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, length, out=np.zeros_like(normals), where=length > 0)
    facets = np.zeros(len(triangles), dtype=_FACET)
    facets["normal"] = normals
    facets["vertices"] = triangles
    return _HEADER + np.uint32(len(triangles)).astype("<u4").tobytes() + facets.tobytes()


def write_stl(mesh: Mesh, path: Path) -> None:
    with open(long_path(Path(path)), "wb") as f:
        f.write(stl_to_bytes(mesh))
