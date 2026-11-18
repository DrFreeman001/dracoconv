"""Ouverture de .drc dans un trancheur : détection, choix, décodage temporaire, regroupement d'une sélection."""
import os
import time
from pathlib import Path

from dracoconv import slicer
from dracoconv.convert import encode_bytes
from dracoconv.gui.launch import parse
from dracoconv.gui.slicer_open import gather
from dracoconv.settings import EncodeSettings


def _fake_exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ")
    return path


def test_find_by_registry_then_program_files(tmp_path, monkeypatch):
    orca = _fake_exe(tmp_path / "ailleurs" / "orca-slicer.exe")
    prusa = _fake_exe(tmp_path / "pf" / "Prusa3D" / "PrusaSlicer" / "prusa-slicer.exe")
    monkeypatch.setattr(slicer, "_registered_exes", lambda: {"orca-slicer.exe": orca,
                                                             "bambu-studio.exe": tmp_path / "absent.exe"})
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    found = slicer.find_slicers()
    assert list(found) == ["orca", "prusa"]  # Bambu enregistré mais absent du disque : ignoré
    assert found["orca"] == orca and found["prusa"] == prusa


def test_choice_saved_or_automatic(tmp_path, monkeypatch):
    bambu = _fake_exe(tmp_path / "bambu-studio.exe")
    monkeypatch.setattr(slicer, "find_slicers", lambda: {"bambu": bambu})
    assert slicer.chosen() == ("Bambu Studio", bambu)
    custom = _fake_exe(tmp_path / "MonTrancheur.exe")
    slicer.choose(custom)
    assert slicer.chosen() == ("MonTrancheur", custom)
    custom.unlink()  # programme désinstallé : retour au choix automatique
    assert slicer.chosen() == ("Bambu Studio", bambu)
    slicer.choose(None)
    monkeypatch.setattr(slicer, "find_slicers", lambda: {})
    assert slicer.chosen() is None


def test_prepare_decodes_to_temporary_stl(tmp_path, cube):
    data, _ = encode_bytes(cube, EncodeSettings())
    a = tmp_path / "un" / "piece.drc"
    b = tmp_path / "deux" / "piece.drc"
    for path in (a, b):
        path.parent.mkdir()
        path.write_bytes(data)
    broken = tmp_path / "casse.drc"
    broken.write_bytes(b"pas du draco")
    text = tmp_path / "notes.txt"
    text.write_text("x")
    root = tmp_path / "temp"
    old = root / "ancien"
    old.mkdir(parents=True)
    past = time.time() - slicer.MAX_AGE_S - 60
    os.utime(old, (past, past))

    ready, failed = slicer.prepare([a, b, broken, text], root=root)
    assert [p.name for p in ready] == ["piece.stl", "piece_.stl"]  # même nom dans deux dossiers
    assert all(p.stat().st_size > 84 for p in ready)
    assert [(p.name, code) for p, code in failed][1] == ("notes.txt", "not_draco")
    assert failed[0][0] == broken
    assert not old.exists()  # dossiers temporaires de plus de deux jours effacés


def test_launch_arguments_and_gathering(tmp_path):
    assert parse(["--slicer", "a.drc", "b.drc"]) == ("slicer", [Path("a.drc"), Path("b.drc")])
    a, b = tmp_path / "a.drc", tmp_path / "b.drc"

    class FakeChannel:
        def __init__(self):
            import queue

            self.requests = queue.Queue()
            self.closed = False

        def close(self):
            self.closed = True

    channel = FakeChannel()
    channel.requests.put(("slicer", [b]))
    channel.requests.put(("slicer", [a]))  # doublon : gardé une seule fois
    assert gather(channel, [a], idle_s=0.2) == [a, b]
    assert channel.closed
