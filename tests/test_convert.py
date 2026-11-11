import os
from dataclasses import replace

import numpy as np
import pytest

from conftest import (
    make_quad_cube_obj, make_two_cube_3mf, obj_bytes, same_geometry, write_ascii_stl, write_binary_stl,
)
from dracoconv import convert
from dracoconv.convert import decode_file, encode_bytes, encode_file, output_path, verify
from dracoconv.engine.dracopy import DracoPyEngine
from dracoconv.io import load_mesh, read_stl
from dracoconv.mesh import Mesh
from dracoconv.settings import EncodeSettings

LONG_PREFIX = "\\\\?\\"


def test_encode_file_lossless(tmp_path, sphere):
    src = tmp_path / "s.stl"
    write_binary_stl(src, sphere)
    r = encode_file(src, tmp_path / "s.drc", EncodeSettings())
    assert r.state == "done" and r.reason is None and r.quality.identical
    assert r.size_before == src.stat().st_size and r.size_after == (tmp_path / "s.drc").stat().st_size
    assert r.size_after < r.size_before and r.lossy_source is False
    assert not list(tmp_path.glob("*.part"))
    assert (tmp_path / "s.drc").stat().st_mtime == pytest.approx(src.stat().st_mtime, abs=2)


def test_full_roundtrip_stl(tmp_path, sphere):
    src = tmp_path / "s.stl"
    write_binary_stl(src, sphere)
    encode_file(src, tmp_path / "s.drc", EncodeSettings())
    r = decode_file(tmp_path / "s.drc", tmp_path / "back.stl", "stl")
    assert r.state == "done" and same_geometry(read_stl(tmp_path / "back.stl"), sphere)
    assert (tmp_path / "back.stl").stat().st_size == src.stat().st_size


@pytest.mark.parametrize("fmt", ["obj", "ply"])
def test_decode_to_other_formats(tmp_path, sphere, fmt):
    src = tmp_path / "s.stl"
    write_binary_stl(src, sphere)
    encode_file(src, tmp_path / "s.drc", EncodeSettings())
    assert decode_file(tmp_path / "s.drc", tmp_path / f"back.{fmt}", fmt).state == "done"
    assert same_geometry(load_mesh(tmp_path / f"back.{fmt}"), sphere)


def test_ascii_stl_and_obj_sources(tmp_path, sphere):
    write_ascii_stl(tmp_path / "a.stl", sphere)
    (tmp_path / "o.obj").write_bytes(obj_bytes(sphere))
    for name in ("a.stl", "o.obj"):
        r = encode_file(tmp_path / name, tmp_path / (name + ".drc"), EncodeSettings())
        assert r.state == "done" and r.quality.identical and r.size_after < 0.2 * r.size_before


def test_quantized_encode_reports_error(tmp_path, sphere):
    src = tmp_path / "s.stl"
    write_binary_stl(src, sphere)
    r = encode_file(src, tmp_path / "s.drc", replace(EncodeSettings(), position_bits=12))
    assert r.state == "done" and not r.quality.identical and 0 < r.quality.max_error_mm < 0.03


def test_never_overwrites(tmp_path, cube):
    src = tmp_path / "c.stl"
    write_binary_stl(src, cube)
    (tmp_path / "c.drc").write_bytes(b"keep")
    r = encode_file(src, tmp_path / "c.drc", EncodeSettings())
    assert r.state == "failed" and r.reason == "exists" and (tmp_path / "c.drc").read_bytes() == b"keep"
    (tmp_path / "c2.stl").write_bytes(b"keep")
    assert decode_file(tmp_path / "c.drc", tmp_path / "c2.stl", "stl").reason == "exists"


def test_no_gain_skipped(tmp_path, cube, monkeypatch):
    src = tmp_path / "c.stl"
    write_binary_stl(src, cube)
    real = convert.encode_bytes

    def padded(*a, **k):
        data, q = real(*a, **k)
        return data + b"\0" * 10_000, q

    monkeypatch.setattr(convert, "encode_bytes", padded)
    r = encode_file(src, tmp_path / "c.drc", EncodeSettings())
    assert (r.state, r.reason) == ("skipped", "no_gain") and not (tmp_path / "c.drc").exists()
    assert encode_file(src, tmp_path / "c.drc", EncodeSettings(), skip_if_no_gain=False).state == "done"


@pytest.mark.parametrize("content,state,reason", [(b"", "skipped", "empty"), (b"garbage" * 30, "failed", "unreadable")])
def test_bad_sources(tmp_path, content, state, reason):
    src = tmp_path / "b.stl"
    src.write_bytes(content)
    r = encode_file(src, tmp_path / "b.drc", EncodeSettings())
    assert (r.state, r.reason) == (state, reason) and not (tmp_path / "b.drc").exists() and src.exists()


def test_missing_source(tmp_path):
    r = encode_file(tmp_path / "absent.stl", tmp_path / "x.drc", EncodeSettings())
    assert (r.state, r.reason) == ("failed", "unreadable")


