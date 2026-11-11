"""Étape 2 : réglages d'encodage, chacun expliqué."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from ...engine import CliEngine, DracoPyEngine
from ...i18n import format_number, tr
from ...params import CATALOG
from ...quality import bits_for_tolerance, quantization_step_mm, theoretical_error_mm
from ...settings import PROFILES, EncodeSettings, save_profile, user_profiles
from ..param_panel import HelpPanel, ParamRow

_TYPICAL_EXTENT_MM = 100.0
_ENGINE_SUPPORT = {"dracopy": DracoPyEngine.supports, "reference": CliEngine.supports}
_BITS_OF_ATTRIBUTE = {"texcoord_bits": "texcoord", "normal_bits": "normal", "generic_bits": "generic"}
#: Réglages que seul le moteur de référence honore, incompatibles avec « conserver l'ordre ».
_REFERENCE_ONLY = ("metadata", "preserve_polygons", "generic_bits")


class SettingsPage(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.paths: list[Path] = []
        self._extent: float | None = None
        self.rows: dict[str, ParamRow] = {}

        self.profile_label = QLabel()
        self.profile_combo = QComboBox()
        self.save_profile_button = QPushButton()
        self.engine_label = QLabel()
        self.engine_combo = QComboBox()
        for data in (None, "dracopy", "reference"):
            self.engine_combo.addItem("", data)
        top = QHBoxLayout()
        top.addWidget(self.profile_label)
        top.addWidget(self.profile_combo, 1)
        top.addWidget(self.save_profile_button)
        top.addSpacing(24)
        top.addWidget(self.engine_label)
        top.addWidget(self.engine_combo, 1)

        self.decode_note = QLabel()
        self.decode_note.setWordWrap(True)
        self.decode_note.hide()

        rows_host = QWidget()
        rows_layout = QVBoxLayout(rows_host)
        for spec in CATALOG.values():
            row = ParamRow(spec)
            row.valueChanged.connect(self._row_edited)
            row.helpRequested.connect(self._show_help)
            self.rows[spec.id] = row
            rows_layout.addWidget(row)
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            rows_layout.addWidget(line)
        rows_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(rows_host)
        self.params_group = QGroupBox()
        QVBoxLayout(self.params_group).addWidget(scroll)

        self.help_panel = HelpPanel()
        self.help_group = QGroupBox()
        QVBoxLayout(self.help_group).addWidget(self.help_panel)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.params_group)
        splitter.addWidget(self.help_group)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self.command_label = QLabel()
        self.command_preview = QLineEdit()
        self.command_preview.setReadOnly(True)
        self.copy_button = QPushButton()
        bottom = QHBoxLayout()
        bottom.addWidget(self.command_label)
        bottom.addWidget(self.command_preview, 1)
        bottom.addWidget(self.copy_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.decode_note)
        layout.addWidget(splitter, 1)
        layout.addLayout(bottom)

        self.profile_combo.currentIndexChanged.connect(self._profile_chosen)
        self.engine_combo.currentIndexChanged.connect(self._engine_chosen)
        self.save_profile_button.clicked.connect(self._ask_profile_name)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.command_line()))

        self._fill_profiles("lossless")
        self.retranslate()

    # -- valeurs -------------------------------------------------------------------------------

    def settings(self) -> EncodeSettings:
        return EncodeSettings(**{pid: row.value() for pid, row in self.rows.items()})

    def engine(self) -> str | None:
        return self.engine_combo.currentData()

    def set_settings(self, settings: EncodeSettings) -> None:
        for pid, row in self.rows.items():
            row.load(getattr(settings, pid))
        self._select_profile(self._matching_profile(settings))
        self._refresh()
        self.changed.emit()

    def set_reference_extent(self, extent_mm: float | None) -> None:
        """Taille de modèle servant d'exemple pour l'effet concret des réglages."""
        self._extent = extent_mm
        self._update_effects()

    # -- profils -------------------------------------------------------------------------------

    def _all_profiles(self) -> dict[str, EncodeSettings]:
        return {**PROFILES, **user_profiles()}

    def _matching_profile(self, settings: EncodeSettings) -> str:
        return next((name for name, s in self._all_profiles().items() if s == settings), "custom")

    def _fill_profiles(self, selected: str) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for name in PROFILES:
            self.profile_combo.addItem(tr(f"profile.{name}"), name)
        for name in user_profiles():
            self.profile_combo.addItem(name, name)
        self.profile_combo.addItem(tr("profile.custom"), "custom")
        index = self.profile_combo.findData(selected)
        self.profile_combo.setCurrentIndex(index if index >= 0 else self.profile_combo.findData("custom"))
        self.profile_combo.blockSignals(False)

    def _select_profile(self, name: str) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentIndex(self.profile_combo.findData(name))
        self.profile_combo.blockSignals(False)

    def _profile_chosen(self, _index: int) -> None:
        name = self.profile_combo.currentData()
        profile = self._all_profiles().get(name)
        if profile is None:
            return
        for pid, row in self.rows.items():
            row.load(getattr(profile, pid))
        self._refresh()
        self.changed.emit()

    def save_profile_as(self, name: str) -> None:
        save_profile(name, self.settings())
        self._fill_profiles(name.strip())

    def _ask_profile_name(self) -> None:
        name, accepted = QInputDialog.getText(self, tr("gui.settings.save_profile"), tr("gui.settings.profile_name"))
        if accepted and name.strip():
            try:
                self.save_profile_as(name)
            except ValueError as exc:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, tr("gui.error.title"), str(exc))

    # -- réactions -----------------------------------------------------------------------------

    def _row_edited(self) -> None:
        self._select_profile(self._matching_profile(self.settings()))
        self._refresh()
        self.changed.emit()

    def _engine_chosen(self, _index: int) -> None:
        self._refresh()
        self.changed.emit()

    def _show_help(self, param_id: str) -> None:
        self.help_panel.show_param(param_id)

    def _refresh(self) -> None:
        self._update_states()
        self._update_effects()
        self.command_preview.setText(self.command_line())

    def _update_states(self) -> None:
        engine = self.engine()
        defaults = EncodeSettings()
        if engine:  # un réglage que le moteur imposé ne sait pas faire revient à sa valeur par défaut
            for pid, row in self.rows.items():
                if pid != "tolerance_mm" and pid not in _ENGINE_SUPPORT[engine] and row.value() != getattr(defaults, pid):
                    row.load(getattr(defaults, pid))
        settings = self.settings()
        for pid, row in self.rows.items():
            reason = None
            is_default = getattr(settings, pid) == getattr(defaults, pid)
            if pid == "position_bits" and settings.tolerance_mm is not None:
                reason = tr("param.disabled.tolerance_active")
            elif pid in _BITS_OF_ATTRIBUTE and _BITS_OF_ATTRIBUTE[pid] in settings.skip_attributes:
                reason = tr("param.disabled.attribute_skipped")
            elif engine and pid != "tolerance_mm" and pid not in _ENGINE_SUPPORT[engine]:
                reason = tr("param.disabled.engine")
            elif engine is None and is_default:
                if pid == "preserve_order":
                    active = next(
                        (p for p in _REFERENCE_ONLY if getattr(settings, p) != getattr(defaults, p)), None)
                    if active:
                        reason = tr("param.disabled.conflict", other=CATALOG[active].label())
                elif pid in _REFERENCE_ONLY and settings.preserve_order:
                    reason = tr("param.disabled.conflict", other=CATALOG["preserve_order"].label())
            row.set_disabled_reason(reason)

    def _update_effects(self) -> None:
        settings = self.settings()
        extent = self._extent or _TYPICAL_EXTENT_MM
        extent_text = format_number(extent, 0)
        bits_text = tolerance_text = ""
        if settings.tolerance_mm is not None:
            bits = bits_for_tolerance(extent, settings.tolerance_mm)
            key = "gui.effect.tolerance" if bits else "gui.effect.tolerance_lossless"
            tolerance_text = tr(key, extent=extent_text, bits=bits)
        elif settings.position_bits == 0:
            bits_text = tr("gui.effect.lossless")
        else:
            bits = settings.position_bits
            bits_text = tr(
                "gui.effect.bits", bits=bits, extent=extent_text,
                step=format_number(quantization_step_mm(extent, bits), 3 if bits <= 16 else 6),
                error=format_number(theoretical_error_mm(extent, bits), 4 if bits <= 16 else 7),
            )
        self.rows["position_bits"].effect.setText(bits_text)
        self.rows["tolerance_mm"].effect.setText(tolerance_text)

    # -- commande équivalente ------------------------------------------------------------------

    def command_line(self) -> str:
        settings, defaults = self.settings(), EncodeSettings()
        parts = ["dracoconv", "encode"]
        parts += [f'"{p}"' for p in self.paths] or ["<dossier>"]
        for spec in CATALOG.values():
            value = getattr(settings, spec.id)
            if value == getattr(defaults, spec.id):
                continue
            if spec.type == "bool":
                parts.append(spec.cli_flag)
            elif spec.type == "set":
                parts += [spec.cli_flag, ",".join(sorted(value)) or "none"]
            else:
                parts += [spec.cli_flag, f"{value:g}"]
        if self.engine():
            parts += ["--engine", self.engine()]
        return " ".join(parts)

    # -- langue --------------------------------------------------------------------------------

    def retranslate(self) -> None:
        self.profile_label.setText(tr("gui.settings.profile"))
        self.save_profile_button.setText(tr("gui.settings.save_profile"))
        self.engine_label.setText(tr("gui.settings.engine"))
        for index, key in enumerate(("auto", "dracopy", "reference")):
            self.engine_combo.setItemText(index, tr(f"gui.settings.engine.{key}"))
        self.engine_combo.setToolTip(tr("gui.settings.engine.tooltip"))
        self.decode_note.setText(tr("gui.settings.decode_note"))
        self.params_group.setTitle(tr("gui.settings.params"))
        self.help_group.setTitle(tr("gui.settings.help"))
        self.command_label.setText(tr("gui.settings.command"))
        self.copy_button.setText(tr("gui.settings.copy_command"))
        self._fill_profiles(self.profile_combo.currentData() or "custom")
        for row in self.rows.values():
            row.retranslate()
        self.help_panel.retranslate()
        self._refresh()
