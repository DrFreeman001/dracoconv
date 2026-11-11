import errno
import os
import shutil
import threading
from pathlib import Path

import pytest

from conftest import make_sphere, make_two_cube_3mf, same_geometry, write_binary_stl
from dracoconv import batch
from dracoconv.batch import BatchOptions, Journal, build_plan, check_free_space, run
from dracoconv.engine.dracopy import DracoPyEngine
from dracoconv.io import save_mesh
from dracoconv.io.sniff import FileKind
from dracoconv.scan import ScanOptions, scan
from dracoconv.settings import EncodeSettings

ALL = frozenset(FileKind)


def plan_for(root, kinds=ALL, **options):
    opts = BatchOptions(**options)
    inv = scan([root], ScanOptions(kinds=kinds))
    return build_plan(inv, [root], EncodeSettings(), opts), opts


def run_batch(root, journal=None, kinds=ALL, stop=None, on_progress=None, settings=None, **options):
    """Recense, planifie et exécute ; rend le journal. Un seul processus par défaut pour des tests rapides."""
    options.setdefault("workers", 1)
    settings = settings or EncodeSettings()
    items, opts = plan_for(root, kinds, **options)
    journal = journal or Journal(Path(root).parent / f"journal-{len(os.listdir(Path(root).parent))}.sqlite")
    journal.add_plan(items, settings)
    run(journal, settings, opts, on_progress=on_progress, stop=stop)
    return journal


def decode_to_mesh(path):
    return DracoPyEngine().decode(Path(path).read_bytes())


def test_keep_mode(model_tree):
    s = run_batch(model_tree).summary()
    assert s["total"] == 5 and s["done"] == 5 and s["failed"] == 0 and s["pending"] == 0
    assert (model_tree / "a.stl").exists() and (model_tree / "a.drc").exists()
    assert (model_tree / "sub" / "c.drc").exists() and (model_tree / "d.drc").exists()
    assert (model_tree / "pack.drc.zip").exists() and (model_tree / "pack.zip").exists()
    assert not (model_tree / "build.drc").exists()
    assert 0 < s["bytes_after"] < s["bytes_before"]


def test_parallel_run_gives_same_result(model_tree):
    s = run_batch(model_tree, workers=3).summary()
    assert s["done"] == 5 and (model_tree / "sub" / "b.drc").exists()


def test_mirror_mode(model_tree, tmp_path):
    run_batch(model_tree, originals="mirror", mirror_dir=tmp_path / "out")
    assert (tmp_path / "out" / "sub" / "b.drc").exists() and (tmp_path / "out" / "pack.drc.zip").exists()
    assert not (model_tree / "sub" / "b.drc").exists() and (model_tree / "sub" / "b.stl").exists()


def test_mirror_requires_directory(model_tree):
    with pytest.raises(ValueError, match="mirror_dir_required"):
        plan_for(model_tree, originals="mirror")


def test_replace_requires_confirmation(model_tree):
    with pytest.raises(ValueError, match="replace_not_confirmed"):
        plan_for(model_tree, originals="replace")


def test_replace_sends_to_recycle_bin(model_tree, monkeypatch):
    trashed = []
    monkeypatch.setattr(batch, "send2trash", lambda p: (trashed.append(Path(p)), os.remove(p)))
    run_batch(model_tree, originals="replace", confirm_replace=True)
    assert model_tree / "a.stl" in trashed and (model_tree / "a.drc").exists() and not (model_tree / "a.stl").exists()
    assert model_tree / "d.obj" in trashed


def test_replace_never_applies_to_3mf_and_zip(model_tree, cube, monkeypatch):
    make_two_cube_3mf(model_tree, cube)
    trashed = []
    monkeypatch.setattr(batch, "send2trash", lambda p: trashed.append(Path(p)))
    items, _ = plan_for(model_tree, originals="replace", confirm_replace=True)
    flagged = {i.src.suffix: (i.replace_allowed, i.warning) for i in items}
    assert flagged[".3mf"] == (False, "data_loss") and flagged[".zip"] == (False, "not_replaceable")
    assert flagged[".stl"] == (True, None)
    run_batch(model_tree, originals="replace", confirm_replace=True)
    assert trashed and not any(p.suffix in (".3mf", ".zip") for p in trashed)
    assert (model_tree / "pack.zip").exists() and (model_tree / "two.3mf").exists()


