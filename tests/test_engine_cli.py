from dataclasses import replace

import pytest

from conftest import make_colored_ply, make_quad_cube_obj, make_textured_obj, same_geometry
from dracoconv.engine import select_engine
from dracoconv.engine.base import EngineError
from dracoconv.engine.cli import CliEngine, find_binaries
from dracoconv.engine.dracopy import DracoPyEngine
from dracoconv.io import load_mesh
from dracoconv.quality import error_bound_mm, measure
from dracoconv.settings import EncodeSettings


@pytest.fixture(scope="module")
def ref():
    binaries = find_binaries()
    if not binaries:
        pytest.skip("moteur de référence absent : lancer tools/build_draco.ps1")
    return CliEngine(*binaries)


def test_lossless_roundtrip_is_exact(ref, sphere):
    assert same_geometry(ref.decode(ref.encode(sphere, EncodeSettings())), sphere)


def test_supports_whole_cli_surface(ref):
    assert ref.supports == {"compression_level", "position_bits", "texcoord_bits", "normal_bits", "generic_bits",
                            "skip_attributes", "point_cloud", "metadata", "preserve_polygons"}
    assert ref.max_position_bits == 30


def test_thirty_bits(ref, sphere):
    out = ref.decode(ref.encode(sphere, replace(EncodeSettings(), position_bits=30)))
    assert measure(sphere, out).max_error_mm <= error_bound_mm(sphere, 30)


def test_cross_decoding(ref, sphere):
    builtin = DracoPyEngine()
    s = replace(EncodeSettings(), position_bits=14)
    bound = error_bound_mm(sphere, 14)
    assert measure(sphere, ref.decode(builtin.encode(sphere, s))).max_error_mm <= bound
    assert measure(sphere, builtin.decode(ref.encode(sphere, s))).max_error_mm <= bound


def test_cross_decoding_lossless(ref, sphere):
    builtin = DracoPyEngine()
    assert same_geometry(ref.decode(builtin.encode(sphere, EncodeSettings())), sphere)
    assert same_geometry(builtin.decode(ref.encode(sphere, EncodeSettings())), sphere)


def test_point_cloud(ref, sphere):
    out = ref.decode(ref.encode(sphere, replace(EncodeSettings(), point_cloud=True)))
    assert out.triangle_count() == 0 and len(out.positions) == len(sphere.positions)


def test_colors_survive(ref, tmp_path):
    mesh = load_mesh(make_colored_ply(tmp_path))
    assert ref.decode(ref.encode(mesh, EncodeSettings())).colors is not None


def test_texcoords_survive(ref, tmp_path):
    mesh = load_mesh(make_textured_obj(tmp_path))
    assert DracoPyEngine().decode(ref.encode(mesh, EncodeSettings())).texcoords is not None


def test_preserve_polygons_from_source(ref, tmp_path):
    src = make_quad_cube_obj(tmp_path)
    plain = ref.encode_source(src, EncodeSettings())
    kept = ref.encode_source(src, replace(EncodeSettings(), preserve_polygons=True))
    assert ref.decode(kept).triangle_count() == 12
    assert len(kept) > len(plain)


def test_metadata_from_source(ref, tmp_path):
    src = tmp_path / "named.obj"
    src.write_text("o piece_principale\nusemtl rouge\nv 0 0 0\nv 10 0 0\nv 0 10 0\nf 1 2 3\n", encoding="ascii")
    plain = ref.encode_source(src, EncodeSettings())
    with_names = ref.encode_source(src, replace(EncodeSettings(), metadata=True))
    assert len(with_names) > len(plain) and b"rouge" in with_names


def test_source_with_accents_in_path(ref, tmp_path):
    folder = tmp_path / "modèles éàü"
    folder.mkdir()
    src = make_quad_cube_obj(folder)
    assert ref.decode(ref.encode_source(src, EncodeSettings())).triangle_count() == 12


def test_preserve_order_is_not_supported(ref, sphere):
    with pytest.raises(EngineError):
        ref.encode(sphere, replace(EncodeSettings(), preserve_order=True))


def test_garbage_raises(ref):
    with pytest.raises(EngineError):
        ref.decode(b"not draco")


def test_select_default_is_builtin():
    assert select_engine(EncodeSettings()).name == "dracopy"


@pytest.mark.parametrize(
    "change", [dict(preserve_polygons=True), dict(metadata=True), dict(generic_bits=12), dict(position_bits=30)]
)
def test_select_falls_back_to_reference(change):
    assert select_engine(replace(EncodeSettings(), **change)).name == "reference"


def test_select_resolves_tolerance_with_extent():
    tight = replace(EncodeSettings(), tolerance_mm=1e-6)
    assert select_engine(tight, max_extent=1000.0).name == "reference"  # 30 bits nécessaires
    assert select_engine(replace(EncodeSettings(), tolerance_mm=0.01), max_extent=100.0).name == "dracopy"


def test_select_honours_preference():
    assert select_engine(replace(EncodeSettings(), position_bits=14), prefer="reference").name == "reference"
    assert select_engine(EncodeSettings(), prefer="dracopy").name == "dracopy"


def test_select_refuses_impossible_combination():
    with pytest.raises(EngineError) as e:
        select_engine(replace(EncodeSettings(), preserve_order=True, preserve_polygons=True))
    assert e.value.reason == "engine_unavailable"
    with pytest.raises(EngineError):
        select_engine(replace(EncodeSettings(), preserve_polygons=True), prefer="dracopy")


def test_select_without_binaries(monkeypatch):
    monkeypatch.setattr("dracoconv.engine.find_binaries", lambda: None)
    assert select_engine(EncodeSettings()).name == "dracopy"
    with pytest.raises(EngineError) as e:
        select_engine(replace(EncodeSettings(), preserve_polygons=True))
    assert e.value.reason == "engine_unavailable"
