from dataclasses import replace

import pytest
from PySide6.QtWidgets import QTextBrowser

from dracoconv.gui.main_window import MainWindow
from dracoconv.gui.pages.settings import SettingsPage
from dracoconv.i18n import set_language, tr, tr_in
from dracoconv.params import CATALOG
from dracoconv.settings import EncodeSettings, user_profiles


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    set_language("fr")
    yield
    set_language("fr")


def test_one_row_per_param(qtbot):
    page = SettingsPage()
    qtbot.addWidget(page)
    assert list(page.rows) == list(CATALOG)


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_each_row_explains_itself(qtbot, lang):
    set_language(lang)
    page = SettingsPage()
    qtbot.addWidget(page)
    for pid, row in page.rows.items():
        spec = CATALOG[pid]
        assert row.label.text() == spec.label() and row.hint.text() == spec.tooltip()
        assert spec.tooltip() in row.editor.toolTip() and spec.default_text() in row.editor.toolTip()
        assert row.help_button.toolTip()


def test_help_panel_follows_button(qtbot):
    page = SettingsPage()
    qtbot.addWidget(page)
    page.show()
    page.rows["normal_bits"].help_button.click()
    assert page.help_panel.current_id == "normal_bits"
    text = page.help_panel.findChild(QTextBrowser).toPlainText()
    assert CATALOG["normal_bits"].label() in text
    assert all(s in text for s in CATALOG["normal_bits"].help_sections().values())
    assert tr("help.section.quality") in text and "-qn" in text


def test_help_panel_follows_edit(qtbot):
    page = SettingsPage()
    qtbot.addWidget(page)
    page.rows["compression_level"].set_value(5)
    assert page.help_panel.current_id == "compression_level"


def test_help_panel_is_never_empty(qtbot):
    page = SettingsPage()
    qtbot.addWidget(page)
    assert page.help_panel.current_id in CATALOG
    assert page.help_panel.findChild(QTextBrowser).toPlainText().strip()


def test_language_switch_without_restart(qtbot):
    set_language("fr")
    w = MainWindow()
    qtbot.addWidget(w)
    assert w.settings_page.rows["position_bits"].label.text() == tr_in("fr", "param.position_bits.label")
    w.settings_page.rows["position_bits"].help_button.click()
    w.set_language("en")
    assert w.settings_page.rows["position_bits"].label.text() == tr_in("en", "param.position_bits.label")
    assert w.settings_page.rows["position_bits"].hint.text() == tr_in("en", "param.position_bits.tooltip")
    text = w.settings_page.help_panel.findChild(QTextBrowser).toPlainText()
    assert tr_in("en", "param.position_bits.help_what") in text
    assert w.windowTitle() == tr_in("en", "gui.title")


def test_concrete_effect_text(qtbot):
    set_language("fr")
    page = SettingsPage()
    qtbot.addWidget(page)
    page.set_reference_extent(180.0)
    page.set_settings(replace(EncodeSettings(), position_bits=14))
    effect = page.rows["position_bits"].effect.text()
    assert "0,011 mm" in effect and "180" in effect and "14" in effect
    page.set_settings(EncodeSettings())
    assert page.rows["position_bits"].effect.text() == tr("gui.effect.lossless")
    page.set_settings(replace(EncodeSettings(), tolerance_mm=0.01))
    assert "14 bits" in page.rows["tolerance_mm"].effect.text() and "180" in page.rows["tolerance_mm"].effect.text()


def test_effect_text_in_english_uses_a_point(qtbot):
    set_language("en")
    page = SettingsPage()
    qtbot.addWidget(page)
    page.set_reference_extent(180.0)
    page.set_settings(replace(EncodeSettings(), position_bits=14))
    assert "0.011 mm" in page.rows["position_bits"].effect.text()


def test_settings_roundtrip(qtbot):
    page = SettingsPage()
    qtbot.addWidget(page)
    s = replace(EncodeSettings(), position_bits=20, compression_level=5, skip_attributes=frozenset({"normal", "color"}),
                texcoord_bits=12, point_cloud=True)
    page.set_settings(s)
    assert page.settings() == s
    t = replace(EncodeSettings(), tolerance_mm=0.02, preserve_order=True, skip_attributes=frozenset())
    page.set_settings(t)
    assert page.settings() == t


def test_profiles(qtbot):
    page = SettingsPage()
    qtbot.addWidget(page)
    assert page.profile_combo.currentData() == "lossless"
    page.profile_combo.setCurrentIndex(page.profile_combo.findData("tolerance"))
    assert page.settings().tolerance_mm == 0.001
    page.profile_combo.setCurrentIndex(page.profile_combo.findData("fixed_bits"))
    assert page.settings().position_bits == 16 and page.settings().tolerance_mm is None
    page.rows["compression_level"].set_value(3)
    assert page.profile_combo.currentData() == "custom"


def test_save_user_profile_from_window(qtbot):
    page = SettingsPage()
    qtbot.addWidget(page)
    page.set_settings(replace(EncodeSettings(), position_bits=18))
    page.save_profile_as("mes figurines")
    assert page.profile_combo.findData("mes figurines") >= 0 and page.profile_combo.currentData() == "mes figurines"
    assert user_profiles()["mes figurines"].position_bits == 18
    again = SettingsPage()
    qtbot.addWidget(again)
    assert again.profile_combo.findData("mes figurines") >= 0


def test_disabled_param_says_why(qtbot):
    page = SettingsPage()
    qtbot.addWidget(page)
    page.set_settings(replace(EncodeSettings(), tolerance_mm=0.01))
    row = page.rows["position_bits"]
    assert not row.editor.isEnabled() and tr("param.disabled.tolerance_active") in row.editor.toolTip()
    page.set_settings(EncodeSettings())
    assert row.editor.isEnabled() and tr("param.disabled.tolerance_active") not in row.editor.toolTip()
    assert not page.rows["normal_bits"].editor.isEnabled()  # normales non enregistrées par défaut
    assert tr("param.disabled.attribute_skipped") in page.rows["normal_bits"].editor.toolTip()
    assert page.rows["texcoord_bits"].editor.isEnabled()


def test_forced_engine_disables_what_it_cannot_do(qtbot):
    page = SettingsPage()
    qtbot.addWidget(page)
    page.engine_combo.setCurrentIndex(page.engine_combo.findData("dracopy"))
    for pid in ("metadata", "preserve_polygons"):
        assert not page.rows[pid].editor.isEnabled()
        assert tr("param.disabled.engine") in page.rows[pid].editor.toolTip()
    page.engine_combo.setCurrentIndex(page.engine_combo.findData("reference"))
    assert not page.rows["preserve_order"].editor.isEnabled() and page.rows["metadata"].editor.isEnabled()
    assert page.engine() == "reference"
    page.engine_combo.setCurrentIndex(page.engine_combo.findData(None))
    assert page.rows["preserve_order"].editor.isEnabled() and page.engine() is None


def test_command_line_copy(qtbot):
    page = SettingsPage()
    qtbot.addWidget(page)
    assert page.command_line().startswith("dracoconv encode")
    page.set_settings(replace(EncodeSettings(), position_bits=14, skip_attributes=frozenset()))
    assert "--position-bits 14" in page.command_line() and "--skip none" in page.command_line()
    assert "--compression-level" not in page.command_line()
    assert page.command_preview.text() == page.command_line()


def test_changed_signal(qtbot):
    page = SettingsPage()
    qtbot.addWidget(page)
    with qtbot.waitSignal(page.changed, timeout=1000):
        page.rows["point_cloud"].set_value(True)
    assert page.settings().point_cloud is True
