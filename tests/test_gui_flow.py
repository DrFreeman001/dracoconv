from dataclasses import replace

import pytest
from PySide6.QtWidgets import QAbstractButton, QGroupBox, QLabel

from conftest import make_two_cube_3mf
from dracoconv.gui.main_window import MainWindow
from dracoconv.i18n import all_keys, set_language, tr
from dracoconv.io.sniff import FileKind
from dracoconv.settings import EncodeSettings


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    set_language("fr")
    yield
    set_language("fr")


@pytest.fixture
def window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.convert_page.workers_spin.setValue(1)
    return w


@pytest.fixture
def scanned_window(qtbot, window, model_tree):
    window.source_page.add_root(model_tree)
    with qtbot.waitSignal(window.source_page.scanned, timeout=20_000):
        window.source_page.start_scan()
    return window


def visible_texts(w) -> list[str]:
    texts = [w.windowTitle()]
    for kind in (QLabel, QAbstractButton):
        texts += [x.text() for x in w.findChildren(kind)]
    texts += [x.title() for x in w.findChildren(QGroupBox)]
    texts += [w.steps.item(i).text() for i in range(w.steps.count())]
    return texts


def test_five_steps_in_order(window):
    assert window.steps.count() == 5 and window.pages.count() == 5
    assert [window.pages.widget(i) for i in range(5)] == [
        window.source_page, window.settings_page, window.projection_page, window.convert_page, window.journal_page]
    window.steps.setCurrentRow(3)
    assert window.pages.currentWidget() is window.convert_page
    window.next_button.click()
    assert window.pages.currentWidget() is window.journal_page
    window.previous_button.click()
    assert window.pages.currentWidget() is window.convert_page


def test_scan_fills_table(qtbot, scanned_window, model_tree):
    w = scanned_window
    assert w.state.inventory.count(FileKind.STL) == 3 and w.state.roots == [model_tree]
    rows = {w.source_page.table.item(r, 0).text(): w.source_page.table.item(r, 1).text()
            for r in range(w.source_page.table.rowCount())}
    assert rows[tr("kind.stl")] == "3" and rows[tr("kind.zip")] == "1" and rows[tr("cli.total")] == "5"
    assert tr("reason.compiler_obj") in w.source_page.ignored_label.text()


def test_unchecked_kind_is_not_scanned(qtbot, window, model_tree):
    window.source_page.add_root(model_tree)
    window.source_page.kind_boxes[FileKind.ZIP].setChecked(False)
    with qtbot.waitSignal(window.source_page.scanned, timeout=20_000):
        window.source_page.start_scan()
    assert window.state.inventory.count(FileKind.ZIP) == 0 and window.state.inventory.count() == 4


def test_projection_shows_gain_and_margin(qtbot, scanned_window):
    p = scanned_window.projection_page
    p.refresh_instant()
    assert p.current_label.text() and p.projected_label.text() and p.saved_label.text().endswith("%")
    assert scanned_window.state.projection.method == "instant"
    with qtbot.waitSignal(p.sampled, timeout=60_000):
        p.start_sampling()
    assert "±" in p.margin_label.text() and scanned_window.state.projection.method == "sampled"
    assert p.kind_table.rowCount() == 3 and str(5) in p.method_label.text()


def test_quality_block_lossless_vs_quantized(qtbot, scanned_window):
    w = scanned_window
    p = w.projection_page
    p.refresh_instant()
    assert tr("quality.identical") in p.theoretical_label.text()
    w.settings_page.set_settings(replace(EncodeSettings(), position_bits=12))
    p.refresh_instant()
    assert "mm" in p.theoretical_label.text() and tr("quality.identical") not in p.theoretical_label.text()
    assert len(p.chart.chart().series()) >= 4  # écart théorique + trois repères
    assert "0,2" in p.marks_label.text() and "0,4" in p.marks_label.text() and "0,01" in p.marks_label.text()


def test_measured_quality_after_sampling(qtbot, scanned_window):
    w = scanned_window
    w.settings_page.set_settings(replace(EncodeSettings(), position_bits=12))
    p = w.projection_page
    with qtbot.waitSignal(p.quality_ready, timeout=120_000):
        p.start_sampling()
    assert "mm" in p.measured_label.text() and p.measured_label.text() != tr("gui.projection.not_measured")
    names = [s.name() for s in p.chart.chart().series()]
    assert tr("gui.chart.size") in names and tr("gui.chart.measured") in names


