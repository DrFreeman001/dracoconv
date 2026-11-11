"""Passage par trimesh pour les formats que le projet ne lit pas lui-même."""
from __future__ import annotations

import io

import numpy as np

from ..mesh import Mesh, MeshReadError


def load_with_trimesh(data: bytes, file_type: str, has_normals: bool) -> Mesh:
    import trimesh

    try:
        loaded = trimesh.load(io.BytesIO(data), file_type=file_type, process=False, maintain_order=True)
        if isinstance(loaded, trimesh.Scene):
            if not loaded.geometry:
                raise MeshReadError("empty")
            loaded = loaded.to_geometry()
    except MeshReadError:
        raise
    except Exception as exc:  # trimesh lève des types variés selon le format
        raise MeshReadError("unreadable", str(exc)) from exc
    vertices = getattr(loaded, "vertices", None)
    if vertices is None or len(vertices) == 0:
        raise MeshReadError("empty")
    faces = getattr(loaded, "faces", None)
    faces = np.zeros((0, 3), np.uint32) if faces is None else np.asarray(faces)
    mesh = Mesh(np.asarray(vertices, dtype=np.float32), faces.astype(np.uint32))
    count = len(mesh.positions)
    visual = getattr(loaded, "visual", None)
    uv = getattr(visual, "uv", None)
    if uv is not None and len(uv) == count:
        mesh.texcoords = np.asarray(uv, dtype=np.float32)[:, :2]
    colors = None
    if visual is not None and getattr(visual, "kind", None) == "vertex":
        colors = visual.vertex_colors
    elif visual is None:
        colors = getattr(loaded, "colors", None)  # nuage de points
    if colors is not None and len(colors) == count:
        mesh.colors = np.asarray(colors, dtype=np.uint8)
    if has_normals and len(faces):
        normals = np.asarray(loaded.vertex_normals, dtype=np.float32)
        if len(normals) == count:
            mesh.normals = normals
    mesh.validate()
    return mesh
