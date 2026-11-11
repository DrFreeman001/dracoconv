import zipfile

from conftest import make_encrypted_zip, make_sphere, make_zip, same_geometry, stl_bytes
from dracoconv.convert import decode_zip, encode_zip, zip_output_path
from dracoconv.engine.dracopy import DracoPyEngine
from dracoconv.io import load_mesh_from_bytes
from dracoconv.io.archive import rewrite_zip
from dracoconv.settings import EncodeSettings


def test_encode_zip(tmp_path, sphere):
    src = make_zip(tmp_path / "pack.zip", {"a/s.stl": stl_bytes(sphere), "lisezmoi.txt": b"hello"})
    r = encode_zip(src, tmp_path / "pack.drc.zip", EncodeSettings())
    with zipfile.ZipFile(tmp_path / "pack.drc.zip") as z:
        assert sorted(z.namelist()) == ["a/s.drc", "lisezmoi.txt"] and z.read("lisezmoi.txt") == b"hello"
        assert z.getinfo("a/s.drc").compress_type == zipfile.ZIP_STORED
        assert same_geometry(DracoPyEngine().decode(z.read("a/s.drc")), sphere)
    assert r.state == "done" and src.exists()
    assert r.size_before == src.stat().st_size and r.size_after == (tmp_path / "pack.drc.zip").stat().st_size
    assert not list(tmp_path.glob("*.part"))


def test_zip_roundtrip(tmp_path, sphere):
    src = make_zip(tmp_path / "pack.zip", {"s.stl": stl_bytes(sphere)})
    encode_zip(src, tmp_path / "pack.drc.zip", EncodeSettings())
    r = decode_zip(tmp_path / "pack.drc.zip", tmp_path / "pack.stl.zip", "stl")
    assert r.state == "done"
    with zipfile.ZipFile(tmp_path / "pack.stl.zip") as z:
        assert z.namelist() == ["s.stl"]
        assert same_geometry(load_mesh_from_bytes("s.stl", z.read("s.stl")), sphere)


def test_unsafe_and_nested_entries_skipped(tmp_path, sphere):
    inner = make_zip(tmp_path / "inner.zip", {"deep.stl": stl_bytes(sphere)}).read_bytes()
    src = make_zip(tmp_path / "p.zip", {"../evil.stl": stl_bytes(sphere), "in.zip": inner, "ok.stl": stl_bytes(sphere)})
    r = encode_zip(src, tmp_path / "out" / "p.drc.zip", EncodeSettings())
    with zipfile.ZipFile(tmp_path / "out" / "p.drc.zip") as z:
        names = z.namelist()
        assert z.read("in.zip") == inner
    assert sorted(names) == ["in.zip", "ok.drc"]
    assert r.state == "done" and not (tmp_path / "evil.drc").exists() and not (tmp_path / "evil.stl").exists()


def test_encrypted_zip_skipped(tmp_path):
    src = make_encrypted_zip(tmp_path / "e.zip")
    r = encode_zip(src, tmp_path / "e.drc.zip", EncodeSettings())
    assert (r.state, r.reason) == ("skipped", "encrypted_zip") and not (tmp_path / "e.drc.zip").exists()


def test_bad_model_inside_is_copied_as_is(tmp_path, sphere):
    src = make_zip(tmp_path / "p.zip", {"bad.stl": b"garbage" * 30, "ok.stl": stl_bytes(sphere)})
    encode_zip(src, tmp_path / "p.drc.zip", EncodeSettings())
    with zipfile.ZipFile(tmp_path / "p.drc.zip") as z:
        assert sorted(z.namelist()) == ["bad.stl", "ok.drc"] and z.read("bad.stl") == b"garbage" * 30


def test_zip_without_convertible_model_is_not_created(tmp_path):
    src = make_zip(tmp_path / "p.zip", {"bad.stl": b"garbage" * 30, "a.txt": b"x"})
    r = encode_zip(src, tmp_path / "p.drc.zip", EncodeSettings())
    assert (r.state, r.reason) == ("skipped", "no_gain") and not (tmp_path / "p.drc.zip").exists()
    assert not list(tmp_path.glob("*.part"))


def test_corrupt_zip_fails(tmp_path):
    (tmp_path / "c.zip").write_bytes(b"not a zip")
    r = encode_zip(tmp_path / "c.zip", tmp_path / "c.drc.zip", EncodeSettings())
    assert (r.state, r.reason) == ("failed", "unreadable")


def test_zip_never_overwrites(tmp_path, sphere):
    src = make_zip(tmp_path / "p.zip", {"s.stl": stl_bytes(sphere)})
    (tmp_path / "p.drc.zip").write_bytes(b"keep")
    r = encode_zip(src, tmp_path / "p.drc.zip", EncodeSettings())
    assert r.reason == "exists" and (tmp_path / "p.drc.zip").read_bytes() == b"keep"


def test_same_stem_models_do_not_collide(tmp_path, sphere):
    other = make_sphere(2, 10.0)
    src = make_zip(tmp_path / "p.zip", {"m.stl": stl_bytes(sphere), "m.obj": b"garbage", "m.ply": b"garbage"})
    encode_zip(src, tmp_path / "p.drc.zip", EncodeSettings())
    with zipfile.ZipFile(tmp_path / "p.drc.zip") as z:
        assert sorted(z.namelist()) == ["m.drc", "m.obj", "m.ply"]
    assert other.triangle_count() == 320


def test_rewrite_zip_report(tmp_path):
    src = make_zip(tmp_path / "p.zip", {"a.txt": b"aaa", "b.bin": b"bbb", "dir/": b""})
    report = rewrite_zip(src, tmp_path / "q.zip", lambda name, data: ("A.TXT", data.upper()) if name == "a.txt" else None)
    assert (report.converted, report.copied) == (1, 1) and report.skipped == {}
    with zipfile.ZipFile(tmp_path / "q.zip") as z:
        assert z.read("A.TXT") == b"AAA" and z.read("b.bin") == b"bbb"


def test_zip_output_names(tmp_path):
    assert zip_output_path(tmp_path / "pack.zip", "drc", tmp_path, set()).name == "pack.drc.zip"
    assert zip_output_path(tmp_path / "pack.drc.zip", "stl", tmp_path, set()).name == "pack.stl.zip"
    assert zip_output_path(tmp_path / "autre.zip", "ply", tmp_path, set()).name == "autre.ply.zip"
    (tmp_path / "pack.drc.zip").touch()
    assert zip_output_path(tmp_path / "pack.zip", "drc", tmp_path, set()).name == "pack (1).drc.zip"
