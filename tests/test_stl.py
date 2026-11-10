import numpy as np
import pytest

from conftest import same_geometry, write_ascii_stl, write_binary_stl
from dracoconv.io.stl import read_stl, write_stl
from dracoconv.mesh import Mesh, MeshReadError


def test_reads_binary(tmp_path, sphere):
    p = tmp_path / "s.stl"
    write_binary_stl(p, sphere)
    assert same_geometry(read_stl(p), sphere)


def test_reads_ascii(tmp_path, cube):
    p = tmp_path / "c.stl"
    write_ascii_stl(p, cube)
    assert same_geometry(read_stl(p), cube)


def test_reads_binary_with_solid_header(tmp_path, cube):
    p = tmp_path / "c.stl"
    write_binary_stl(p, cube, header=b"solid exported by CAD")
    assert same_geometry(read_stl(p), cube)


def test_merges_identical_vertices(tmp_path, cube):
    p = tmp_path / "c.stl"
    write_binary_stl(p, cube)
    m = read_stl(p)
    assert len(m.positions) == 8 and len(m.faces) == 12


def test_records_provenance(tmp_path, cube):
    p = tmp_path / "c.stl"
    write_binary_stl(p, cube)
    m = read_stl(p)
    assert m.source_path == p and m.source_kind == "stl" and m.source_size == p.stat().st_size


def test_roundtrip_write_read(tmp_path, sphere):
    p = tmp_path / "o.stl"
    write_stl(sphere, p)
    assert p.stat().st_size == 84 + 50 * sphere.triangle_count()
    assert same_geometry(read_stl(p), sphere)


def test_written_normals_are_unit_and_outward(tmp_path, cube):
    p = tmp_path / "o.stl"
    write_stl(cube, p)
    raw = np.frombuffer(p.read_bytes()[84:], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    assert np.allclose(np.linalg.norm(raw["n"], axis=1), 1.0)
    centers = raw["v"].mean(axis=1) - 10.0
    assert (np.einsum("ij,ij->i", raw["n"], centers) > 0).all()


@pytest.mark.parametrize(
    "content,reason",
    [(b"", "empty"), (b"\0" * 84, "empty"), (b"\0" * 80 + b"\x05\0\0\0" + b"\0" * 10, "unreadable")],
)
def test_rejects_bad_files(tmp_path, content, reason):
    p = tmp_path / "b.stl"
    p.write_bytes(content)
    with pytest.raises(MeshReadError) as e:
        read_stl(p)
    assert e.value.reason == reason


def test_rejects_nan(tmp_path, cube):
    bad = Mesh(cube.positions.copy(), cube.faces)
    bad.positions[0, 0] = np.inf
    p = tmp_path / "n.stl"
    write_binary_stl(p, bad)
    with pytest.raises(MeshReadError) as e:
        read_stl(p)
    assert e.value.reason == "invalid_coordinates"
