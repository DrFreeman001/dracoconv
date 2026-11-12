from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication
from dracoconv.config import load_prefs
from dracoconv.gui.main_window import MainWindow
from dracoconv.i18n import set_language


def test_theme_persists_and_switches(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    w = MainWindow(); qtbot.addWidget(w)
    w.set_theme('dark')
    p = QApplication.palette()
    assert p.color(QPalette.ColorRole.Window).lightness() < p.color(QPalette.ColorRole.WindowText).lightness()
    assert load_prefs()['theme'] == 'dark'
    other = MainWindow(); qtbot.addWidget(other)
    assert other.theme_actions['dark'].isChecked()
    w.set_language('en')
    assert w.theme_actions['dark'].text() == 'Dark'
    w.set_theme('light')
    p = QApplication.palette()
    assert p.color(QPalette.ColorRole.Window).lightness() > p.color(QPalette.ColorRole.WindowText).lightness()
    w.set_theme('system'); set_language('fr')


def test_activity_stops_on_failures(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    w = MainWindow(); qtbot.addWidget(w)
    for page, handler in [(w.source_page, '_scan_failed'), (w.projection_page, '_on_failed'), (w.convert_page, '_on_failed')]:
        page.activity.start()
        assert not page.activity.isHidden()
        assert page.activity.maximum() == 0
        getattr(page, handler)('test error')
        assert page.activity.isHidden()


def test_source_activity_lifecycle(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path/'prefs'))
    w = MainWindow(); qtbot.addWidget(w)
    w.source_page.add_root(tmp_path)
    with qtbot.waitSignal(w.source_page.scanned, timeout=10000):
        w.source_page.start_scan()
        assert not w.source_page.activity.isHidden()
    assert w.source_page.activity.isHidden()

def test_conversion_activity_and_total(qtbot, monkeypatch, tmp_path, model_tree):
    monkeypatch.setenv('APPDATA', str(tmp_path/'prefs'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'local'))
    w = MainWindow(); qtbot.addWidget(w)
    w.convert_page.workers_spin.setValue(1)
    w.source_page.add_root(model_tree)
    with qtbot.waitSignal(w.source_page.scanned, timeout=10000):
        w.source_page.start_scan()
    c = w.convert_page
    with qtbot.waitSignal(c.finished, timeout=30000) as result:
        c.start()
        assert not c.activity.isHidden()
        assert c.progress.value() == 0
    assert result.args[0]['failed'] == 0
    assert c.activity.isHidden()
    assert c.progress.value() == c.progress.maximum()


def test_sampling_activity_through_quality(qtbot, monkeypatch, tmp_path, model_tree):
    monkeypatch.setenv('APPDATA', str(tmp_path/'prefs'))
    w = MainWindow(); qtbot.addWidget(w)
    w.source_page.add_root(model_tree)
    with qtbot.waitSignal(w.source_page.scanned, timeout=10000):
        w.source_page.start_scan()
    p = w.projection_page
    with qtbot.waitSignal(p.quality_ready, timeout=30000):
        p.start_sampling()
        assert not p.activity.isHidden()
    assert p.activity.isHidden()

def test_chart_matches_dark_theme(qtbot, monkeypatch, tmp_path):
    from PySide6.QtCharts import QChart
    monkeypatch.setenv('APPDATA', str(tmp_path))
    w = MainWindow(); qtbot.addWidget(w)
    w.set_theme('dark')
    assert w.projection_page.chart.chart().theme() == QChart.ChartTheme.ChartThemeDark
    w.set_theme('light')
    assert w.projection_page.chart.chart().theme() == QChart.ChartTheme.ChartThemeLight
    w.set_theme('system')

def test_system_theme_tracks_changes(qtbot, monkeypatch, tmp_path):
    from PySide6.QtCore import Qt
    monkeypatch.setenv('APPDATA', str(tmp_path))
    w = MainWindow(); qtbot.addWidget(w)
    w.set_theme('system')
    QApplication.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    assert QApplication.palette().color(QPalette.Window).lightness() < 128
    QApplication.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
    assert QApplication.palette().color(QPalette.Window).lightness() > 128
    w.set_theme('dark')
    QApplication.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
    assert QApplication.palette().color(QPalette.Window).lightness() < 128
    w.set_theme('system')


def test_declared_qt_supports_theme_api():
    import tomllib
    from pathlib import Path
    project = tomllib.loads((Path(__file__).parents[1]/'pyproject.toml').read_text(encoding='utf-8'))
    assert 'PySide6>=6.8' in project['project']['dependencies']
