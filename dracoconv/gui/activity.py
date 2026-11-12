"""Indeterminate activity indicator for operations without internal progress."""
from PySide6.QtWidgets import QProgressBar
from ..i18n import tr


class ActivityBar(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 0)
        self.setTextVisible(False)
        self.setMaximumHeight(10)
        self.hide()

    def start(self):
        self.setAccessibleName(tr('gui.activity'))
        self.setToolTip(tr('gui.activity'))
        self.show()

    def stop(self):
        self.hide()
