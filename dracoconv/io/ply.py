"""PLY : lecture par trimesh, écriture binaire petit-boutiste."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ..mesh import Mesh
from ._trimesh import load_with_trimesh
from .paths import long_path

_HAS_NX = re.compile(rb"^property\s+\S+\s+nx\s*$", re.MULTILINE)


def ply_from_bytes(data: bytes) -> Mesh:
    end = data.find(b"end_header", 0, 65536)
    header = data[: end + 10] if end >= 0 else data[:65536]
    mesh = load_with_trimesh(data, "ply", has_normals=bool(_HAS_NX.search(header)))
    mesh.source_kind, mesh.source_size = "ply", len(data)
    return mesh


def read_ply(path: Path) -> Mesh:
    with open(long_path(path), "rb") as f:
        mesh = ply_from_bytes(f.read())
    mesh.source_path = Path(path)
    return mesh


def ply_to_bytes(mesh: Mesh) -> bytes:
    count = len(mesh.positions)
    fields = [("x", "<f4"), ("y", "<f4"), ("z", "<f4")]
    props = ["property float x", "property float y", "property float z"]
    if mesh.normals is not None:
        fields += [("nx", "<f4"), ("ny", "<f4"), ("nz", "<f4")]
        props += ["property float nx", "property float ny", "property float nz"]
    if mesh.texcoords is not None:
        fields += [("s", "<f4"), ("t", "<f4")]
        props += ["property float s", "property float t"]
    channels = ("red", "green", "blue", "alpha")[: mesh.colors.shape[1]] if mesh.colors is not None else ()
    for name in channels:
        fields.append((name, "u1"))
        props.append(f"property uchar {name}")
    vertices = np.zeros(count, dtype=np.dtype(fields))
    vertices["x"], vertices["y"], vertices["z"] = mesh.positions.T
    if mesh.normals is not None:
        vertices["nx"], vertices["ny"], vertices["nz"] = mesh.normals.T
    if mesh.texcoords is not None:
        vertices["s"], vertices["t"] = mesh.texcoords.T
    for i, name in enumerate(channels):
        vertices[name] = mesh.colors[:, i]
    faces = np.zeros(len(mesh.faces), dtype=np.dtype([("n", "u1"), ("v", "<i4", 3)]))
    faces["n"] = 3
    faces["v"] = mesh.faces
    header = ["ply", "format binary_little_endian 1.0", "comment dracoconv", f"element vertex {count}", *props,
              f"element face {len(faces)}", "property list uchar int vertex_indices", "end_header"]
    return ("\n".join(header) + "\n").encode("ascii") + vertices.tobytes() + faces.tobytes()


def write_ply(mesh: Mesh, path: Path) -> None:
    with open(long_path(path), "wb") as f:
        f.write(ply_to_bytes(mesh))