def test_plan_lists_files_and_warnings(qtbot, scanned_window, model_tree, cube):
    make_two_cube_3mf(model_tree, cube)
    w = scanned_window
    with qtbot.waitSignal(w.source_page.scanned, timeout=20_000):
        w.source_page.start_scan()
    c = w.convert_page
    c.refresh_plan()
    assert c.plan_table.rowCount() == 6 and "6" in c.plan_label.text()
    remarks = " ".join(c.plan_table.item(r, 3).text() for r in range(6))
    assert tr("warning.data_loss") in remarks


def test_replace_needs_checkbox(qtbot, scanned_window):
    c = scanned_window.convert_page
    c.refresh_plan()
    assert c.start_button.isEnabled()
    c.select_originals("replace")
    assert not c.start_button.isEnabled() and not c.replace_confirm.isHidden()
    c.replace_confirm.setChecked(True)
    assert c.start_button.isEnabled()
    remarks = " ".join(c.plan_table.item(r, 3).text() for r in range(c.plan_table.rowCount()))
    assert tr("warning.not_replaceable") in remarks
    c.select_originals("keep")
    assert c.replace_confirm.isHidden() and c.start_button.isEnabled()


def test_mirror_needs_directory(qtbot, scanned_window, tmp_path):
    c = scanned_window.convert_page
    c.refresh_plan()
    c.select_originals("mirror")
    assert not c.start_button.isEnabled()
    c.mirror_edit.setText(str(tmp_path / "miroir"))
    assert c.start_button.isEnabled()
    assert str(tmp_path / "miroir") in c.plan_table.item(0, 1).text()


def test_full_conversion_from_window(qtbot, scanned_window, model_tree):
    w = scanned_window
    c = w.convert_page
    c.refresh_plan()
    steps = []
    c.progressed.connect(lambda done, total: steps.append((done, total)))
    with qtbot.waitSignal(c.finished, timeout=120_000) as sig:
        c.start_button.click()
    summary = sig.args[0]
    assert summary["done"] == 5 and summary["failed"] == 0 and (model_tree / "a.drc").exists()
    assert steps[0] == (0, 5) and steps[-1] == (5, 5)  # avancement de la barre des tâches
    assert w.journal_page.table.rowCount() == summary["total"] == 5
    assert "5" in w.journal_page.summary_label.text() and not c.stop_button.isEnabled()
    assert not c.start_button.isEnabled()  # tout est déjà converti : plus rien à lancer
    assert tr("reason.already_converted") in c.plan_table.item(0, 3).text()
    w.journal_page.filter_combo.setCurrentIndex(w.journal_page.filter_combo.findData("failed"))
    assert w.journal_page.table.rowCount() == 0


def test_decode_direction_from_window(qtbot, scanned_window, model_tree):
    w = scanned_window
    c = w.convert_page
    c.refresh_plan()
    with qtbot.waitSignal(c.finished, timeout=120_000):
        c.start_button.click()
    w.source_page.direction_combo.setCurrentIndex(w.source_page.direction_combo.findData("decode"))
    with qtbot.waitSignal(w.source_page.scanned, timeout=20_000):
        w.source_page.start_scan()
    c.format_combo.setCurrentIndex(c.format_combo.findData("ply"))
    c.refresh_plan()
    with qtbot.waitSignal(c.finished, timeout=120_000) as sig:
        c.start_button.click()
    assert sig.args[0]["done"] == 5 and (model_tree / "a.ply").exists()


def test_stop_leaves_consistent_counts(qtbot, scanned_window):
    c = scanned_window.convert_page
    c.refresh_plan()
    with qtbot.waitSignal(c.finished, timeout=120_000) as sig:
        c.start_button.click()
        c.stop_button.click()
    s = sig.args[0]
    assert s["done"] + s["pending"] + s["failed"] + s["skipped"] == s["total"] == 5


def test_export_and_retry_buttons(qtbot, scanned_window, model_tree, tmp_path, sphere):
    from conftest import write_binary_stl

    (model_tree / "bad.stl").write_bytes(b"garbage" * 30)
    w = scanned_window
    with qtbot.waitSignal(w.source_page.scanned, timeout=20_000):
        w.source_page.start_scan()
    c = w.convert_page
    c.refresh_plan()
    with qtbot.waitSignal(c.finished, timeout=120_000) as sig:
        c.start_button.click()
    assert sig.args[0]["failed"] == 1 and w.journal_page.retry_failed_button.isEnabled()
    w.journal_page.export_to(tmp_path / "journal.csv")
    assert len((tmp_path / "journal.csv").read_text(encoding="utf-8-sig").splitlines()) == 7
    write_binary_stl(model_tree / "bad.stl", sphere)
    with qtbot.waitSignal(c.finished, timeout=120_000) as sig:
        w.journal_page.retry_failed_button.click()
    assert sig.args[0]["failed"] == 0 and sig.args[0]["done"] == 6