def test_recycle_bin_unavailable_keeps_original(model_tree, monkeypatch):
    def refuse(path):
        raise OSError("pas de corbeille sur ce volume")

    monkeypatch.setattr(batch, "send2trash", refuse)
    journal = run_batch(model_tree, originals="replace", confirm_replace=True)
    assert (model_tree / "a.stl").exists() and (model_tree / "a.drc").exists()
    assert journal.row(model_tree / "a.stl")["note"] == "recycle_unavailable"
    assert journal.row(model_tree / "a.stl")["state"] == "done"


def test_failed_file_keeps_original_and_batch_continues(model_tree, monkeypatch):
    (model_tree / "bad.stl").write_bytes(b"garbage" * 30)
    monkeypatch.setattr(batch, "send2trash", lambda p: os.remove(p))
    journal = run_batch(model_tree, originals="replace", confirm_replace=True)
    s = journal.summary()
    assert s["failed"] == 1 and s["done"] == 5 and (model_tree / "bad.stl").exists()
    assert journal.row(model_tree / "bad.stl")["reason"] == "unreadable" and s["reasons"] == {"unreadable": 1}


def test_unwritable_destination_reported(model_tree, tmp_path, monkeypatch):
    def refuse(path):
        raise PermissionError(13, "refus")

    monkeypatch.setattr("dracoconv.convert._open_part", refuse)
    s = run_batch(model_tree, kinds=frozenset({FileKind.STL}), originals="mirror", mirror_dir=tmp_path / "out").summary()
    assert s["total"] == 3 and s["failed"] == 3 and s["reasons"] == {"access_denied": 3}
    assert (model_tree / "a.stl").exists()


def test_resume_skips_done(model_tree, tmp_path):
    journal = Journal(tmp_path / "j.sqlite")
    stop = threading.Event()
    seen = []

    def stop_after_two(result):
        seen.append(result)
        if len(seen) == 2:
            stop.set()

    run_batch(model_tree, journal=journal, stop=stop, on_progress=stop_after_two)
    assert journal.summary()["done"] == 2 and len(journal.pending()) == 3
    second = []
    run_batch(model_tree, journal=journal, on_progress=second.append)
    assert len(second) == 3 and journal.summary()["done"] == 5 and not journal.pending()
    assert {r.src for r in second}.isdisjoint({r.src for r in seen})


def test_journal_survives_reopening(model_tree, tmp_path):
    run_batch(model_tree, journal=Journal(tmp_path / "j.sqlite"))
    reopened = Journal(tmp_path / "j.sqlite")
    assert reopened.summary()["done"] == 5 and reopened.settings() == EncodeSettings()


def test_retry_failed(model_tree, tmp_path, sphere):
    (model_tree / "bad.stl").write_bytes(b"garbage" * 30)
    journal = run_batch(model_tree, journal=Journal(tmp_path / "j.sqlite"))
    write_binary_stl(model_tree / "bad.stl", sphere)
    assert journal.retry_failed() == 1 and len(journal.pending()) == 1
    run(journal, EncodeSettings(), BatchOptions(workers=1))
    assert journal.summary()["failed"] == 0 and (model_tree / "bad.drc").exists()


def test_changed_file_is_replanned(model_tree, tmp_path, sphere):
    journal = Journal(tmp_path / "j.sqlite")
    items, opts = plan_for(model_tree)
    journal.add_plan(items, EncodeSettings())
    write_binary_stl(model_tree / "a.stl", sphere)
    os.utime(model_tree / "a.stl", (1_000_000, 1_000_000))
    run(journal, EncodeSettings(), opts)
    assert same_geometry(decode_to_mesh(model_tree / "a.drc"), sphere)
    assert journal.row(model_tree / "a.stl")["note"] == "changed"


