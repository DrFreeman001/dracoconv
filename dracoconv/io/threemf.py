"""3MF : géométrie seule. Plateaux, réglages, couleurs et séparation des objets sont perdus."""
from __future__ import annotations

from pathlib import Path

from ..mesh import Mesh, MeshReadError
from ._trimesh import load_with_trimesh
from .paths import long_path


def threemf_from_bytes(data: bytes) -> Mesh:
    try:
        mesh = load_with_trimesh(data, "3mf", has_normals=False)
    except MeshReadError as exc:
        if exc.reason in ("unreadable", "empty"):
            # Les projets Bambu Studio / OrcaSlicer rangent leurs objets d'une façon que la
            # lecture ne sait pas suivre : on les laisse tels quels plutôt que de les abîmer.
            raise MeshReadError("unsupported_3mf", str(exc)) from exc
        raise
    mesh.texcoords = mesh.colors = None
    mesh.source_kind, mesh.source_size = "3mf", len(data)
    return mesh


def read_3mf(path: Path) -> Mesh:
    with open(long_path(path), "rb") as f:
        mesh = threemf_from_bytes(f.read())
    mesh.source_path = Path(path)
    return mesh