def test_all_pages_retranslate(qtbot, scanned_window):
    w = scanned_window
    w.projection_page.refresh_instant()
    w.convert_page.refresh_plan()
    fr = visible_texts(w)
    w.set_language("en")
    en = visible_texts(w)
    assert len(fr) == len(en) > 60
    pairs = [(a, b) for a, b in zip(fr, en) if a.strip() and any(ch.isalpha() for ch in a)]
    changed = sum(1 for a, b in pairs if a != b)
    assert changed >= 0.85 * len(pairs), [a for a, b in pairs if a == b]
    w.set_language("fr")
    assert visible_texts(w) == fr


def test_no_raw_translation_key_on_screen(qtbot, scanned_window):
    keys = all_keys("fr")
    shown = [t for t in visible_texts(scanned_window) if t in keys]
    assert shown == []


def test_language_menu(qtbot, window):
    assert window.language_actions["fr"].isChecked()
    window.language_actions["en"].trigger()
    assert window.language_actions["en"].isChecked() and window.windowTitle() == tr("gui.title")
    assert window.steps.item(1).text().endswith("Settings")


def test_launch_arguments_and_direction():
    from pathlib import Path

    from dracoconv.gui.launch import infer_direction, parse

    assert parse(["--decode", "a.drc", "", "b.drc"]) == ("decode", [Path("a.drc"), Path("b.drc")])
    assert parse(["x.stl"]) == (None, [Path("x.stl")])
    assert infer_direction([Path("a.DRC"), Path("b.drc")]) == "decode"
    assert infer_direction([Path("a.drc"), Path("b.stl")]) == "encode"
    assert infer_direction([Path("dossier")]) == "encode"


def test_open_paths_sets_direction_and_scans_once(qtbot, window, model_tree):
    window.open_paths([model_tree], "decode")
    assert window.source_page.direction_combo.currentData() == "decode"
    window.open_paths([model_tree / "missing.drc"], "decode")
    assert len(window.source_page.state.roots) == 2
    with qtbot.waitSignal(window.source_page.scanned, timeout=20_000):
        pass


def test_drop_on_window_adds_paths(qtbot, window, model_tree):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    def drop(mime):
        event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier)
        window.dropEvent(event)
        return event.isAccepted()

    text_only = QMimeData()
    text_only.setText("pas un fichier")
    assert not drop(text_only)
    assert window.source_page.state.roots == []

    files = QMimeData()
    files.setUrls([QUrl.fromLocalFile(str(model_tree)), QUrl("https://example.com/x.stl")])
    assert drop(files)
    assert len(window.source_page.state.roots) == 1
    with qtbot.waitSignal(window.source_page.scanned, timeout=20_000):
        pass


def test_taskbar_progress_and_notification(qtbot, window, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon

    from dracoconv.gui.taskbar import ERROR, TaskbarProgress

    window.show()
    hwnd = int(window.winId())
    bar = TaskbarProgress()
    bar.set_value(hwnd, 3, 10)  # ne doit rien lever, même sans barre des tâches
    bar.set_state(hwnd, ERROR)
    bar.clear(hwnd)

    shown = []
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda self, *args: shown.append(args))
    window._notify({"done": 3, "failed": 1, "skipped": 2, "bytes_before": 3 << 20, "bytes_after": 1 << 20})
    if QSystemTrayIcon.isSystemTrayAvailable():
        title, body = shown[0][:2]
        assert title == tr("gui.notify.finished")
        assert "3" in body and "1" in body and "2" in body
        assert tr("gui.notify.saved", size="").split(":")[0] in body
    window._batch_progress(-1, 0)
    window._batch_progress(2, 4)


def test_second_launch_forwards_to_the_first(tmp_path):
    import uuid
    from pathlib import Path

    from dracoconv.gui.launch import Channel, forward

    address, key = rf"\\.\pipe\dracoconv-test-{uuid.uuid4().hex}", b"test"
    channel = Channel(address, key)
    try:
        assert forward(address, key, "encode", [tmp_path / "a.stl", tmp_path / "b.obj"])
        assert channel.requests.get(timeout=5) == ("encode", [tmp_path / "a.stl", tmp_path / "b.obj"])
        assert not forward(address, b"wrong key", "encode", [tmp_path]) or channel.requests.empty()
    finally:
        channel.close()
    assert not forward(rf"\\.\pipe\dracoconv-test-{uuid.uuid4().hex}", key, None, [Path("x")])
