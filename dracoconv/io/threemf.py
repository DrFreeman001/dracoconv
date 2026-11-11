"""3MF : géométrie seule. Plateaux, réglages, couleurs et séparation des objets sont perdus."""
from __future__ import annotations

from pathlib import Path

from ..mesh import Mesh
from ._trimesh import load_with_trimesh
from .paths import long_path


def threemf_from_bytes(data: bytes) -> Mesh:
    mesh = load_with_trimesh(data, "3mf", has_normals=False)
    mesh.texcoords = mesh.colors = None
    mesh.source_kind, mesh.source_size = "3mf", len(data)
    return mesh


def read_3mf(path: Path) -> Mesh:
    with open(long_path(path), "rb") as f:
        mesh = threemf_from_bytes(f.read())
    mesh.source_path = Path(path)
    return mesh
