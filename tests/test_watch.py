"""Dossiers surveillés : passage unique, fichiers récents laissés pour plus tard, tâche planifiée, fenêtre."""
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from conftest import write_binary_stl
from dracoconv import watch
from dracoconv.watch import WatchConfig, run_once, task_xml


@pytest.fixture(autouse=True)
def _normal_priority(monkeypatch):
    """Le passage baisse la priorité de son processus : pas celle de la suite de tests."""
    monkeypatch.setattr(watch, "_lower_priority", lambda: None)


def _age(path: Path, seconds: float) -> None:
    past = time.time() - seconds
    os.utime(path, (past, past))


def test_run_once_converts_settled_files_and_logs(tmp_path, sphere):
    folder = tmp_path / "téléchargements"
    folder.mkdir()
    write_binary_stl(folder / "ancien.stl", sphere)
    _age(folder / "ancien.stl", 3600)
    write_binary_stl(folder / "en-cours.stl", sphere)  # vient d'arriver : attend le passage suivant
    config = WatchConfig(folders=[str(folder), str(tmp_path / "absent")])

    summary = run_once(config)
    assert summary["done"] == 1 and summary["waiting"] == 1
    assert (folder / "ancien.drc").exists() and not (folder / "en-cours.drc").exists()
    assert (folder / "ancien.stl").exists()  # originaux gardés par défaut
    assert "1 converti(s)" in watch.read_log()[-1]

    _age(folder / "en-cours.stl", 3600)
    assert run_once(config)["done"] == 1
    assert run_once(config)["done"] == 0  # tout a déjà son .drc


def test_no_folder_is_logged(tmp_path):
    assert run_once(WatchConfig(folders=[str(tmp_path / "absent")]))["done"] == 0
    assert "aucun dossier" in watch.read_log()[-1]


def test_config_round_trip_and_fallbacks():
    WatchConfig(folders=["D:/Modèles"], profile="tolerance", originals="replace", interval_min=15).save()
    loaded = WatchConfig.load()
    assert loaded.folders == ["D:/Modèles"] and loaded.profile == "tolerance"
    assert loaded.originals == "replace" and loaded.interval_min == 15
    WatchConfig(interval_min=7, originals="mirror").save()
    loaded = WatchConfig.load()
    assert loaded.interval_min == 60 and loaded.originals == "keep"


def test_task_xml_is_valid_and_escaped():
    text = task_xml(360, (r"D:\3D Printing & Models\dracoconv-gui.exe", "--watch", r"D:\3D Printing & Models"),
                    user=r"PC\Moi")
    root = ET.fromstring(text.split("\n", 1)[1])
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.find(".//t:Exec/t:Command", ns).text == r"D:\3D Printing & Models\dracoconv-gui.exe"
    assert root.find(".//t:Repetition/t:Interval", ns).text == "PT360M"
    assert root.find(".//t:MultipleInstancesPolicy", ns).text == "IgnoreNew"
    assert root.find(".//t:LogonTrigger/t:UserId", ns).text == r"PC\Moi"


def test_launch_command_uses_windowless_python():
    program, arguments, _folder = watch.launch_command()
    assert arguments.endswith("--watch")
    assert Path(program).name.lower() in ("pythonw.exe", "python.exe", "dracoconv-gui.exe")


def test_dialog_saves_config_and_task(qtbot, tmp_path, monkeypatch):
    from dracoconv.gui.watch_dialog import WatchDialog

    calls = []
    monkeypatch.setattr(watch, "task_installed", lambda: False)
    monkeypatch.setattr(watch, "install_task", lambda config: calls.append(("install", config.interval_min)))
    monkeypatch.setattr(watch, "remove_task", lambda: calls.append(("remove",)))
    dialog = WatchDialog()
    qtbot.addWidget(dialog)
    dialog.folders.addItem(str(tmp_path))
    dialog.interval_combo.setCurrentIndex(dialog.interval_combo.findData(1440))
    dialog.replace_radio.setChecked(True)
    assert not dialog.save_button.isEnabled()  # la corbeille demande une confirmation
    dialog.replace_confirm.setChecked(True)
    dialog.enabled_box.setChecked(True)
    assert dialog.save()
    assert calls == [("install", 1440)]
    assert WatchConfig.load().originals == "replace" and WatchConfig.load().folders == [str(tmp_path)]
    dialog.enabled_box.setChecked(False)
    assert dialog.save() and calls[-1] == ("remove",)
