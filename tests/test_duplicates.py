"""Recherche des doublons : copies exactes, STL et son .drc, .drc d'autres réglages, variantes à ne pas confondre."""
import shutil
from dataclasses import replace

import numpy as np
import pytest

from conftest import make_sphere, write_binary_stl
from dracoconv import duplicates
from dracoconv.convert import encode_bytes
from dracoconv.duplicates import find_duplicates, fingerprint_bytes, same_model
from dracoconv.io.sniff import FileKind
from dracoconv.mesh import Mesh
from dracoconv.scan import scan
from dracoconv.settings import EncodeSettings


def _box(low, high):
    (x0, y0, z0), (x1, y1, z1) = low, high
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], dtype=np.float32)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]], dtype=np.uint32)
    return v, f


def _plate_with_pin(pin_x: float) -> Mesh:
    """Plaque 100×100×5 avec un plot 5×5×10 posé dessus à l'abscisse ``pin_x`` : même boîte, même surface."""
    pv, pf = _box((0, 0, 0), (100, 100, 5))
    qv, qf = _box((pin_x, 40, 5), (pin_x + 5, 45, 15))
    return Mesh(np.vstack([pv, qv]), np.vstack([pf, qf + 8]))


@pytest.fixture
def collection(tmp_path, sphere):
    """Une sphère en STL, sa copie, son .drc par défaut et un .drc plus grossier (« ancienne version »)."""
    folder = tmp_path / "collection"
    (folder / "copies").mkdir(parents=True)
    write_binary_stl(folder / "boule.stl", sphere)
    shutil.copy2(folder / "boule.stl", folder / "copies" / "boule (1).stl")
    (folder / "boule.drc").write_bytes(encode_bytes(sphere, EncodeSettings())[0])
    old = replace(EncodeSettings(), position_bits=11, compression_level=7)
    (folder / "copies" / "boule-ancienne.drc").write_bytes(encode_bytes(sphere, old)[0])
    write_binary_stl(folder / "autre.stl", make_sphere(3, 30.0))
    return folder


def test_finds_copies_and_converted_versions(collection):
    report = find_duplicates(scan([collection]).entries, cache_path=None)
    assert report.examined == 5 and not report.failed
    assert len(report.groups) == 1
    group = report.groups[0]
    names = sorted(e.path.name for e in group.files)
    assert names == ["boule (1).stl", "boule-ancienne.drc", "boule.drc", "boule.stl"]
    assert not group.identical
    sizes = sorted(e.size for e in group.files)
    assert group.recoverable == sum(sizes) - sizes[0]


def test_identical_files_alone_are_marked_identical(tmp_path, cube):
    write_binary_stl(tmp_path / "a.stl", cube)
    shutil.copy2(tmp_path / "a.stl", tmp_path / "b.stl")
    report = find_duplicates(scan([tmp_path]).entries, cache_path=None)
    assert len(report.groups) == 1 and report.groups[0].identical


def test_moved_feature_is_not_a_duplicate():
    from conftest import stl_bytes

    a = fingerprint_bytes(stl_bytes(_plate_with_pin(10)), FileKind.STL)
    b = fingerprint_bytes(stl_bytes(_plate_with_pin(80)), FileKind.STL)
    assert a.triangles == b.triangles and a.size == b.size and a.area == pytest.approx(b.area)
    assert not same_model(a, b)
    moved = Mesh(_plate_with_pin(10).positions + np.float32(250), _plate_with_pin(10).faces)
    assert same_model(a, fingerprint_bytes(stl_bytes(moved), FileKind.STL))  # même modèle, déplacé


def test_unreadable_file_reported_and_cache_reused(tmp_path, collection, monkeypatch):
    (collection / "casse.stl").write_bytes(b"solid x\nrien\n")
    cache = tmp_path / "cache.sqlite"
    first = find_duplicates(scan([collection]).entries, cache_path=cache)
    assert [p.name for p, _ in first.failed] == ["casse.stl"]

    def refuse(*_args):
        raise AssertionError("relu alors qu'il est dans le cache")

    monkeypatch.setattr(duplicates, "_fingerprint_file",
                        lambda path, kind: refuse() if not path.endswith("casse.stl") else (path, None, "unreadable"))
    second = find_duplicates(scan([collection]).entries, cache_path=cache)
    assert len(second.groups) == 1 and len(second.groups[0].files) == 4


def test_parallel_matches_sequential(collection):
    entries = scan([collection]).entries
    one = find_duplicates(entries, workers=1, cache_path=None)
    two = find_duplicates(entries, workers=2, cache_path=None)
    assert [sorted(e.path.name for e in g.files) for g in one.groups] == \
           [sorted(e.path.name for e in g.files) for g in two.groups]


def test_cli_lists_groups_and_writes_csv(collection, tmp_path, capsys):
    import csv
    import json

    from dracoconv.cli import main

    out_csv = tmp_path / "doublons.csv"
    assert main(["--lang", "fr", "duplicates", str(collection), "--json", "--csv", str(out_csv), "--workers", "1"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["examined"] == 5 and len(data["groups"]) == 1 and len(data["groups"][0]["files"]) == 4
    with open(out_csv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 4 and {r["group"] for r in rows} == {"1"}
    assert main(["--lang", "fr", "duplicates", str(collection), "--workers", "1"]) == 0
    assert "Groupe 1 (même modèle)" in capsys.readouterr().out


def test_dialog_search_and_trash_keeps_one_per_group(qtbot, collection, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    import dracoconv.batch
    from dracoconv.gui.duplicates_dialog import DuplicatesDialog

    dialog = DuplicatesDialog([collection], workers=1)
    qtbot.addWidget(dialog)
    dialog.start()
    qtbot.waitUntil(lambda: dialog.report is not None, timeout=60_000)
    assert dialog.tree.topLevelItemCount() == 1
    head = dialog.tree.topLevelItem(0)
    assert head.childCount() == 4

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    for c in range(4):
        head.child(c).setCheckState(0, Qt.CheckState.Checked)
    assert dialog.trash_checked(confirm=False) == 0 and warnings  # tout cocher est refusé

    trashed = []
    monkeypatch.setattr("send2trash.send2trash", lambda path: trashed.append(path))
    monkeypatch.setattr(dracoconv.batch, "recycle_bin_available", lambda path: True)
    for c in range(2, 4):
        head.child(c).setCheckState(0, Qt.CheckState.Unchecked)
    assert dialog.trash_checked(confirm=False) == 2 and len(trashed) == 2
    assert dialog.tree.topLevelItem(0).childCount() == 2
