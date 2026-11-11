"""OBJ Wavefront."""
from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np

from ..mesh import Mesh
from ._trimesh import load_with_trimesh
from .paths import long_path

_HAS_VN = re.compile(rb"^vn\s", re.MULTILINE)


def obj_from_bytes(data: bytes) -> Mesh:
    mesh = load_with_trimesh(data, "obj", has_normals=bool(_HAS_VN.search(data)))
    mesh.source_kind, mesh.source_size = "obj", len(data)
    return mesh


def read_obj(path: Path) -> Mesh:
    with open(long_path(path), "rb") as f:
        mesh = obj_from_bytes(f.read())
    mesh.source_path = Path(path)
    return mesh


def obj_to_bytes(mesh: Mesh) -> bytes:
    out = io.BytesIO()
    out.write(b"# dracoconv\n")
    np.savetxt(out, mesh.positions, fmt="v %.9g %.9g %.9g")
    if mesh.texcoords is not None:
        np.savetxt(out, mesh.texcoords, fmt="vt %.9g %.9g")
    if mesh.normals is not None:
        np.savetxt(out, mesh.normals, fmt="vn %.9g %.9g %.9g")
    if len(mesh.faces):
        f = mesh.faces.astype(np.int64) + 1
        if mesh.texcoords is not None and mesh.normals is not None:
            np.savetxt(out, np.repeat(f, 3, axis=1), fmt="f %d/%d/%d %d/%d/%d %d/%d/%d")
        elif mesh.texcoords is not None:
            np.savetxt(out, np.repeat(f, 2, axis=1), fmt="f %d/%d %d/%d %d/%d")
        elif mesh.normals is not None:
            np.savetxt(out, np.repeat(f, 2, axis=1), fmt="f %d//%d %d//%d %d//%d")
        else:
            np.savetxt(out, f, fmt="f %d %d %d")
    return out.getvalue()


def write_obj(mesh: Mesh, path: Path) -> None:
    with open(long_path(path), "wb") as f:
        f.write(obj_to_bytes(mesh))
