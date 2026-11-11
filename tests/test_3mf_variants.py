import pytest

from conftest import make_two_cube_3mf, make_zip
from dracoconv.convert import encode_file
from dracoconv.io import load_mesh
from dracoconv.io.sniff import FileKind, detect_kind, kind_from_name
from dracoconv.mesh import MeshReadError
from dracoconv.scan import ScanOptions, scan
from dracoconv.settings import EncodeSettings


def test_sliced_3mf_is_its_own_kind(tmp_path):
    assert kind_from_name("plateau.gcode.3mf") is FileKind.GCODE_3MF
    assert kind_from_name("Plateau.GCODE.3MF") is FileKind.GCODE_3MF
    assert kind_from_name("modele.3mf") is FileKind.THREEMF
    p = tmp_path / "a.gcode.3mf"
    p.write_bytes(b"PK")
    assert detect_kind(p) is FileKind.GCODE_3MF


def test_sliced_3mf_is_ignored_by_scan(tmp_path, cube):
    make_two_cube_3mf(tmp_path, cube)
    make_zip(tmp_path / "plateau.gcode.3mf", {"Metadata/plate_1.gcode": b"G1 X0"})
    inv = scan([tmp_path], ScanOptions(kinds=frozenset(FileKind)))
    assert inv.count() == 1 and inv.ignored["gcode_3mf"] == 1


def test_sliced_3mf_is_skipped_not_failed(tmp_path):
    src = make_zip(tmp_path / "plateau.gcode.3mf", {"Metadata/plate_1.gcode": b"G1 X0"})
    r = encode_file(src, tmp_path / "x.drc", EncodeSettings())
    assert (r.state, r.reason) == ("skipped", "gcode_3mf") and src.exists()


def test_project_3mf_that_cannot_be_read_is_skipped(tmp_path):
    src = make_zip(tmp_path / "projet.3mf", {"3D/3dmodel.model": b"<model><resources/><build/></model>",
                                             "Metadata/model_settings.config": b"<config/>"})
    with pytest.raises(MeshReadError) as e:
        load_mesh(src)
    assert e.value.reason == "unsupported_3mf"
    r = encode_file(src, tmp_path / "x.drc", EncodeSettings())
    assert (r.state, r.reason) == ("skipped", "unsupported_3mf") and not (tmp_path / "x.drc").exists()
