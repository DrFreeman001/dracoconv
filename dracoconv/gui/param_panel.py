"""Une ligne par paramètre (libellé, contrôle, explication, effet concret) et le panneau d'aide détaillée."""
from __future__ import annotations

import html

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QSpinBox, QTextBrowser, QToolButton, QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..params import CATALOG, HELP_SECTIONS, ParamSpec

_DEFAULT_TOLERANCE_MM = 0.01


class ParamRow(QWidget):
    """Un paramètre : son nom, son contrôle, une phrase d'explication toujours visible, son effet concret."""

    valueChanged = Signal()
    helpRequested = Signal(str)

    def __init__(self, spec: ParamSpec, parent: QWidget | None = None):
        super().__init__(parent)
        self.spec = spec
        self._loading = False
        self._disabled_reason: str | None = None
        self.label = QLabel()
        self.label.setStyleSheet("font-weight: 600;")
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: palette(placeholder-text);")
        self.effect = QLabel()
        self.effect.setWordWrap(True)
        self.effect.setStyleSheet("font-style: italic;")
        self.help_button = QToolButton()
        self.help_button.setText("?")
        self.help_button.setAutoRaise(True)
        self.help_button.clicked.connect(lambda: self.helpRequested.emit(self.spec.id))
        self.editor = self._build_editor()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 6, 0, 6)
        grid.addWidget(self.label, 0, 0)
        grid.addWidget(self.editor, 0, 1, alignment=Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.help_button, 0, 2)
        grid.addWidget(self.hint, 1, 0, 1, 3)
        grid.addWidget(self.effect, 2, 0, 1, 3)
        grid.setColumnStretch(0, 1)
        self.retranslate()

    # -- construction du contrôle selon le type du paramètre --------------------------------

    def _build_editor(self) -> QWidget:
        spec = self.spec
        if spec.type == "int":
            editor = QSpinBox()
            editor.setRange(int(spec.minimum), int(spec.maximum))
            editor.setValue(int(spec.default))
            editor.valueChanged.connect(self._edited)
            self._watch(editor)
            return editor
        if spec.type == "bool":
            editor = QCheckBox()
            editor.setChecked(bool(spec.default))
            editor.toggled.connect(self._edited)
            self._watch(editor)
            return editor
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        if spec.type == "float":
            self.enable_box = QCheckBox()
            self.spin = QDoubleSpinBox()
            self.spin.setDecimals(4)
            self.spin.setRange(0.0001, float(spec.maximum))
            self.spin.setSingleStep(0.001)
            self.spin.setValue(_DEFAULT_TOLERANCE_MM)
            self.spin.setSuffix(" mm")
            self.spin.setEnabled(False)
            self.enable_box.toggled.connect(self.spin.setEnabled)
            self.enable_box.toggled.connect(self._edited)
            self.spin.valueChanged.connect(self._edited)
            row.addWidget(self.enable_box)
            row.addWidget(self.spin)
            self._watch(self.enable_box, self.spin)
        else:  # ensemble de choix
            self.choice_boxes: dict[str, QCheckBox] = {}
            for choice in spec.choices:
                box = QCheckBox()
                box.setChecked(choice in spec.default)
                box.toggled.connect(self._edited)
                row.addWidget(box)
                self.choice_boxes[choice] = box
                self._watch(box)
        return container

    def _watch(self, *widgets: QWidget) -> None:
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - API Qt
        if event.type() == QEvent.Type.FocusIn:
            self.helpRequested.emit(self.spec.id)
        return super().eventFilter(watched, event)

    def _edited(self, *_args) -> None:
        if self._loading:
            return
        self.helpRequested.emit(self.spec.id)
        self.valueChanged.emit()

    # -- valeur --------------------------------------------------------------------------------

    def value(self):
        spec = self.spec
        if spec.type == "int":
            return self.editor.value()
        if spec.type == "bool":
            return self.editor.isChecked()
        if spec.type == "float":
            return round(self.spin.value(), 4) if self.enable_box.isChecked() else None
        return frozenset(name for name, box in self.choice_boxes.items() if box.isChecked())

    def load(self, value) -> None:
        """Charge une valeur sans prévenir (chargement d'un profil)."""
        self._loading = True
        try:
            spec = self.spec
            if spec.type == "int":
                self.editor.setValue(int(value))
            elif spec.type == "bool":
                self.editor.setChecked(bool(value))
            elif spec.type == "float":
                self.enable_box.setChecked(value is not None)
                if value is not None:
                    self.spin.setValue(float(value))
            else:
                for name, box in self.choice_boxes.items():
                    box.setChecked(name in value)
        finally:
            self._loading = False

    def set_value(self, value) -> None:
        """Change la valeur comme le ferait l'utilisateur : l'aide suit et la page est prévenue."""
        self.load(value)
        self.helpRequested.emit(self.spec.id)
        self.valueChanged.emit()

    # -- état et textes ------------------------------------------------------------------------

    def set_disabled_reason(self, reason: str | None) -> None:
        self._disabled_reason = reason
        self.editor.setEnabled(reason is None)
        self._update_tooltip()

    def _update_tooltip(self) -> None:
        lines = [self.spec.tooltip(), tr("help.default", value=self.spec.default_text())]
        if self._disabled_reason:
            lines.append(self._disabled_reason)
        self.editor.setToolTip("\n".join(lines))
        self.label.setToolTip(self.spec.tooltip())

    def retranslate(self) -> None:
        self.label.setText(self.spec.label())
        self.hint.setText(self.spec.tooltip())
        self.help_button.setToolTip(tr("gui.settings.help_button"))
        if self.spec.type == "float":
            self.enable_box.setText(tr("gui.settings.enable"))
        elif self.spec.type == "set":
            for name, box in self.choice_boxes.items():
                box.setText(tr(f"attr.{name}"))
        self._update_tooltip()


class HelpPanel(QWidget):
    """Aide détaillée du paramètre en cours : toujours les mêmes rubriques, dans le même ordre."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.current_id: str = next(iter(CATALOG))
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)
        self.show_param(self.current_id)

    def show_param(self, param_id: str) -> None:
        if param_id not in CATALOG:
            return
        self.current_id = param_id
        spec = CATALOG[param_id]
        esc = lambda text: html.escape(str(text), quote=False)  # noqa: E731
        facts = [tr("help.default", value=spec.default_text())]
        if spec.minimum is not None:
            facts.append(tr("help.range", minimum=f"{spec.minimum:g}", maximum=f"{spec.maximum:g}"))
        if spec.draco_flag:
            facts.append(tr("help.draco_flag", flag=spec.draco_flag))
        facts.append(f"dracoconv : {spec.cli_flag}")
        parts = [f"<h3>{esc(spec.label())}</h3>", f"<p>{esc(spec.tooltip())}</p>"]
        parts.append("<p><i>" + "<br>".join(esc(f) for f in facts) + "</i></p>")
        sections = spec.help_sections()
        for name in HELP_SECTIONS:
            parts.append(f"<h4>{esc(tr('help.section.' + name))}</h4><p>{esc(sections[name])}</p>")
        self.browser.setHtml("".join(parts))

    def retranslate(self) -> None:
        self.show_param(self.current_id)
