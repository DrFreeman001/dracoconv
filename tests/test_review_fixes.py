"""Tests nés de la relecture indépendante : chacun reproduit un défaut signalé."""
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from conftest import make_colored_ply, make_sphere, make_textured_obj, make_zip, obj_bytes, stl_bytes, write_binary_stl
from dracoconv import batch, convert
from dracoconv.batch import BatchOptions, Journal, build_plan, recycle_bin_available, run
from dracoconv.convert import decode_file, encode_file, verify
from dracoconv.engine.dracopy import DracoPyEngine
from dracoconv.io import load_mesh
from dracoconv.io.sniff import FileKind
from dracoconv.mesh import Mesh
from dracoconv.scan import ScanOptions, scan
from dracoconv.settings import EncodeSettings

ALL = frozenset(FileKind)


def plan(root, kinds=ALL, **options):
    opts = BatchOptions(**{"workers": 1, **options})
    return build_plan(scan([root], ScanOptions(kinds=kinds)), [root], EncodeSettings(), opts), opts


def go(root, journal_path, kinds=ALL, **options):
    items, opts = plan(root, kinds, **options)
    journal = Journal(journal_path)
    journal.add_plan(items, EncodeSettings(), opts)
    run(journal, EncodeSettings(), opts)
    return journal


@pytest.fixture
def no_real_trash(monkeypatch):
    trashed = []
    monkeypatch.setattr(batch, "send2trash", lambda p: (trashed.append(Path(p)), os.remove(p)))
    monkeypatch.setattr(batch, "recycle_bin_available", lambda p: True)
    return trashed


# 1. La confirmation du mode « remplacer » ne se contourne pas ----------------------------------

def test_run_refuses_replace_without_confirmation(model_tree, tmp_path, no_real_trash):
    items, opts = plan(model_tree)
    journal = Journal(tmp_path / "j.sqlite")
    journal.add_plan(items, EncodeSettings(), opts)
    with pytest.raises(ValueError, match="replace_not_confirmed"):
        run(journal, EncodeSettings(), replace(opts, originals="replace"))
    assert no_real_trash == [] and len(journal.pending()) == 5


def test_journal_remembers_its_mode_and_refuses_another(model_tree, tmp_path, no_real_trash):
    items, opts = plan(model_tree)
    journal = Journal(tmp_path / "j.sqlite")
    journal.add_plan(items, EncodeSettings(), opts)
    stored = Journal(tmp_path / "j.sqlite").options()
    assert (stored.originals, stored.direction, stored.confirm_replace) == ("keep", "encode", False)
    with pytest.raises(ValueError, match="journal_mode_mismatch"):
        run(journal, EncodeSettings(), replace(opts, originals="replace", confirm_replace=True))
    assert no_real_trash == [] and (model_tree / "a.stl").exists()


def test_gui_retry_uses_the_mode_of_the_batch_not_the_current_buttons(qtbot, model_tree, monkeypatch, tmp_path, sphere, no_real_trash):
    from dracoconv.gui.main_window import MainWindow

    monkeypatch.setenv("APPDATA", str(tmp_path / "a"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "l"))
    (model_tree / "bad.stl").write_bytes(b"garbage" * 30)
    w = MainWindow()
    qtbot.addWidget(w)
    c = w.convert_page
    c.workers_spin.setValue(1)
    w.source_page.add_root(model_tree)
    with qtbot.waitSignal(w.source_page.scanned, timeout=20_000):
        w.source_page.start_scan()
    c.refresh_plan()
    with qtbot.waitSignal(c.finished, timeout=120_000):
        c.start_button.click()
    write_binary_stl(model_tree / "bad.stl", sphere)
    c.select_originals("replace")
    c.replace_confirm.setChecked(True)
    with qtbot.waitSignal(c.finished, timeout=120_000) as sig:
        w.journal_page.retry_failed_button.click()
    assert sig.args[0]["failed"] == 0 and (model_tree / "bad.stl").exists() and no_real_trash == []


# 2. Corbeille indisponible : l'original reste ---------------------------------------------------

