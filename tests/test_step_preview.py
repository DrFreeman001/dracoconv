from pathlib import Path
import shutil
import numpy as np
import pytest
from dracoconv import step_preview

BLOCK = Path(__file__).parent / 'data' / 'tall_block.step'
needs_tool = pytest.mark.skipif(not step_preview.STEP_TOOL.exists(), reason='step_mesh.exe not built')


def write_mesh(path, points, faces, magic=step_preview.MAGIC, counts=None):
    points = np.asarray(points, np.float32)
    faces = np.asarray(faces, np.uint32)
    counts = counts or (len(points), len(faces))
    path.write_bytes(magic + np.asarray(counts, '<u4').tobytes() + points.tobytes() + faces.tobytes())


def test_recognizes_step_header():
    assert step_preview.is_step(b'ISO-10303-21;\nHEADER;')
    assert step_preview.is_step(b'\xef\xbb\xbf \r\n\tISO-10303-21;')
    assert not step_preview.is_step(b'DRACO\x02\x02')
    assert not step_preview.is_step(b'')


def test_reads_compact_mesh(tmp_path):
    path = tmp_path / 'model.mesh'
    write_mesh(path, [[0, 0, 0], [2, 0, 0], [0, 4, 0]], [[0, 1, 2]])
    mesh = step_preview.read_mesh_file(path)
    assert mesh.faces.tolist() == [[0, 1, 2]]
    assert np.isclose(np.ptp(mesh.positions, axis=0).max(), 1.0)


@pytest.mark.parametrize('case', ['magic', 'truncated', 'index', 'counts'])
def test_rejects_corrupt_mesh_files(tmp_path, case):
    path = tmp_path / 'model.mesh'
    points, faces = [[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]]
    if case == 'magic':
        write_mesh(path, points, faces, magic=b'NOTMESH\0')
    elif case == 'truncated':
        write_mesh(path, points, faces)
        path.write_bytes(path.read_bytes()[:-4])
    elif case == 'index':
        write_mesh(path, points, [[0, 1, 3]])
    else:
        write_mesh(path, points, faces, counts=(3, 2))
    with pytest.raises(ValueError):
        step_preview.read_mesh_file(path)


def test_missing_reader_is_reported(tmp_path):
    with pytest.raises(ValueError, match='STEP reader'):
        step_preview.mesh_step(BLOCK, tmp_path / 'model.mesh', tool=tmp_path / 'absent.exe')


@needs_tool
def test_meshes_a_real_step_file_without_touching_it(tmp_path):
    source = tmp_path / 'input.drc'
    shutil.copyfile(BLOCK, source)
    before = source.read_bytes()
    mesh = step_preview.mesh_step(source, tmp_path / 'model.mesh')
    assert len(mesh.faces) > 12
    extent = np.ptp(mesh.positions, axis=0)
    # Bloc de 20 x 10 x 40 mm : la hauteur Z est la plus grande dimension.
    assert np.allclose(extent, [0.5, 0.25, 1.0], atol=0.01)
    assert source.read_bytes() == before
    assert not (tmp_path / 'model.mesh').exists()


@needs_tool
def test_invalid_step_is_rejected(tmp_path):
    source = tmp_path / 'input.drc'
    source.write_bytes(b'ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n')
    with pytest.raises(ValueError, match='STEP'):
        step_preview.mesh_step(source, tmp_path / 'model.mesh')
    assert not (tmp_path / 'model.mesh').exists()
