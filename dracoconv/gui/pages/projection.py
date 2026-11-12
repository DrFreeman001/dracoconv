"""Étape 3 : gain de place projeté et perte de qualité."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QLogValueAxis, QValueAxis
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...estimate import Projection, instant, sampled
from ...i18n import format_number, format_size, tr
from ...quality import MAX_BITS, REFERENCE_MARKS_MM, bits_for_tolerance, theoretical_error_mm
from ...sampling import QualitySample, quality_sample
from ...settings import EncodeSettings
from ..state import AppState
from ..workers import Worker
from ..activity import ActivityBar

_TYPICAL_EXTENT_MM = 100.0
_KIND_ORDER = ("stl", "obj", "ply", "3mf", "zip")
_MARK_COLORS = {"layer_height": "#7c3aed", "nozzle": "#b45309", "cad_tolerance": "#6b7280"}


def _sample_task(inventory, settings, engine, per_class, budget, report=None, stop=None):
    """Projection par échantillon, puis mesure de qualité ; exécuté hors du fil de l'interface."""
    projection = sampled(inventory, settings, per_class=per_class, time_budget_s=budget,
                         on_progress=lambda done, total: report(("progress", done, total)), stop=stop)
    report(("projection", projection))
    return quality_sample(inventory, settings, engine, stop=stop)


