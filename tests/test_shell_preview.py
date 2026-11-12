import numpy as np
import pytest
import DracoPy
from dracoconv.shell_preview import prepare_mesh, project, render_image


def encoded():
    return DracoPy.encode(np.array([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]), np.array([[0,1,2],[0,2,3]], dtype=np.uint32))


def test_invalid_and_point_cloud():
    with pytest.raises(ValueError): prepare_mesh(b'invalid')
    with pytest.raises(ValueError, match='point'): prepare_mesh(DracoPy.encode(np.array([[0.,0.,0.],[1.,1.,1.]])))


def test_projection_does_not_mutate_and_face_cap():
    tris, reduced = prepare_mesh(encoded(), 1)
    assert tris.shape == (1,3,3) and reduced
    original = tris.copy()
    moved = project(tris, 30, 20, 1.5)
    assert np.array_equal(original, tris)
    assert not np.array_equal(moved, tris)


def test_thumbnail_has_geometry(qapp, tmp_path):
    tris, _ = prepare_mesh(encoded())
    image = render_image(tris, 128)
    assert image.width() == image.height() == 128
    assert image.save(str(tmp_path / 'thumb.png'))
    assert len({image.pixel(x,y) for x in range(128) for y in range(128)}) > 2
