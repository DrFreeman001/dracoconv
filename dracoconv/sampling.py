"""Échantillon de qualité : écart réellement mesuré sur quelques modèles, et courbe par nombre de bits."""
from __future__ import annotations

import statistics
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .convert import VerifyError, encode_bytes
from .engine import EngineError, select_engine
from .io import MODEL_KINDS, load_mesh
from .mesh import MeshReadError
from .quality import CurvePoint, curve
from .scan import Inventory
from .settings import EncodeSettings

_CURVE_MAX_BYTES = 20 << 20  # la courbe encode le même fichier une vingtaine de fois
_SAMPLE_MAX_BYTES = 200 << 20


@dataclass
class QualitySample:
    files: int = 0
    identical: bool = True
    median_error_mm: float = 0.0
    worst_error_mm: float = 0.0
    collapsed: int = 0
    median_extent_mm: float = 0.0
    curve: list[CurvePoint] = field(default_factory=list)
    curve_size_pct: list[float] = field(default_factory=list)  # taille en % du fichier d'origine
    curve_extent_mm: float = 0.0
    curve_file: Path | None = None


def quality_sample(
    inv: Inventory,
    settings: EncodeSettings,
    prefer_engine: str | None = None,
    max_files: int = 5,
    seed: int | None = None,
    stop: threading.Event | None = None,
) -> QualitySample:
    """Encode quelques modèles tirés au hasard, mesure l'écart, et trace la courbe sur l'un d'eux."""
    result = QualitySample()
    candidates = [e for e in inv.entries if e.kind in MODEL_KINDS and e.size <= _SAMPLE_MAX_BYTES]
    if not candidates:
        return result
    rng = np.random.default_rng(seed)
    order = [candidates[i] for i in rng.permutation(len(candidates))]
    errors, extents = [], []
    curve_mesh = None
    for entry in order:
        if len(errors) >= max_files or (stop is not None and stop.is_set()):
            break
        try:
            mesh = load_mesh(entry.path, entry.kind)
            _, report = encode_bytes(mesh, settings, prefer_engine)
        except (MeshReadError, EngineError, VerifyError, OSError, MemoryError):
            continue
        errors.append(report.max_error_mm)
        extents.append(mesh.max_extent())
        result.collapsed += report.degenerate_created
        result.identical = result.identical and report.identical
        if entry.size <= _CURVE_MAX_BYTES and (curve_mesh is None or entry.size > curve_mesh.source_size):
            curve_mesh = mesh
            result.curve_file = entry.path
    result.files = len(errors)
    if not errors:
        return result
    result.median_error_mm = statistics.median(errors)
    result.worst_error_mm = max(errors)
    result.median_extent_mm = statistics.median(extents)
    if curve_mesh is not None and not (stop is not None and stop.is_set()):
        base = EncodeSettings(compression_level=settings.compression_level, skip_attributes=settings.skip_attributes)
        engine = select_engine(base, "dracopy")
        result.curve = curve(curve_mesh, engine, base, range(8, engine.max_position_bits + 1))
        result.curve_size_pct = [100.0 * p.size_bytes / curve_mesh.source_size for p in result.curve]
        result.curve_extent_mm = curve_mesh.max_extent()
    return result
