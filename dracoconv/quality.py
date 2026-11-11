"""Perte de qualité : écart théorique, écart mesuré, contrôles d'intégrité."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Iterable

import numpy as np

if TYPE_CHECKING:
    from .mesh import Mesh

MAX_BITS = 30
#: Repères affichés à côté d'un écart, en millimètres.
REFERENCE_MARKS_MM = {"layer_height": 0.2, "nozzle": 0.4, "cad_tolerance": 0.01}
#: Marge d'arrondi des flottants 32 bits, en nombre de pas de la plus grande coordonnée.
_FLOAT_STEPS = 8


def quantization_step_mm(max_extent: float, bits: int) -> float:
    """Pas de la grille de quantification pour un modèle de cette taille."""
    if bits <= 0:
        return 0.0
    return max_extent / (2**bits - 1)


def theoretical_error_mm(max_extent: float, bits: int) -> float:
    """Déplacement maximal d'un sommet : un demi-pas par axe, soit pas × √3 / 2 en distance."""
    return quantization_step_mm(max_extent, bits) * math.sqrt(3) / 2


def bits_for_tolerance(max_extent: float, tolerance_mm: float) -> int:
    """Plus petit nombre de bits respectant la tolérance ; 0 (sans quantification) si aucun."""
    for bits in range(1, MAX_BITS + 1):
        if theoretical_error_mm(max_extent, bits) <= tolerance_mm:
            return bits
    return 0


def float_floor_mm(mesh: "Mesh") -> float:
    """Plancher de précision : les coordonnées sont des flottants 32 bits.

    Au-delà d'un certain nombre de bits, la grille devient plus fine que ce qu'un
    flottant 32 bits peut représenter à cette distance de l'origine ; l'écart ne baisse plus.
    """
    if len(mesh.positions) == 0:
        return 0.0
    largest = np.float32(np.abs(mesh.positions).max())
    return float(np.spacing(largest)) * _FLOAT_STEPS


def error_bound_mm(mesh: "Mesh", bits: int) -> float:
    """Écart maximal garanti pour ce modèle : écart théorique plus plancher des flottants."""
    if bits <= 0:
        return 0.0
    return theoretical_error_mm(mesh.max_extent(), bits) + float_floor_mm(mesh)


@dataclass
class QualityReport:
    max_error_mm: float
    rms_error_mm: float
    triangles_before: int  # hors triangles dégénérés
    triangles_after: int
    degenerate_created: int  # triangles écrasés par la conversion
    vertices_merged: int
    identical: bool
    #: Sommets que Draco a dédoublés (surface non variété). La géométrie est intacte, mais un
    #: logiciel qui relie les triangles par numéro de sommet y verra des arêtes ouvertes.
    vertices_split: int = 0
    watertight_before: bool | None = None
    watertight_after: bool | None = None
    volume_change_pct: float | None = None


def _integrity(mesh: "Mesh") -> tuple[bool, float | None]:
    import trimesh

    if mesh.triangle_count() == 0:
        return False, None
    tm = trimesh.Trimesh(mesh.positions, mesh.faces, process=False)
    watertight = bool(tm.is_watertight)
    return watertight, float(tm.volume) if watertight else None


def measure(source: "Mesh", decoded: "Mesh", integrity: bool = True) -> QualityReport:
    """Compare un maillage à sa version décodée. ``integrity=False`` saute étanchéité et volume."""
    from scipy.spatial import cKDTree

    canon_before, _ = source.canonical_triangles()
    canon_after, _ = decoded.canonical_triangles()
    identical = canon_before.shape == canon_after.shape and bool(np.array_equal(canon_before, canon_after))
    if source.triangle_count() == 0:  # nuage de points : on compare les ensembles de points
        identical = bool(
            np.array_equal(np.unique(source.positions, axis=0), np.unique(decoded.positions, axis=0))
        )
    if identical or len(decoded.positions) == 0:
        max_error = rms_error = 0.0 if identical else math.inf
    else:
        distances, _ = cKDTree(decoded.positions).query(source.positions)
        max_error = float(distances.max())
        rms_error = float(np.sqrt(np.mean(distances.astype(np.float64) ** 2)))
    before, after = len(canon_before), len(canon_after)
    report = QualityReport(
        max_error_mm=max_error,
        rms_error_mm=rms_error,
        triangles_before=before,
        triangles_after=after,
        degenerate_created=max(0, before - after),
        vertices_merged=max(0, len(np.unique(source.positions, axis=0)) - len(np.unique(decoded.positions, axis=0)))
        if not identical else 0,
        identical=identical,
        vertices_split=max(0, len(decoded.positions) - len(source.positions)) if source.triangle_count() else 0,
    )
    if integrity:
        report.watertight_before, volume_before = _integrity(source)
        if identical:
            report.watertight_after, volume_after = report.watertight_before, volume_before
        else:
            report.watertight_after, volume_after = _integrity(decoded)
        if volume_before and volume_after is not None:
            report.volume_change_pct = (volume_after - volume_before) / abs(volume_before) * 100.0
    return report


@dataclass
class CurvePoint:
    bits: int
    size_bytes: int
    theoretical_error_mm: float
    max_error_mm: float


def curve(mesh: "Mesh", engine, settings, bits: Iterable[int] = range(8, MAX_BITS)) -> list[CurvePoint]:
    """Taille obtenue et écart mesuré pour chaque nombre de bits demandé."""
    points = []
    extent = mesh.max_extent()
    for b in bits:
        data = engine.encode(mesh, replace(settings, position_bits=b, tolerance_mm=None))
        report = measure(mesh, engine.decode(data), integrity=False)
        points.append(CurvePoint(b, len(data), theoretical_error_mm(extent, b), report.max_error_mm))
    return points
