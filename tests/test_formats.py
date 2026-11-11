import pytest

from conftest import make_colored_ply, make_textured_obj, make_two_cube_3mf, same_geometry, stl_bytes
from dracoconv.io import LOSSY_KINDS, load_mesh, load_mesh_from_bytes, save_mesh
from dracoconv.io.sniff import FileKind
from dracoconv.mesh import MeshReadError


@pytest.mark.parametrize("fmt", ["stl", "obj", "ply"])
def test_save_load_roundtrip(tmp_path, sphere, fmt):
    p = tmp_path / f"m.{fmt}"
    save_mesh(sphere, p, fmt)
    assert same_geometry(load_mesh(p), sphere)


def test_obj_keeps_uv_and_normals(tmp_path):
    m = load_mesh(make_textured_obj(tmp_path))
    assert m.texcoords is not None and m.normals is not None
    assert m.triangle_count() == 1


def test_ply_keeps_colors(tmp_path):
    m = load_mesh(make_colored_ply(tmp_path))
    assert m.colors is not None and m.colors.shape[1] in (3, 4)


def test_ply_roundtrip_keeps_colors(tmp_path):
    m = load_mesh(make_colored_ply(tmp_path))
    save_mesh(m, tmp_path / "out.ply", "ply")
    assert load_mesh(tmp_path / "out.ply").colors is not None


def test_3mf_merges_objects(tmp_path, cube):
    m = load_mesh(make_two_cube_3mf(tmp_path, cube))
    assert m.triangle_count() == 24 and m.max_extent() == pytest.approx(120.0)
    assert m.source_kind == "3mf"


def test_3mf_is_lossy_kind():
    assert LOSSY_KINDS == {FileKind.THREEMF}


def test_load_from_bytes(sphere):
    assert same_geometry(load_mesh_from_bytes("dir/s.stl", stl_bytes(sphere)), sphere)


def test_compiler_obj_refused(tmp_path):
    p = tmp_path / "a.obj"
    p.write_bytes(b"\x64\x86\x02\x00" + b"\0" * 60)
    with pytest.raises(MeshReadError) as e:
        load_mesh(p)
    assert e.value.reason == "compiler_obj"


def test_garbage_obj_is_unreadable(tmp_path):
    p = tmp_path / "a.obj"
    p.write_text("hello world\n")
    with pytest.raises(MeshReadError) as e:
        load_mesh(p)
    assert e.value.reason in ("unreadable", "empty")
