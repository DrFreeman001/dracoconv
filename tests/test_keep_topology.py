from dataclasses import replace

import numpy as np

from conftest import write_binary_stl
from dracoconv.cli import main
from dracoconv.convert import encode_bytes, encode_file
from dracoconv.engine.dracopy import DracoPyEngine
from dracoconv.mesh import Mesh
from dracoconv.params import CATALOG
from dracoconv.settings import EncodeSettings


def two_cubes_sharing_one_vertex(cube) -> Mesh:
    second = cube.positions + np.float32(20)
    remap = np.array([6] + list(range(8, 15)), dtype=np.uint32)
    return Mesh(np.vstack([cube.positions, second[1:]]), np.vstack([cube.faces, remap[cube.faces]]))


def test_it_is_a_documented_setting_on_by_default():
    assert EncodeSettings().keep_topology is True
    spec = CATALOG["keep_topology"]
    assert spec.default is True and spec.cli_flag == "--keep-topology" and all(spec.help_sections().values())


def test_non_watertight_model_keeps_its_vertices(cube):
    mesh = two_cubes_sharing_one_vertex(cube)
    data, report = encode_bytes(mesh, EncodeSettings())
    decoded = DracoPyEngine().decode(data)
    assert report.identical and report.vertices_split == 0 and len(decoded.positions) == len(mesh.positions)


def test_it_can_be_turned_off(cube):
    mesh = two_cubes_sharing_one_vertex(cube)
    data, report = encode_bytes(mesh, replace(EncodeSettings(), keep_topology=False))
    assert report.identical and report.vertices_split == 1
    assert len(DracoPyEngine().decode(data).positions) == len(mesh.positions) + 1


def test_watertight_model_is_encoded_exactly_as_before(sphere):
    data, report = encode_bytes(sphere, EncodeSettings())
    assert data == DracoPyEngine().encode(sphere, EncodeSettings()) and report.vertices_split == 0


def test_it_also_applies_with_quantization(cube):
    mesh = two_cubes_sharing_one_vertex(cube)
    _, report = encode_bytes(mesh, replace(EncodeSettings(), position_bits=14))
    assert report.vertices_split == 0


def test_split_count_is_exact_even_when_quantization_merges_vertices(dense):
    """La fusion de sommets par la grille ne doit pas masquer un dédoublement, ni en inventer un."""
    settings = replace(EncodeSettings(), position_bits=6, keep_topology=False)
    assert encode_bytes(dense, settings)[1].vertices_split == 0


def test_command_line_can_turn_it_off(tmp_path, cube, capsys):
    src = tmp_path / "c.stl"
    write_binary_stl(src, two_cubes_sharing_one_vertex(cube))
    on = encode_file(src, tmp_path / "on.drc", EncodeSettings(), skip_if_no_gain=False)
    assert main(["quality", str(src), "--no-keep-topology", "--json"]) == 0
    assert '"vertices_split": 1' in capsys.readouterr().out and on.quality.vertices_split == 0


def test_gui_command_line_shows_the_negative_form(qtbot):
    from dracoconv.gui.pages.settings import SettingsPage

    page = SettingsPage()
    qtbot.addWidget(page)
    assert "keep-topology" not in page.command_line()
    page.rows["keep_topology"].set_value(False)
    assert "--no-keep-topology" in page.command_line() and page.settings().keep_topology is False