class ProjectionPage(QWidget):
    sampled = Signal(object)
    quality_ready = Signal(object)

    def __init__(self, state: AppState, get_settings: Callable[[], EncodeSettings],
                 get_engine: Callable[[], str | None], parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._get_settings, self._get_engine = get_settings, get_engine
        self._worker: Worker | None = None
        self._quality: QualitySample | None = None
        self._progress: tuple[int, int] | None = None

        self.gain_group = QGroupBox()
        self.current_title, self.current_label = QLabel(), QLabel()
        self.projected_title, self.projected_label = QLabel(), QLabel()
        self.saved_title, self.saved_label = QLabel(), QLabel()
        self.margin_title, self.margin_label = QLabel(), QLabel()
        self.method_title, self.method_label = QLabel(), QLabel()
        self.saved_label.setStyleSheet("font-weight: 700; font-size: 15pt;")
        form = QFormLayout()
        for title, value in ((self.current_title, self.current_label), (self.projected_title, self.projected_label),
                             (self.saved_title, self.saved_label), (self.margin_title, self.margin_label),
                             (self.method_title, self.method_label)):
            form.addRow(title, value)
        self.kind_table = QTableWidget(0, 4)
        self.kind_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.kind_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.kind_table.verticalHeader().hide()
        self.kind_table.setMaximumHeight(120)
        self.no_gain_label = QLabel()
        self.note_label = QLabel()
        self.note_label.setWordWrap(True)
        self.sample_button = QPushButton()
        self.per_class_title, self.per_class_spin = QLabel(), QSpinBox()
        self.per_class_spin.setRange(1, 500)
        self.per_class_spin.setValue(12)
        self.budget_title, self.budget_spin = QLabel(), QSpinBox()
        self.budget_spin.setRange(1, 3600)
        self.budget_spin.setValue(60)
        self.progress_label = QLabel()
        sample_row = QHBoxLayout()
        for widget in (self.sample_button, self.per_class_title, self.per_class_spin, self.budget_title,
                       self.budget_spin):
            sample_row.addWidget(widget)
        sample_row.addWidget(self.progress_label, 1)
        gain_layout = QVBoxLayout(self.gain_group)
        gain_layout.addLayout(form)
        gain_layout.addWidget(self.kind_table)
        gain_layout.addWidget(self.no_gain_label)
        gain_layout.addWidget(self.note_label)
        gain_layout.addLayout(sample_row)

        self.quality_group = QGroupBox()
        self.theoretical_title, self.theoretical_label = QLabel(), QLabel()
        self.measured_title, self.measured_label = QLabel(), QLabel()
        for label in (self.theoretical_label, self.measured_label):
            label.setWordWrap(True)
        self.marks_label = QLabel()
        self.marks_label.setWordWrap(True)
        quality_form = QFormLayout()
        quality_form.addRow(self.theoretical_title, self.theoretical_label)
        quality_form.addRow(self.measured_title, self.measured_label)
        self.chart = QChartView(QChart())
        self.chart.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart.setMinimumHeight(260)
        quality_layout = QVBoxLayout(self.quality_group)
        quality_layout.addLayout(quality_form)
        quality_layout.addWidget(self.marks_label)
        quality_layout.addWidget(self.chart, 1)

        self.activity = ActivityBar()
        layout = QVBoxLayout(self)
        layout.addWidget(self.activity)
        layout.addWidget(self.gain_group)
        layout.addWidget(self.quality_group, 1)
        self.sample_button.clicked.connect(self.start_sampling)
        self.retranslate()

    # -- gain ----------------------------------------------------------------------------------

    def settings_changed(self) -> None:
        """Les réglages ont changé : la projection et la mesure précédentes ne valent plus."""
        self.state.projection = None
        self._quality = None
        self.refresh_instant()

    def refresh_instant(self) -> None:
        inventory = self.state.inventory
        if inventory is not None and self.state.direction == "encode":
            if self.state.projection is None:
                self.state.projection = instant(inventory, self._get_settings())
        self._show()

    def start_sampling(self) -> None:
        inventory = self.state.inventory
        if self._worker is not None or inventory is None or self.state.direction != "encode":
            return
        self.activity.start()
        self.sample_button.setEnabled(False)
        self._progress = (0, 0)
        self._worker = Worker(_sample_task, inventory, self._get_settings(), self._get_engine(),
                              self.per_class_spin.value(), float(self.budget_spin.value()),
                              progress_arg="report", stop_arg="stop", parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_quality)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()
        self._show_progress()

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()
            self._worker.wait()

    def _on_progress(self, message: tuple) -> None:
        if message[0] == "progress":
            self._progress = (message[1], message[2])
            self._show_progress()
        elif message[0] == "projection":
            self.state.projection = message[1]
            self._progress = None
            self._show()
            self.progress_label.setText(tr("gui.projection.measuring"))
            self.sampled.emit(message[1])

    def _on_quality(self, quality: QualitySample) -> None:
        self._worker = None
        self.activity.stop()
        self.sample_button.setEnabled(True)
        self._quality = quality
        if quality.files:
            self.state.reference_extent = quality.median_extent_mm
        self._show()
        self.quality_ready.emit(quality)

    def _on_failed(self, message: str) -> None:
        self._worker = None
        self._progress = None
        self.activity.stop()
        self.sample_button.setEnabled(True)
        self.progress_label.setText(message)

    def _show_progress(self) -> None:
        if self._progress is None:
            self.progress_label.setText("")
        else:
            self.progress_label.setText(tr("gui.projection.sampling", done=self._progress[0], total=self._progress[1]))

    # -- affichage -----------------------------------------------------------------------------

    def _show(self) -> None:
        self._show_progress()
        self._show_projection(self.state.projection)
        self._show_quality()
        self._draw_chart()

    def _show_projection(self, projection: Projection | None) -> None:
        self.kind_table.setRowCount(0)
        self.no_gain_label.setText("")
        if self.state.direction != "encode":
            self.note_label.setText(tr("gui.projection.decode_note"))
        elif self.state.inventory is None:
            self.note_label.setText(tr("gui.projection.no_inventory"))
        else:
            self.note_label.setText("")
        if projection is None or self.state.direction != "encode":
            for label in (self.current_label, self.projected_label, self.saved_label, self.margin_label,
                          self.method_label):
                label.setText("")
            return
        self.current_label.setText(format_size(projection.current_bytes))
        self.projected_label.setText(format_size(projection.projected_bytes))
        self.saved_label.setText(f"{format_size(projection.saved_bytes)} — {format_number(projection.saved_pct, 1)} %")
        half = (projection.high_bytes - projection.low_bytes) / 2
        self.margin_label.setText(
            f"± {format_size(half)} ("
            + tr("cli.estimate.range", low=format_size(projection.low_bytes), high=format_size(projection.high_bytes))
            + ")")
        if projection.method == "sampled":
            self.method_label.setText(tr("method.sampled", n=projection.sampled_files))
        else:
            self.method_label.setText(tr("method.instant"))
        by_kind = {k.value: v for k, v in projection.by_kind.items()}
        for kind in [k for k in _KIND_ORDER if k in by_kind]:
            row = self.kind_table.rowCount()
            self.kind_table.insertRow(row)
            values = (tr(f"kind.{kind}"), str(by_kind[kind].files), format_size(by_kind[kind].current_bytes),
                      format_size(by_kind[kind].projected_bytes))
            for column, text in enumerate(values):
                self.kind_table.setItem(row, column, QTableWidgetItem(text))
        if projection.no_gain:
            self.no_gain_label.setText(tr("gui.projection.no_gain", n=len(projection.no_gain)))

    def _extent(self) -> float:
        if self._quality is not None and self._quality.curve_extent_mm:
            return self._quality.curve_extent_mm
        return self.state.reference_extent or _TYPICAL_EXTENT_MM

    def _show_quality(self) -> None:
        settings = self._get_settings()
        extent = self.state.reference_extent or _TYPICAL_EXTENT_MM
        bits = settings.position_bits
        if settings.tolerance_mm is not None:
            bits = bits_for_tolerance(extent, settings.tolerance_mm)
        if bits == 0:
            self.theoretical_label.setText(tr("quality.identical"))
        else:
            error = theoretical_error_mm(extent, bits)
            self.theoretical_label.setText(tr(
                "gui.projection.theoretical_value", error=format_number(error, 4 if error >= 0.0001 else 7),
                extent=format_number(extent, 0), bits=bits))
        quality = self._quality
        if quality is None or quality.files == 0:
            self.measured_label.setText(tr("gui.projection.not_measured"))
        elif quality.identical:
            self.measured_label.setText(tr("gui.projection.measured_identical", n=quality.files))
        else:
            self.measured_label.setText(tr(
                "gui.projection.measured_value", median=format_number(quality.median_error_mm, 5),
                worst=format_number(quality.worst_error_mm, 5), n=quality.files, collapsed=quality.collapsed))
        marks = REFERENCE_MARKS_MM
        self.marks_label.setText(tr(
            "gui.projection.marks", layer=format_number(marks["layer_height"], 1),
            nozzle=format_number(marks["nozzle"], 1), cad=format_number(marks["cad_tolerance"], 2)))

    def _draw_chart(self) -> None:
        chart = QChart()
        dark = QApplication.palette().color(self.backgroundRole()).lightness() < 128
        if dark:
            chart.setTheme(QChart.ChartTheme.ChartThemeDark)
        chart.setTitle(tr("gui.chart.title"))
        bits_axis = QValueAxis()
        bits_axis.setRange(8, MAX_BITS)
        bits_axis.setTickCount(12)
        bits_axis.setLabelFormat("%d")
        bits_axis.setTitleText(tr("gui.chart.bits"))
        error_axis = QLogValueAxis()
        error_axis.setBase(10)
        error_axis.setRange(1e-7, 1.0)
        error_axis.setLabelFormat("%g")
        error_axis.setTitleText(tr("gui.chart.error_axis"))
        chart.addAxis(bits_axis, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(error_axis, Qt.AlignmentFlag.AlignLeft)

        def add(series: QLineSeries, axis) -> None:
            chart.addSeries(series)
            series.attachAxis(bits_axis)
            series.attachAxis(axis)

        extent = self._extent()
        theoretical = QLineSeries()
        theoretical.setName(tr("gui.chart.theoretical"))
        for bits in range(8, MAX_BITS + 1):
            theoretical.append(bits, theoretical_error_mm(extent, bits))
        add(theoretical, error_axis)
        for name, value in REFERENCE_MARKS_MM.items():
            mark = QLineSeries()
            mark.setName(f"{tr('gui.chart.mark.' + name)} ({format_number(value, 2)} mm)")
            mark.append(8, value)
            mark.append(MAX_BITS, value)
            color = {"layer_height": "#b69aff", "nozzle": "#efb45e", "cad_tolerance": "#b4becd"}[name] if dark else _MARK_COLORS[name]
            pen = QPen(QColor(color))
            pen.setWidthF(1.5)
            pen.setStyle(Qt.PenStyle.DashLine)
            mark.setPen(pen)
            add(mark, error_axis)
        quality = self._quality
        if quality is not None and quality.curve:
            measured = QLineSeries()
            measured.setName(tr("gui.chart.measured"))
            measured.setPointsVisible(True)
            for point in quality.curve:
                measured.append(point.bits, max(point.max_error_mm, 1e-7))
            add(measured, error_axis)
            size_axis = QValueAxis()
            size_axis.setRange(0, max(quality.curve_size_pct) * 1.1)
            size_axis.setLabelFormat("%.1f")
            size_axis.setTitleText(tr("gui.chart.size_axis"))
            chart.addAxis(size_axis, Qt.AlignmentFlag.AlignRight)
            size = QLineSeries()
            size.setName(tr("gui.chart.size"))
            size.setColor(QColor("#2e9e5b"))
            for point, pct in zip(quality.curve, quality.curve_size_pct):
                size.append(point.bits, pct)
            add(size, size_axis)
        old = self.chart.chart()
        self.chart.setChart(chart)
        old.deleteLater()

    # -- langue --------------------------------------------------------------------------------

    def retranslate(self) -> None:
        self.gain_group.setTitle(tr("gui.projection.gain"))
        self.current_title.setText(tr("gui.projection.current"))
        self.projected_title.setText(tr("gui.projection.projected"))
        self.saved_title.setText(tr("gui.projection.saved"))
        self.margin_title.setText(tr("gui.projection.margin"))
        self.method_title.setText(tr("gui.projection.method"))
        self.sample_button.setText(tr("gui.projection.sample"))
        self.per_class_title.setText(tr("gui.projection.per_class"))
        self.budget_title.setText(tr("gui.projection.budget"))
        self.quality_group.setTitle(tr("gui.projection.quality"))
        self.theoretical_title.setText(tr("gui.projection.theoretical"))
        self.measured_title.setText(tr("gui.projection.measured"))
        self.kind_table.setHorizontalHeaderLabels(
            [tr("cli.col.kind"), tr("cli.col.files"), tr("cli.col.size"), tr("cli.col.projected")])
        self._show()
