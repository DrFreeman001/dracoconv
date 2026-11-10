"""Maillage en mémoire, commun à tous les formats et à tous les moteurs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


class MeshReadError(Exception):
    """Fichier illisible ou géométrie inutilisable ; ``reason`` est un code de raison."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _lex_less(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a < b dans l'ordre lexicographique (x, y, z), ligne par ligne."""
    return (a[:, 0] < b[:, 0]) | (
        (a[:, 0] == b[:, 0]) & ((a[:, 1] < b[:, 1]) | ((a[:, 1] == b[:, 1]) & (a[:, 2] < b[:, 2])))
    )


@dataclass
class Mesh:
    positions: np.ndarray  # float32, N×3
    faces: np.ndarray  # uint32, M×3 ; vide pour un nuage de points
    normals: np.ndarray | None = None
    texcoords: np.ndarray | None = None
    colors: np.ndarray | None = None
    source_path: Path | None = None
    source_kind: str | None = None
    source_size: int | None = None

    def __post_init__(self) -> None:
        self.positions = np.ascontiguousarray(self.positions, dtype=np.float32).reshape(-1, 3)
        self.faces = np.ascontiguousarray(self.faces, dtype=np.uint32).reshape(-1, 3)

    def triangle_count(self) -> int:
        return int(len(self.faces))

    def max_extent(self) -> float:
        if len(self.positions) == 0:
            return 0.0
        return float((self.positions.max(axis=0) - self.positions.min(axis=0)).max())

    def validate(self) -> None:
        if len(self.positions) == 0:
            raise MeshReadError("empty")
        if not np.isfinite(self.positions).all():
            raise MeshReadError("invalid_coordinates")
        if len(self.faces) and int(self.faces.max()) >= len(self.positions):
            raise MeshReadError("unreadable", "indice de face hors limites")

    def canonical_triangles(self) -> tuple[np.ndarray, int]:
        """Triangles sous forme canonique (K×3×3) et nombre de dégénérés écartés.

        Deux maillages de même géométrie donnent le même tableau, quel que soit
        l'ordre des sommets, des triangles, ou le sommet de départ de chaque triangle.
        """
        tris = self.positions[self.faces] + np.float32(0.0)  # -0.0 devient 0.0
        v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
        degenerate = (v0 == v1).all(axis=1) | (v1 == v2).all(axis=1) | (v0 == v2).all(axis=1)
        dropped = int(degenerate.sum())
        tris = tris[~degenerate]
        if len(tris) == 0:
            return tris.reshape(0, 3, 3), dropped
        v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
        first = np.zeros(len(tris), dtype=np.intp)
        smallest = v0.copy()
        better = _lex_less(v1, smallest)
        first[better] = 1
        smallest[better] = v1[better]
        better = _lex_less(v2, smallest)
        first[better] = 2
        order = (first[:, None] + np.arange(3)[None, :]) % 3
        tris = np.take_along_axis(tris, order[:, :, None], axis=1)
        flat = tris.reshape(-1, 9)
        tris = tris[np.lexsort(flat.T[::-1])]
        return np.ascontiguousarray(tris), dropped
