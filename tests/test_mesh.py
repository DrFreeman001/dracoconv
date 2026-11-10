import numpy as np
import pytest

from dracoconv.mesh import Mesh, MeshReadError


def test_max_extent(cube):
    assert cube.max_extent() == pytest.approx(20.0)


def test_triangle_count(cube):
    assert cube.triangle_count() == 12


def test_canonical_ignores_order_and_rotation(cube):
    shuffled = Mesh(cube.positions[::-1].copy(), (7 - cube.faces)[::-1][:, [1, 2, 0]].astype(np.uint32))
    a, _ = cube.canonical_triangles()
    b, _ = shuffled.canonical_triangles()
    assert np.array_equal(a, b)


def test_canonical_keeps_winding(cube):
    flipped = Mesh(cube.positions, cube.faces[:, ::-1].copy())
    assert not np.array_equal(cube.canonical_triangles()[0], flipped.canonical_triangles()[0])


def test_canonical_drops_degenerate(cube):
    faces = np.vstack([cube.faces, [[0, 0, 1]]]).astype(np.uint32)
    tris, dropped = Mesh(cube.positions, faces).canonical_triangles()
    assert len(tris) == 12 and dropped == 1


def test_canonical_treats_negative_zero_as_zero(cube):
    neg = cube.positions.copy()
    neg[neg == 0] = -0.0
    assert np.array_equal(cube.canonical_triangles()[0], Mesh(neg, cube.faces).canonical_triangles()[0])


def test_validate_rejects_nan_and_empty(cube):
    bad = cube.positions.copy()
    bad[0, 0] = np.nan
    with pytest.raises(MeshReadError) as e:
        Mesh(bad, cube.faces).validate()
    assert e.value.reason == "invalid_coordinates"
    with pytest.raises(MeshReadError) as e:
        Mesh(np.zeros((0, 3), np.float32), np.zeros((0, 3), np.uint32)).validate()
    assert e.value.reason == "empty"