def test_no_recycle_bin_on_the_volume_keeps_the_original(model_tree, tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(batch, "send2trash", lambda p: called.append(p))
    monkeypatch.setattr(batch, "recycle_bin_available", lambda p: False)
    journal = go(model_tree, tmp_path / "j.sqlite", kinds=frozenset({FileKind.STL}), originals="replace", confirm_replace=True)
    assert called == [] and (model_tree / "a.stl").exists() and (model_tree / "a.drc").exists()
    assert journal.row(model_tree / "a.stl")["note"] == "recycle_unavailable"


def test_recycle_bin_detection(tmp_path):
    assert recycle_bin_available(tmp_path / "x.stl") in (True, False)
    assert recycle_bin_available(Path("//serveur-inexistant/partage/x.stl")) is False


# 3. Le fichier écrit est relu avant d'être déclaré bon ------------------------------------------

class _ShortWrite:
    def __init__(self, path):
        self._f = open(path, "wb")

    def write(self, data):
        return self._f.write(data[: len(data) // 2])

    def __getattr__(self, name):
        return getattr(self._f, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._f.close()


def test_short_write_is_caught_before_the_file_gets_its_name(tmp_path, sphere, monkeypatch):
    src = tmp_path / "s.stl"
    write_binary_stl(src, sphere)
    monkeypatch.setattr(convert, "_open_part", lambda p: _ShortWrite(convert.long_path(p)))
    r = encode_file(src, tmp_path / "s.drc", EncodeSettings())
    assert (r.state, r.reason) == ("failed", "verify_failed")
    assert not (tmp_path / "s.drc").exists() and not list(tmp_path.glob("*.part")) and src.exists()


# 4. « Déjà converti » ne se trompe pas de fichier -----------------------------------------------

def test_same_stem_same_date_is_not_mistaken_for_already_converted(tmp_path, sphere):
    root = tmp_path / "m"
    root.mkdir()
    (root / "part.obj").write_bytes(obj_bytes(make_sphere(2, 10.0)))
    write_binary_stl(root / "part.stl", sphere)
    for name in ("part.obj", "part.stl"):
        os.utime(root / name, (1_700_000_000, 1_700_000_000))
    go(root, tmp_path / "j1.sqlite", kinds=frozenset({FileKind.OBJ}))  # premier passage interrompu après l'OBJ
    journal = go(root, tmp_path / "j2.sqlite")
    assert journal.row(root / "part.obj")["reason"] == "already_converted"
    assert journal.row(root / "part.stl")["state"] == "done" and (root / "part.stl.drc").exists()
    third = go(root, tmp_path / "j3.sqlite")
    assert third.summary()["reasons"] == {"already_converted": 2}


def test_recovery_after_a_dead_worker_never_trusts_a_file_that_was_already_there(model_tree, tmp_path, monkeypatch, no_real_trash):
    """Un fichier présent avant le lot à l'emplacement prévu ne prouve rien, même avec la bonne date."""
    items, opts = plan(model_tree, kinds=frozenset({FileKind.STL}), originals="replace", confirm_replace=True)
    journal = Journal(tmp_path / "j.sqlite")
    journal.add_plan(items, EncodeSettings(), opts)
    target = next(i for i in items if i.src.name == "a.stl")
    target.dst.write_bytes(b"pas une conversion")
    os.utime(target.dst, (target.mtime, target.mtime))

    class Broken:
        def __init__(self, max_workers=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def submit(self, fn, *args):
            raise BrokenProcessPool("mort")

    monkeypatch.setattr(batch, "ProcessPoolExecutor", Broken)
    run(journal, EncodeSettings(), replace(opts, workers=4))
    assert (model_tree / "a.stl").exists() and model_tree / "a.stl" not in no_real_trash
    assert journal.row(model_tree / "a.stl")["reason"] == "exists"


# 5. Le journal affiche les archives dont une entrée a été écartée -------------------------------

def test_journal_page_shows_zip_notes(qtbot, tmp_path, sphere):
    from dracoconv.gui.pages.journal import JournalPage

    root = tmp_path / "m"
    root.mkdir()
    inner = make_zip(tmp_path / "inner.zip", {"x.txt": b"x"}).read_bytes()
    make_zip(root / "pack.zip", {"in.zip": inner, "ok.stl": stl_bytes(sphere)})
    journal = go(root, tmp_path / "j.sqlite")
    page = JournalPage()
    qtbot.addWidget(page)
    page.load(journal)
    assert page.table.rowCount() == 1 and "in.zip" in page.table.item(0, 3).text()


# 6. Un fichier qui tue son processus n'emporte pas le lot ----------------------------------------

class _KillerPool:
    """Pool factice : le fichier « a.stl » tue toujours son processus de travail."""

    def __init__(self, max_workers=None):
        self._pool = ThreadPoolExecutor(max_workers)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._pool.shutdown(wait=True)
        return False

    def submit(self, fn, item, *args):
        if item.src.name == "a.stl":
            future = Future()
            future.set_exception(BrokenProcessPool("le processus est mort sur ce fichier"))
            return future
        return self._pool.submit(fn, item, *args)


def test_a_file_that_kills_its_worker_fails_alone(model_tree, tmp_path, monkeypatch):
    in_main = []
    real = batch._safe_convert
    monkeypatch.setattr(batch, "_safe_convert", lambda item, *a: (in_main.append(item.src.name), real(item, *a))[1])
    monkeypatch.setattr(batch, "ProcessPoolExecutor", _KillerPool)
    journal = go(model_tree, tmp_path / "j.sqlite", workers=4)
    s = journal.summary()
    assert s["done"] == 4 and s["failed"] == 1 and s["pending"] == 0
    assert journal.row(model_tree / "a.stl")["reason"] == "worker_crashed"
    assert "a.stl" not in in_main  # jamais retenté dans le processus principal


# 7. Jamais de remplacement quand la conversion perd des données ---------------------------------

def test_textured_obj_is_converted_but_never_replaced(tmp_path, no_real_trash):
    root = tmp_path / "m"
    root.mkdir()
    textured = make_textured_obj(root)
    lossy = encode_file(textured, tmp_path / "t.drc", EncodeSettings(), skip_if_no_gain=False)
    assert lossy.state == "done" and lossy.lossy_source is True  # les normales du fichier sont écartées par défaut
    kept = encode_file(textured, tmp_path / "t2.drc", replace(EncodeSettings(), skip_attributes=frozenset()), skip_if_no_gain=False)
    assert kept.lossy_source is False
    items, opts = plan(root, originals="replace", confirm_replace=True, skip_if_no_gain=False)
    journal = Journal(tmp_path / "j.sqlite")
    journal.add_plan(items, EncodeSettings(), opts)
    run(journal, EncodeSettings(), opts)
    assert textured.exists() and no_real_trash == [] and journal.row(textured)["note"] == "replace_forbidden"


def test_obj_with_materials_is_lossy(tmp_path):
    src = tmp_path / "m.obj"
    src.write_text("mtllib m.mtl\nusemtl rouge\nv 0 0 0\nv 10 0 0\nv 0 10 0\nf 1 2 3\n", encoding="ascii")
    assert encode_file(src, tmp_path / "m.drc", EncodeSettings(), skip_if_no_gain=False).lossy_source is True


def test_point_cloud_setting_is_lossy(tmp_path, sphere):
    src = tmp_path / "s.stl"
    write_binary_stl(src, sphere)
    r = encode_file(src, tmp_path / "s.drc", replace(EncodeSettings(), point_cloud=True))
    assert r.state == "done" and r.lossy_source is True


def test_plain_stl_is_not_lossy(tmp_path, sphere):
    src = tmp_path / "s.stl"
    write_binary_stl(src, sphere)
    assert encode_file(src, tmp_path / "s.drc", EncodeSettings()).lossy_source is False


def test_decoding_colors_to_stl_is_lossy_but_to_ply_is_not(tmp_path):
    mesh = load_mesh(make_colored_ply(tmp_path))
    (tmp_path / "c.drc").write_bytes(DracoPyEngine().encode(mesh, EncodeSettings()))
    assert decode_file(tmp_path / "c.drc", tmp_path / "c.stl", "stl").lossy_source is True
    assert decode_file(tmp_path / "c.drc", tmp_path / "c2.ply", "ply").lossy_source is False


# 8. Vérification avec quantification : des triangles manquants ne passent pas ---------------------

def test_missing_triangles_fail_quantized_verification(sphere):
    quantized = replace(EncodeSettings(), position_bits=14)
    thinned = Mesh(sphere.positions, np.delete(sphere.faces, np.arange(0, len(sphere.faces), 10), axis=0))
    assert len(np.unique(thinned.faces)) == len(sphere.positions)  # tous les sommets servent encore
    data = DracoPyEngine().encode(thinned, quantized)
    assert verify(sphere, data, quantized)[0] is False
    assert verify(sphere, DracoPyEngine().encode(sphere, quantized), quantized)[0] is True


def test_extra_geometry_fails_quantized_verification(sphere):
    quantized = replace(EncodeSettings(), position_bits=14)
    half = Mesh(sphere.positions, sphere.faces[: len(sphere.faces) // 2])
    used = np.unique(half.faces)
    compact = Mesh(sphere.positions[used], np.searchsorted(used, half.faces).astype(np.uint32))
    assert verify(compact, DracoPyEngine().encode(sphere, quantized), quantized)[0] is False


def test_coarse_quantization_still_passes_on_a_real_shape(dense):
    for bits in (6, 8, 10):
        settings = replace(EncodeSettings(), position_bits=bits)
        assert verify(dense, DracoPyEngine().encode(dense, settings), settings)[0] is True