def test_name_collision_in_plan(tmp_path, cube):
    write_binary_stl(tmp_path / "m.stl", cube)
    save_mesh(cube, tmp_path / "m.ply", "ply")
    items, _ = plan_for(tmp_path)
    assert {i.src.name: i.dst.name for i in items} == {"m.ply": "m.drc", "m.stl": "m.stl.drc"}


def test_decode_direction(model_tree):
    run_batch(model_tree)
    journal = run_batch(model_tree, direction="decode", output_format="ply")
    assert journal.summary()["done"] == 5
    assert (model_tree / "a.ply").exists() and (model_tree / "pack.ply.zip").exists()
    assert same_geometry(decode_to_mesh(model_tree / "a.drc"), make_sphere(2, 30.0))


def test_big_files_run_alone(model_tree, monkeypatch):
    active, peak = [0], [0]
    real = batch.encode_file

    def tracked(*a, **k):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        try:
            return real(*a, **k)
        finally:
            active[0] -= 1

    monkeypatch.setattr(batch, "encode_file", tracked)
    s = run_batch(model_tree, big_file_bytes=1, workers=4).summary()
    assert s["done"] == 5 and peak[0] == 1


def test_free_space_check(tmp_path):
    assert check_free_space(tmp_path, 1) is True
    assert check_free_space(tmp_path / "pas" / "encore", 1) is True
    assert check_free_space(tmp_path, shutil.disk_usage(tmp_path).free + 1) is False


def test_disk_full_pauses_batch(model_tree, monkeypatch):
    def full(*a, **k):
        raise OSError(errno.ENOSPC, "plus de place")

    monkeypatch.setattr(batch, "encode_file", full)
    journal = run_batch(model_tree, kinds=frozenset({FileKind.STL}))
    s = journal.summary()
    assert s["paused"] == "disk_full" and s["pending"] == s["total"] == 3 and s["failed"] == 0


def test_csv_export(model_tree, tmp_path):
    journal = run_batch(model_tree)
    journal.export_csv(tmp_path / "j.csv")
    lines = (tmp_path / "j.csv").read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].startswith("src,dst,kind") and len(lines) == 6


def test_on_progress_receives_every_result(model_tree):
    seen = []
    run_batch(model_tree, on_progress=seen.append)
    assert len(seen) == 5 and all(r.state == "done" for r in seen)


def test_second_run_without_journal_converts_nothing_new(model_tree):
    run_batch(model_tree)
    before = sorted(p.name for p in model_tree.rglob("*"))
    s = run_batch(model_tree).summary()
    assert s["done"] == 0 and s["skipped"] == 5 and s["reasons"] == {"already_converted": 5}
    assert sorted(p.name for p in model_tree.rglob("*")) == before


def test_modified_source_is_converted_again(model_tree, sphere):
    run_batch(model_tree)
    write_binary_stl(model_tree / "a.stl", sphere)
    os.utime(model_tree / "a.stl", (2_000_000_000, 2_000_000_000))
    s = run_batch(model_tree).summary()
    assert s["done"] == 1 and s["skipped"] == 4
    assert same_geometry(decode_to_mesh(model_tree / "a.stl.drc"), sphere)


def test_decoding_next_to_the_untouched_original_is_skipped(model_tree):
    run_batch(model_tree)
    s = run_batch(model_tree, direction="decode", output_format="stl", kinds=frozenset({FileKind.DRC})).summary()
    assert s["reasons"] == {"already_converted": 3} and s["done"] == 1  # d.drc vient d'un OBJ : pas de d.stl
    assert (model_tree / "d.stl").exists() and not (model_tree / "a (1).stl").exists()


class _InlinePool:
    """Remplace le pool de processus par des fils, pour observer l'ordonnancement depuis le test."""

    def __init__(self, max_workers=None):
        from concurrent.futures import ThreadPoolExecutor

        self._pool = ThreadPoolExecutor(max_workers)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._pool.shutdown(wait=True)

    def submit(self, fn, *args):
        return self._pool.submit(fn, *args)


