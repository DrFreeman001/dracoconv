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


def test_thumbnail_uses_every_face_when_opengl_works(monkeypatch):
    from dracoconv import shell_preview
    calls = {}

    class FakeRenderer:
        def __init__(self, mesh):
            calls['faces'] = len(mesh.faces)
        def __enter__(self):
            return self
        def __exit__(self, *_):
            calls['closed'] = True
        def render(self, width, height, up='y', **_):
            calls['render'] = (width, height, up)
            return 'image'

    monkeypatch.setattr(shell_preview.gpu_rendering, 'MeshRenderer', FakeRenderer)
    image, simplified = shell_preview.render_thumbnail(encoded(), 5000)
    assert image == 'image' and not simplified
    assert calls == {'faces': 2, 'render': (1024, 1024, 'z'), 'closed': True}


def test_thumbnail_falls_back_to_sampled_drawing_without_opengl(qapp, monkeypatch):
    from dracoconv import shell_preview

    def unavailable(mesh):
        raise RuntimeError('OpenGL context unavailable')

    monkeypatch.setattr(shell_preview.gpu_rendering, 'MeshRenderer', unavailable)
    image, simplified = shell_preview.render_thumbnail(encoded(), 64)
    assert image.width() == 64 and not simplified


def test_invalid_input_is_not_hidden_by_the_fallback():
    from dracoconv import shell_preview
    with pytest.raises(ValueError):
        shell_preview.render_thumbnail(b'invalid', 64)


def test_preview_limit_matches_renderer_limit():
    from dracoconv import preview_rendering, shell_preview
    assert shell_preview.MAX_INPUT == preview_rendering.MAX_INPUT == 64 * 1024 * 1024
