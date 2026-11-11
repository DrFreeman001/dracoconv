from dataclasses import replace

import numpy as np
import pytest

from dracoconv.engine.dracopy import DracoPyEngine
from dracoconv.mesh import Mesh
from dracoconv.quality import (
    REFERENCE_MARKS_MM, bits_for_tolerance, curve, error_bound_mm, float_floor_mm, measure,
    quantization_step_mm, theoretical_error_mm,
)
from dracoconv.settings import EncodeSettings


def test_theoretical_error():
    assert theoretical_error_mm(180.0, 14) == pytest.approx(180 / 16383 * 3**0.5 / 2)
    assert theoretical_error_mm(180.0, 0) == 0.0
    assert quantization_step_mm(180.0, 14) == pytest.approx(0.010987, abs=1e-6)


def test_bits_for_tolerance():
    assert bits_for_tolerance(100.0, 0.01) == 14
    assert theoretical_error_mm(100.0, 14) <= 0.01 < theoretical_error_mm(100.0, 13)
    assert bits_for_tolerance(100.0, 1e-12) == 0


def test_reference_marks():
    assert REFERENCE_MARKS_MM == {"layer_height": 0.2, "nozzle": 0.4, "cad_tolerance": 0.01}


def test_float_floor_grows_with_coordinates(sphere):
    far = Mesh(sphere.positions + np.float32(10_000), sphere.faces)
    assert 0 < float_floor_mm(sphere) < float_floor_mm(far)
    assert error_bound_mm(sphere, 14) == pytest.approx(theoretical_error_mm(100.0, 14) + float_floor_mm(sphere))
    assert error_bound_mm(sphere, 0) == 0.0


def test_measure_identical(sphere):
    r = measure(sphere, sphere)
    assert r.identical and r.max_error_mm == 0 and r.rms_error_mm == 0
    assert r.volume_change_pct == pytest.approx(0) and r.watertight_before and r.watertight_after
    assert r.triangles_before == r.triangles_after == sphere.triangle_count() and r.degenerate_created == 0


def test_measure_shift(cube):
    moved = Mesh(cube.positions + np.float32([0.5, 0, 0]), cube.faces)
    r = measure(cube, moved)
    assert r.max_error_mm == pytest.approx(0.5, abs=1e-5) and r.rms_error_mm == pytest.approx(0.5, abs=1e-5)
    assert not r.identical


def test_measure_volume_change(cube):
    bigger = Mesh(cube.positions * np.float32(1.1), cube.faces)
    assert measure(cube, bigger).volume_change_pct == pytest.approx(33.1, abs=0.01)


def test_measure_open_mesh_has_no_volume(cube):
    opened = Mesh(cube.positions, cube.faces[:-1])
    r = measure(opened, opened)
    assert r.watertight_before is False and r.volume_change_pct is None


def test_measure_without_integrity_skips_volume(sphere):
    r = measure(sphere, sphere, integrity=False)
    assert r.identical and r.watertight_before is None and r.volume_change_pct is None


def test_measure_detects_collapse(dense):
    engine = DracoPyEngine()
    out = engine.decode(engine.encode(dense, replace(EncodeSettings(), position_bits=4)))
    r = measure(dense, out)
    assert r.degenerate_created > 0 and r.triangles_after < r.triangles_before and not r.identical


def test_curve_monotonic(sphere):
    pts = curve(sphere, DracoPyEngine(), EncodeSettings(), bits=[8, 12, 16, 20])
    assert [p.bits for p in pts] == [8, 12, 16, 20]
    assert all(a.theoretical_error_mm > b.theoretical_error_mm for a, b in zip(pts, pts[1:]))
    assert all(a.size_bytes < b.size_bytes for a, b in zip(pts, pts[1:]))
    assert all(p.max_error_mm <= error_bound_mm(sphere, p.bits) for p in pts)