def test_out_of_memory_in_parallel_phase_is_retried_alone(model_tree, monkeypatch):
    calls: dict = {}
    real = batch._convert_item
    lock = threading.Lock()

    def flaky(item, settings, options):
        with lock:
            calls[item.src] = calls.get(item.src, 0) + 1
            first = calls[item.src] == 1
        if first:
            raise MemoryError("bad allocation")
        return real(item, settings, options)

    monkeypatch.setattr(batch, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(batch, "_convert_item", flaky)
    s = run_batch(model_tree, workers=4).summary()
    assert s["done"] == 5 and s["failed"] == 0 and set(calls.values()) == {2}


def test_memory_error_twice_is_a_failure(model_tree, monkeypatch):
    def always(item, settings, options):
        raise MemoryError("bad allocation")

    monkeypatch.setattr(batch, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(batch, "_convert_item", always)
    s = run_batch(model_tree, workers=4).summary()
    assert s["failed"] == 5 and s["reasons"] == {"out_of_memory": 5}


def test_broken_pool_falls_back_to_one_by_one(model_tree, monkeypatch):
    from concurrent.futures.process import BrokenProcessPool

    class Broken(_InlinePool):
        def submit(self, fn, *args):
            raise BrokenProcessPool("un processus de travail est mort")

    monkeypatch.setattr(batch, "ProcessPoolExecutor", Broken)
    s = run_batch(model_tree, workers=4).summary()
    assert s["done"] == 5 and s["failed"] == 0


def test_pool_dying_while_results_come_back_loses_no_file(model_tree, monkeypatch):
    from concurrent.futures import Future
    from concurrent.futures.process import BrokenProcessPool

    class DiesOnce(_InlinePool):
        died = False

        def submit(self, fn, *args):
            if not DiesOnce.died:
                DiesOnce.died = True
                future = Future()
                future.set_exception(BrokenProcessPool("mort pendant le travail"))
                return future
            return super().submit(fn, *args)

    monkeypatch.setattr(batch, "ProcessPoolExecutor", DiesOnce)
    s = run_batch(model_tree, workers=4).summary()
    assert s["done"] == 5 and s["pending"] == 0 and s["failed"] == 0


def test_workers_run_single_threaded_math(model_tree, monkeypatch):
    """Sans cela, chaque processus réserve des tampons pour autant de fils qu'il y a de cœurs."""
    seen = {}

    class Spy(_InlinePool):
        def __init__(self, max_workers=None):
            seen.update({name: os.environ.get(name) for name in batch.THREAD_VARIABLES})
            super().__init__(max_workers)

    monkeypatch.delenv("OPENBLAS_NUM_THREADS", raising=False)
    monkeypatch.setenv("OMP_NUM_THREADS", "7")
    monkeypatch.setattr(batch, "ProcessPoolExecutor", Spy)
    run_batch(model_tree, workers=4)
    assert seen["OPENBLAS_NUM_THREADS"] == "1" and seen["OMP_NUM_THREADS"] == "1"
    assert "OPENBLAS_NUM_THREADS" not in os.environ and os.environ["OMP_NUM_THREADS"] == "7"


def test_memory_budget_limits_concurrency(model_tree, monkeypatch):
    active, peak = [0], [0]
    real = batch._convert_item
    lock = threading.Lock()

    def tracked(item, settings, options):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        try:
            return real(item, settings, options)
        finally:
            with lock:
                active[0] -= 1

    monkeypatch.setattr(batch, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(batch, "_convert_item", tracked)
    monkeypatch.setattr(batch, "available_memory", lambda: 1000)  # presque rien : un seul fichier à la fois
    s = run_batch(model_tree, workers=4).summary()
    assert s["done"] == 5 and peak[0] == 1
    monkeypatch.setattr(batch, "available_memory", lambda: 1 << 40)
    for p in list(model_tree.rglob("*.drc")) + list(model_tree.rglob("*.drc.zip")):
        p.unlink()
    peak[0] = 0
    assert run_batch(model_tree, workers=4).summary()["done"] == 5 and peak[0] > 1


def test_available_memory_is_plausible():
    assert batch.available_memory() is None or batch.available_memory() > 1 << 20


def test_default_workers_is_half_the_cores():
    assert BatchOptions().resolved_workers() == max(1, (os.cpu_count() or 2) // 2)
    assert BatchOptions(workers=3).resolved_workers() == 3
