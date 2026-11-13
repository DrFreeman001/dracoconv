"""Full-surface rendering: dropping faces or ignoring depth must fail these tests."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
import DracoPy


def renderer():
    assert importlib.util.find_spec('dracoconv.preview_rendering'), 'Full-surface renderer is missing'
    return importlib.import_module('dracoconv.preview_rendering')


def test_mesh_keeps_every_face_and_source_arrays(cube):
    r = renderer()
    original = cube.positions.copy()
    mesh = r.prepare_arrays(cube.positions, cube.faces)
    assert np.array_equal(mesh.faces, cube.faces)
    assert np.array_equal(cube.positions, original)
    assert mesh.positions.dtype == np.float32
    assert mesh.faces.dtype == np.uint32
    assert mesh.positions.min() == -.5 and mesh.positions.max() == .5
    assert not mesh.simplified


def test_decode_keeps_dense_surface(dense):
    r = renderer()
    data = DracoPy.encode(dense.positions, dense.faces)
    mesh = r.decode_mesh(data)
    assert len(mesh.faces) == len(dense.faces) > 12000


@pytest.mark.parametrize('points,faces', [
    ([[0,0,0],[1,0,0],[0,1,float('nan')]], [[0,1,2]]),
    ([[0,0,0],[1,0,0],[0,1,0]], [[0,1,3]]),
    ([[0,0,0],[1,0,0],[0,1,0]], [[0,-1,2]]),
    ([[0,0,0]]*3, [[0,1,2]]),
])
def test_rejects_invalid_geometry(points, faces):
    with pytest.raises(ValueError):
        renderer().prepare_arrays(np.array(points), np.array(faces))


def test_gpu_surface_is_solid_and_changes_with_camera(request, cube):
    if not native_gpu_test(request):
        return
    r = renderer()
    mesh = r.prepare_arrays(cube.positions, cube.faces)
    with r.MeshRenderer(mesh) as gpu:
        front = gpu.render(128,128,yaw=0,pitch=0)
        background = front.pixel(0,0)
        assert all(front.pixel(x,y) != background for x in range(38,90) for y in range(38,90))
        rotated = gpu.render(128,128,yaw=35,pitch=20)
        assert front != rotated
        reset = gpu.render(128,128,yaw=0,pitch=0)
        assert front == reset
        with pytest.raises(ValueError): gpu.render(0,128)
        with pytest.raises(ValueError): gpu.render(999999,128)



def test_depth_is_independent_of_triangle_submission_order(request):
    if not native_gpu_test(request):
        return
    r = renderer()
    # Near flat triangle covers an identically projected, sloping far triangle.
    points = np.array([[-1,-1,.5],[1,-1,.5],[0,1,.5],[-1,-1,-.5],[1,-1,-.2],[0,1,-.5]],dtype=np.float32)
    faces = np.array([[0,1,2],[3,4,5]],dtype=np.uint32)
    with r.MeshRenderer(r.prepare_arrays(points, faces)) as gpu:
        a = gpu.render(128,128,yaw=0,pitch=0)
    with r.MeshRenderer(r.prepare_arrays(points, faces[::-1])) as gpu:
        b = gpu.render(128,128,yaw=0,pitch=0)
    assert a == b


def test_invalid_draco_and_point_cloud():
    r = renderer()
    with pytest.raises(ValueError, match='Invalid Draco'):
        r.decode_mesh(b'bad')
    with pytest.raises(ValueError, match='point clouds'):
        r.decode_mesh(DracoPy.encode(np.array([[0.,0.,0.],[1.,1.,1.]])))


def native_gpu_test(request):
    """Qt's offscreen plugin lacks Windows GL; isolate native Qt from suite qapp."""
    if sys.platform != 'win32':
        pytest.skip('Native Windows OpenGL integration test')
    if os.environ.get('DRACOCONV_GPU_TEST_CHILD') == '1':
        request.getfixturevalue('qapp')
        return True
    env = dict(os.environ, QT_QPA_PLATFORM='windows', DRACOCONV_GPU_TEST_CHILD='1')
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', request.node.nodeid, '-q'],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return False
