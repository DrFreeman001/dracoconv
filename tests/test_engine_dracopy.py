from dataclasses import replace

import numpy as np
import pytest

from conftest import make_colored_ply, make_textured_obj, same_geometry
from dracoconv.engine.base import EngineError
from dracoconv.engine.dracopy import DracoPyEngine
from dracoconv.io import load_mesh
from dracoconv.params import CATALOG
from dracoconv.quality import error_bound_mm, measure
from dracoconv.settings import EncodeSettings


@pytest.fixture
def engine():
    return DracoPyEngine()


def non_default(pid: str) -> EncodeSettings:
    spec = CATALOG[pid]
    value = {"int": 5, "float": 0.01, "bool": True, "set": frozenset({"color"})}[spec.type]
    return replace(EncodeSettings(), **{pid: value})


def test_lossless_roundtrip_is_exact(engine, sphere):
    data = engine.encode(sphere, EncodeSettings())
    assert same_geometry(engine.decode(data), sphere)


def test_compresses(engine, dense):
    assert len(engine.encode(dense, EncodeSettings())) < 0.4 * (84 + 50 * dense.triangle_count())


@pytest.mark.parametrize("bits", [8, 11, 14, 20, 26, 29])
def test_quantized_error_within_bound(engine, sphere, bits):
    out = engine.decode(engine.encode(sphere, replace(EncodeSettings(), position_bits=bits)))
    assert measure(sphere, out).max_error_mm <= error_bound_mm(sphere, bits)
    assert out.triangle_count() == sphere.triangle_count()


def test_more_bits_bigger_file(engine, dense):
    def size(b):
        return len(engine.encode(dense, replace(EncodeSettings(), position_bits=b)))

    assert size(10) < size(16) < size(24)


def test_tolerance_is_resolved_per_model(engine, sphere):
    by_tolerance = engine.encode(sphere, replace(EncodeSettings(), tolerance_mm=0.01))
    assert by_tolerance == engine.encode(sphere, replace(EncodeSettings(), position_bits=14))


def test_higher_level_is_not_bigger(engine, dense):
    def size(level):
        return len(engine.encode(dense, replace(EncodeSettings(), compression_level=level, position_bits=14)))

    assert size(10) <= size(7) < size(0)


def test_preserve_order(engine, sphere):
    out = engine.decode(engine.encode(sphere, replace(EncodeSettings(), preserve_order=True)))
    assert np.array_equal(out.positions, sphere.positions) and np.array_equal(out.faces, sphere.faces)


def test_point_cloud(engine, sphere):
    out = engine.decode(engine.encode(sphere, replace(EncodeSettings(), point_cloud=True)))
    assert out.triangle_count() == 0 and len(out.positions) == len(sphere.positions)


def test_normals_skipped_by_default_and_kept_on_request(engine, tmp_path):
    mesh = load_mesh(make_textured_obj(tmp_path))
    assert engine.decode(engine.encode(mesh, EncodeSettings())).normals is None
    kept = engine.decode(engine.encode(mesh, replace(EncodeSettings(), skip_attributes=frozenset())))
    assert kept.normals is not None and kept.texcoords is not None


def test_texcoords_kept_by_default_and_skippable(engine, tmp_path):
    mesh = load_mesh(make_textured_obj(tmp_path))
    assert engine.decode(engine.encode(mesh, EncodeSettings())).texcoords is not None
    skipped = replace(EncodeSettings(), skip_attributes=frozenset({"normal", "texcoord"}))
    assert engine.decode(engine.encode(mesh, skipped)).texcoords is None


def test_colors_kept_by_default_and_skippable(engine, tmp_path):
    mesh = load_mesh(make_colored_ply(tmp_path))
    out = engine.decode(engine.encode(mesh, EncodeSettings()))
    assert out.colors is not None and sorted(map(tuple, out.colors[:, :3].tolist())) == [(0, 0, 255), (0, 255, 0), (255, 0, 0)]
    skipped = replace(EncodeSettings(), skip_attributes=frozenset({"normal", "color"}))
    assert engine.decode(engine.encode(mesh, skipped)).colors is None


def test_declared_support(engine):
    assert engine.supports == {"compression_level", "position_bits", "texcoord_bits", "normal_bits",
                               "skip_attributes", "point_cloud", "preserve_order"}


def test_unsupported_param_raises(engine, sphere):
    unsupported = set(CATALOG) - engine.supports - {"tolerance_mm"}
    assert unsupported == {"generic_bits", "metadata", "preserve_polygons"}
    for pid in unsupported:
        assert not engine.can_encode(non_default(pid), sphere.max_extent())
        with pytest.raises(EngineError):
            engine.encode(sphere, non_default(pid))


def test_thirty_bits_is_out_of_reach(engine, sphere):
    thirty = replace(EncodeSettings(), position_bits=30)
    assert not engine.can_encode(thirty, sphere.max_extent())
    assert engine.can_encode(replace(EncodeSettings(), position_bits=29), sphere.max_extent())
    with pytest.raises(EngineError):
        engine.encode(sphere, thirty)


def test_garbage_raises(engine):
    with pytest.raises(EngineError):
        engine.decode(b"not draco")
