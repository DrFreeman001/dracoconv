"""Interface commune des moteurs Draco."""
from __future__ import annotations

from dataclasses import replace
from typing import Protocol

import numpy as np

from ..mesh import Mesh
from ..settings import EncodeSettings, resolved


class EngineError(Exception):
    """Échec d'encodage ou de décodage ; ``reason`` est un code de raison."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


class Engine(Protocol):
    name: str
    supports: frozenset[str]
    max_position_bits: int

    def can_encode(self, settings: EncodeSettings, max_extent: float) -> bool: ...

    def encode(self, mesh: Mesh, settings: EncodeSettings) -> bytes: ...

    def decode(self, data: bytes) -> Mesh: ...


def unsupported_params(engine: Engine, settings: EncodeSettings, max_extent: float) -> set[str]:
    """Paramètres demandés que ce moteur ne sait pas honorer."""
    final = resolved(settings, max_extent)
    # « keep_topology » est une décision prise avant le moteur (voir convert.encode_bytes).
    missing = final.non_default() - set(engine.supports) - {"keep_topology"}
    if final.position_bits > engine.max_position_bits:
        missing.add("position_bits")
    return missing


def prepare(mesh: Mesh, settings: EncodeSettings) -> tuple[Mesh, EncodeSettings]:
    """Applique ce qui ne dépend pas du moteur : tolérance, attributs écartés, nuage de points."""
    final = resolved(settings, mesh.max_extent())
    skip = final.skip_attributes
    faces = np.zeros((0, 3), np.uint32) if final.point_cloud else mesh.faces
    prepared = replace(
        mesh,
        faces=faces,
        normals=None if "normal" in skip or final.point_cloud else mesh.normals,
        texcoords=None if "texcoord" in skip else mesh.texcoords,
        colors=None if "color" in skip else mesh.colors,
    )
    return prepared, final
