import pytest

from dracoconv.io.sniff import FileKind, detect_kind, detect_kind_from_bytes


def test_compiler_obj_detected(tmp_path):
    p = tmp_path / "a.obj"
    p.write_bytes(b"\x64\x86\x02\x00" + b"\0" * 60)
    assert detect_kind(p) is FileKind.COMPILER_OBJ


def test_wavefront_obj_detected(tmp_path):
    p = tmp_path / "a.obj"
    p.write_text("# x\nv 0 0 0\n")
    assert detect_kind(p) is FileKind.OBJ


@pytest.mark.parametrize(
    "name,kind",
    [("a.STL", FileKind.STL), ("a.3mf", FileKind.THREEMF), ("a.drc", FileKind.DRC), ("a.ply", FileKind.PLY),
     ("a.zip", FileKind.ZIP), ("a.txt", FileKind.UNKNOWN)],
)
def test_kind_by_extension(tmp_path, name, kind):
    p = tmp_path / name
    p.write_bytes(b"x")
    assert detect_kind(p) is kind


def test_kind_from_bytes():
    assert detect_kind_from_bytes("dir/m.obj", b"v 0 0 0\n") is FileKind.OBJ
    assert detect_kind_from_bytes("dir/m.obj", b"\x64\x86\0\0") is FileKind.COMPILER_OBJ
    assert detect_kind_from_bytes("M.Stl", b"") is FileKind.STL
