import threading

from conftest import CUBE, make_zip, stl_bytes, write_binary_stl
from dracoconv.io.archive import list_models
from dracoconv.io.sniff import FileKind
from dracoconv.scan import DEFAULT_EXCLUDES, Inventory, ScanOptions, scan

ALL = frozenset(FileKind)


def test_counts_by_kind(model_tree):
    inv = scan([model_tree], ScanOptions(kinds=ALL))
    assert inv.count(FileKind.STL) == 3 and inv.count(FileKind.OBJ) == 1
    assert inv.ignored["compiler_obj"] == 1
    assert [e.archive_models for e in inv.entries if e.kind is FileKind.ZIP] == [2]
    assert inv.count() == 5


def test_totals(model_tree):
    inv = scan([model_tree], ScanOptions(kinds=ALL))
    stl = [model_tree / "a.stl", model_tree / "sub" / "b.stl", model_tree / "sub" / "c.stl"]
    assert inv.total_bytes(FileKind.STL) == sum(p.stat().st_size for p in stl)
    assert inv.total_bytes() == sum(e.size for e in inv.entries)
    assert set(inv.by_kind()) == {FileKind.STL, FileKind.OBJ, FileKind.ZIP}


def test_entries_are_sorted_and_carry_mtime(model_tree):
    inv = scan([model_tree], ScanOptions(kinds=frozenset({FileKind.STL})))
    assert [e.path for e in inv.entries] == sorted(e.path for e in inv.entries)
    assert all(e.mtime > 0 and e.size > 0 for e in inv.entries)


def test_kind_filter(model_tree):
    inv = scan([model_tree], ScanOptions(kinds=frozenset({FileKind.OBJ})))
    assert inv.count() == 1 and inv.entries[0].path.name == "d.obj"


def test_zip_without_models_ignored(tmp_path):
    make_zip(tmp_path / "docs.zip", {"a.txt": b"x"})
    inv = scan([tmp_path], ScanOptions(kinds=ALL))
    assert inv.count(FileKind.ZIP) == 0 and inv.ignored["zip_without_models"] == 1


def test_zip_with_drc_counted_for_decoding(tmp_path):
    make_zip(tmp_path / "pack.drc.zip", {"a.drc": b"DRACO", "b.txt": b"x"})
    inv = scan([tmp_path], ScanOptions(kinds=ALL))
    entry = inv.entries[0]
    assert entry.kind is FileKind.ZIP and entry.archive_models == 0 and entry.archive_drc == 1


def test_corrupt_zip_ignored(tmp_path):
    (tmp_path / "bad.zip").write_bytes(b"not a zip at all")
    inv = scan([tmp_path], ScanOptions(kinds=ALL))
    assert inv.count() == 0 and inv.ignored["unreadable"] == 1


def test_zips_not_opened_when_disabled(tmp_path):
    make_zip(tmp_path / "docs.zip", {"a.txt": b"x"})
    inv = scan([tmp_path], ScanOptions(kinds=ALL, look_inside_zips=False))
    assert inv.count(FileKind.ZIP) == 1


def test_excluded_dirs(model_tree):
    assert "node_modules" in DEFAULT_EXCLUDES and "$Recycle.Bin" in DEFAULT_EXCLUDES
    (model_tree / "node_modules").mkdir()
    write_binary_stl(model_tree / "node_modules" / "x.stl", CUBE)
    assert scan([model_tree], ScanOptions(kinds=frozenset({FileKind.STL}))).count() == 3


def test_user_excluded_dir(model_tree):
    options = ScanOptions(kinds=frozenset({FileKind.STL}), exclude_dirs=DEFAULT_EXCLUDES + ("sub",))
    assert scan([model_tree], options).count() == 1


def test_single_file_root(model_tree):
    assert scan([model_tree / "a.stl"], ScanOptions(kinds=frozenset({FileKind.STL}))).count() == 1


def test_missing_root_is_ignored(tmp_path):
    inv = scan([tmp_path / "absent"], ScanOptions(kinds=ALL))
    assert inv.count() == 0 and inv.ignored["access_denied"] == 1


def test_stop_event(model_tree):
    ev = threading.Event()
    ev.set()
    assert scan([model_tree], ScanOptions(kinds=ALL), stop=ev).count() == 0


def test_progress_reports_final_count(model_tree):
    seen = []
    inv = scan([model_tree], ScanOptions(kinds=ALL), on_progress=seen.append)
    assert seen and seen[-1] == inv.count()


def test_list_models(tmp_path, cube):
    z = make_zip(tmp_path / "p.zip", {"a/m.stl": stl_bytes(cube), "n.OBJ": b"v 0 0 0\n", "t.txt": b"x", "k.drc": b"D"})
    found = {name: (kind, size) for name, kind, size, _ in list_models(z)}
    assert found == {"a/m.stl": (FileKind.STL, 684), "n.OBJ": (FileKind.OBJ, 8), "k.drc": (FileKind.DRC, 1)}


def test_empty_inventory():
    assert Inventory().count() == 0 and Inventory().total_bytes() == 0
