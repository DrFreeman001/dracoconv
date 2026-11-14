"""Fixtures et aides de test, écrites indépendamment du code testé."""
import os
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["DRACOCONV_NO_UPDATE_CHECK"] = "1"  # aucun accès réseau pendant les tests
sys.path.insert(0, str(Path(__file__).parent))

from dracoconv.mesh import Mesh  # noqa: E402

_CUBE_V = np.array(
    [[0, 0, 0], [20, 0, 0], [20, 20, 0], [0, 20, 0], [0, 0, 20], [20, 0, 20], [20, 20, 20], [0, 20, 20]],
    dtype=np.float32,
)
_CUBE_F = np.array(
    [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
     [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]],
    dtype=np.uint32,
)


def make_cube() -> Mesh:
    return Mesh(_CUBE_V.copy(), _CUBE_F.copy())


def make_sphere(subdivisions: int, radius: float = 50.0) -> Mesh:
    import trimesh

    s = trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)
    return Mesh(np.asarray(s.vertices, dtype=np.float32), np.asarray(s.faces, dtype=np.uint32))


CUBE = make_cube()


@pytest.fixture
def cube() -> Mesh:
    return make_cube()


@pytest.fixture(scope="session")
def _sphere4() -> Mesh:
    return make_sphere(4)


@pytest.fixture(scope="session")
def _sphere6() -> Mesh:
    return make_sphere(6)


@pytest.fixture
def sphere(_sphere4) -> Mesh:
    return Mesh(_sphere4.positions.copy(), _sphere4.faces.copy())


@pytest.fixture
def dense(_sphere6) -> Mesh:
    return Mesh(_sphere6.positions.copy(), _sphere6.faces.copy())


def stl_bytes(mesh: Mesh, header: bytes = b"") -> bytes:
    tris = mesh.positions[mesh.faces].astype("<f4")
    out = bytearray(header.ljust(80, b"\0")[:80])
    out += struct.pack("<I", len(tris))
    for t in tris:
        out += b"\0" * 12 + t.tobytes() + b"\0\0"
    return bytes(out)


def write_binary_stl(path, mesh: Mesh, header: bytes = b"") -> None:
    with open(path, "wb") as f:
        f.write(stl_bytes(mesh, header))


def write_ascii_stl(path, mesh: Mesh) -> None:
    lines = ["solid test"]
    for t in mesh.positions[mesh.faces]:
        lines.append(" facet normal 0 0 0\n  outer loop")
        for v in t:
            lines.append(f"   vertex {float(v[0])!r} {float(v[1])!r} {float(v[2])!r}")
        lines.append("  endloop\n endfacet")
    lines.append("endsolid test")
    Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")


def same_geometry(a: Mesh, b: Mesh) -> bool:
    ta, _ = a.canonical_triangles()
    tb, _ = b.canonical_triangles()
    return ta.shape == tb.shape and bool(np.array_equal(ta, tb))


def make_textured_obj(tmp_path) -> Path:
    p = Path(tmp_path) / "tex.obj"
    p.write_text(
        "# triangle avec texture\nv 0 0 0\nv 10 0 0\nv 0 10 0\nvt 0 0\nvt 1 0\nvt 0 1\nvn 0 0 1\n"
        "f 1/1/1 2/2/1 3/3/1\n",
        encoding="ascii",
    )
    return p


def make_quad_cube_obj(tmp_path) -> Path:
    p = Path(tmp_path) / "quads.obj"
    lines = [f"v {x} {y} {z}" for x, y, z in _CUBE_V.astype(int)]
    lines += ["f 1 4 3 2", "f 5 6 7 8", "f 1 2 6 5", "f 2 3 7 6", "f 3 4 8 7", "f 4 1 5 8"]
    p.write_text("\n".join(lines) + "\n", encoding="ascii")
    return p


def make_colored_ply(tmp_path) -> Path:
    p = Path(tmp_path) / "col.ply"
    p.write_text(
        "ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nelement face 1\n"
        "property list uchar int vertex_indices\nend_header\n"
        "0 0 0 255 0 0\n10 0 0 0 255 0\n0 10 0 0 0 255\n3 0 1 2\n",
        encoding="ascii",
    )
    return p


def make_two_cube_3mf(tmp_path, cube: Mesh) -> Path:
    import trimesh

    scene = trimesh.Scene()
    scene.add_geometry(trimesh.Trimesh(cube.positions, cube.faces, process=False), node_name="a")
    scene.add_geometry(
        trimesh.Trimesh(cube.positions, cube.faces, process=False),
        node_name="b",
        transform=trimesh.transformations.translation_matrix([100, 0, 0]),
    )
    p = Path(tmp_path) / "two.3mf"
    p.write_bytes(scene.export(file_type="3mf"))
    return p


def obj_bytes(mesh: Mesh) -> bytes:
    lines = [f"v {float(x)!r} {float(y)!r} {float(z)!r}" for x, y, z in mesh.positions]
    lines += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in mesh.faces]
    return ("\n".join(lines) + "\n").encode("ascii")


def make_zip(path, entries: dict) -> Path:
    import zipfile

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return Path(path)


COMPILER_OBJ_BYTES = b"\x64\x86\x02\x00" + b"\0" * 60


@pytest.fixture
def model_tree(tmp_path) -> Path:
    """3 STL, 1 OBJ, 1 .obj de compilateur, 1 ZIP (2 STL + 1 txt), 1 txt."""
    root = Path(tmp_path) / "models"
    (root / "sub").mkdir(parents=True)
    small, medium = make_sphere(2, 30.0), make_sphere(3, 40.0)
    write_binary_stl(root / "a.stl", small)
    write_binary_stl(root / "sub" / "b.stl", medium)
    write_ascii_stl(root / "sub" / "c.stl", small)
    (root / "d.obj").write_bytes(obj_bytes(medium))
    (root / "build.obj").write_bytes(COMPILER_OBJ_BYTES)
    make_zip(root / "pack.zip", {"x/one.stl": stl_bytes(small), "two.stl": stl_bytes(medium), "lisezmoi.txt": b"bonjour"})
    (root / "notes.txt").write_text("rien", encoding="ascii")
    return root


def make_encrypted_zip(path) -> Path:
    """Archive dont les entrées portent le drapeau « chiffré » (bit 0), comme un ZIP protégé par mot de passe."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as z:
        z.writestr("secret.stl", stl_bytes(CUBE))
    raw = bytearray(buffer.getvalue())
    local, central = raw.find(b"PK" + bytes([3, 4])), raw.find(b"PK" + bytes([1, 2]))
    raw[local + 6] |= 1
    raw[central + 8] |= 1
    Path(path).write_bytes(bytes(raw))
    return Path(path)


@pytest.fixture(autouse=True)
def _isolated_user_folders(tmp_path, monkeypatch):
    """Réglages et journaux dans un dossier temporaire : les tests ne touchent pas à ceux de l'utilisateur."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
