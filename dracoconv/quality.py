"""Perte de qualité : écart théorique, écart mesuré, contrôles d'intégrité."""
from __future__ import annotations

import math

MAX_BITS = 30
#: Repères affichés à côté d'un écart, en millimètres.
REFERENCE_MARKS_MM = {"layer_height": 0.2, "nozzle": 0.4, "cad_tolerance": 0.01}


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
