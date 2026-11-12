"""Application-wide colour themes, including the native system preference."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES = ('system', 'light', 'dark')


def apply_theme(name: str, system_scheme=None) -> None:
    app = QApplication.instance()
    if name not in THEMES:
        name = 'system'
    scheme = {'system': Qt.ColorScheme.Unknown, 'light': Qt.ColorScheme.Light, 'dark': Qt.ColorScheme.Dark}[name]
    if system_scheme is None:
        app.styleHints().setColorScheme(scheme)
    app.setStyle('Fusion')
    effective_scheme = system_scheme if system_scheme is not None else app.styleHints().colorScheme()
    dark = name == 'dark' or (name == 'system' and effective_scheme == Qt.ColorScheme.Dark)
    palette = QPalette()
    colors = {
        'Window': '#24272d' if dark else '#f3f4f6',
        'WindowText': '#f1f3f5' if dark else '#20242a',
        'Base': '#191c21' if dark else '#ffffff',
        'AlternateBase': '#2e333b' if dark else '#e9edf2',
        'Text': '#f1f3f5' if dark else '#20242a',
        'Button': '#353b45' if dark else '#e4e8ee',
        'ButtonText': '#f1f3f5' if dark else '#20242a',
        'ToolTipBase': '#353b45' if dark else '#ffffff',
        'ToolTipText': '#f1f3f5' if dark else '#20242a',
        'Highlight': '#367bc1', 'HighlightedText': '#ffffff',
        'Link': '#86bfff' if dark else '#1558a6',
        'PlaceholderText': '#a5acb7' if dark else '#626b78',
    }
    for role, value in colors.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(value))
    for role in ('Text', 'WindowText', 'ButtonText'):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role), QColor('#89919e' if dark else '#747d89'))
    app.setPalette(palette)