def test_nan_source_fails_cleanly(tmp_path, cube):
    bad = Mesh(cube.positions.copy(), cube.faces)
    bad.positions[0, 0] = np.nan
    src = tmp_path / "n.stl"
    write_binary_stl(src, bad)
    r = encode_file(src, tmp_path / "n.drc", EncodeSettings())
    assert (r.state, r.reason) == ("failed", "invalid_coordinates") and src.exists()


def test_degenerate_triangles_reported_not_fatal(tmp_path, sphere):
    m = Mesh(sphere.positions, np.vstack([sphere.faces, [[0, 0, 1]]]).astype(np.uint32))
    src = tmp_path / "d.stl"
    write_binary_stl(src, m)
    r = encode_file(src, tmp_path / "d.drc", EncodeSettings())
    assert r.state == "done" and r.quality.identical


def test_accents_and_long_path(tmp_path, sphere):
    deep = tmp_path.joinpath(*(["dossier éàü " + "x" * 40] * 6))
    os.makedirs(LONG_PREFIX + str(deep))
    src = deep / "modèle final.stl"
    write_binary_stl(LONG_PREFIX + str(src), sphere)
    assert len(str(src)) > 260
    assert encode_file(src, deep / "modèle final.drc", EncodeSettings()).state == "done"
    assert decode_file(deep / "modèle final.drc", deep / "retour.stl", "stl").state == "done"


def test_3mf_flagged_lossy(tmp_path, cube):
    r = encode_file(make_two_cube_3mf(tmp_path, cube), tmp_path / "o.drc", EncodeSettings(), skip_if_no_gain=False)
    assert r.state == "done" and r.lossy_source is True


def test_preserve_polygons_uses_source_file(tmp_path):
    src = make_quad_cube_obj(tmp_path)
    r = encode_file(src, tmp_path / "q.drc", replace(EncodeSettings(), preserve_polygons=True), skip_if_no_gain=False)
    assert r.state == "done" and r.quality.triangles_after == 12 and r.quality.max_error_mm == 0


def test_engine_failure_is_reported(tmp_path, sphere):
    src = tmp_path / "s.stl"
    write_binary_stl(src, sphere)
    impossible = replace(EncodeSettings(), preserve_order=True, preserve_polygons=True)
    r = encode_file(src, tmp_path / "s.drc", impossible)
    assert (r.state, r.reason) == ("failed", "engine_unavailable")


def test_unwritable_destination(tmp_path, sphere, monkeypatch):
    src = tmp_path / "s.stl"
    write_binary_stl(src, sphere)

    def refuse(path):
        raise PermissionError(13, "refus")

    monkeypatch.setattr(convert, "_open_part", refuse)
    r = encode_file(src, tmp_path / "s.drc", EncodeSettings())
    assert (r.state, r.reason) == ("failed", "access_denied") and src.exists()


def test_garbage_drc(tmp_path):
    (tmp_path / "g.drc").write_bytes(b"not draco")
    r = decode_file(tmp_path / "g.drc", tmp_path / "g.stl", "stl")
    assert (r.state, r.reason) == ("failed", "unreadable") and not (tmp_path / "g.stl").exists()


def test_output_path_rules(tmp_path):
    taken = set()
    assert output_path(tmp_path / "m.stl", ".drc", tmp_path, taken).name == "m.drc"
    assert output_path(tmp_path / "m.obj", ".drc", tmp_path, taken).name == "m.obj.drc"
    assert output_path(tmp_path / "m.obj", ".drc", tmp_path, taken).name == "m.obj (1).drc"
    (tmp_path / "k.stl").touch()
    assert output_path(tmp_path / "k.drc", ".stl", tmp_path, set()).name == "k (1).stl"
    assert output_path(tmp_path / "z.obj.drc", ".obj", tmp_path, set()).name == "z.obj"
    assert output_path(tmp_path / "z.obj.drc", ".ply", tmp_path, set()).name == "z.ply"
    (tmp_path / "e.drc").touch()
    assert output_path(tmp_path / "e.stl", ".drc", tmp_path, set()).name == "e.stl.drc"
    other = tmp_path / "out"
    assert output_path(tmp_path / "m.stl", ".drc", other, set()) == other / "m.drc"


def test_verify_rejects_tampered(sphere):
    other = DracoPyEngine().encode(Mesh(sphere.positions * 2, sphere.faces), EncodeSettings())
    ok, report = verify(sphere, other, EncodeSettings())
    assert ok is False and not report.identical
    assert verify(sphere, b"not draco", EncodeSettings())[0] is False


def test_verify_accepts_within_bound_only(sphere):
    quantized = replace(EncodeSettings(), position_bits=12)
    data = DracoPyEngine().encode(sphere, quantized)
    assert verify(sphere, data, quantized)[0] is True
    assert verify(sphere, data, EncodeSettings())[0] is False  # annoncé sans perte, mais quantifié
    assert verify(sphere, data, replace(EncodeSettings(), position_bits=20))[0] is False


def test_encode_bytes_returns_verified_data(sphere):
    data, report = encode_bytes(sphere, EncodeSettings())
    assert report.identical and same_geometry(DracoPyEngine().decode(data), sphere)
