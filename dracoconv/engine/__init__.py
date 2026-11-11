"""Moteurs Draco et choix automatique du moteur."""
from __future__ import annotations

from typing import Literal

from ..settings import EncodeSettings
from .base import Engine, EngineError, unsupported_params
from .cli import CliEngine, find_binaries
from .dracopy import DracoPyEngine

EngineName = Literal["dracopy", "reference"]


def reference_engine() -> CliEngine | None:
    binaries = find_binaries()
    return CliEngine(*binaries) if binaries else None


def decoder() -> Engine:
    """Moteur de décodage : l'intégré lit tous les fichiers Draco."""
    return DracoPyEngine()


def select_engine(settings: EncodeSettings, prefer: EngineName | None = None, max_extent: float = 0.0) -> Engine:
    """Moteur intégré si tous les réglages demandés y sont disponibles, sinon moteur de référence."""
    builtin = DracoPyEngine()
    if prefer == "dracopy":
        candidates: list[Engine | None] = [builtin]
    elif prefer == "reference":
        candidates = [reference_engine()]
    else:
        candidates = [builtin]
        if not builtin.can_encode(settings, max_extent):
            candidates.append(reference_engine())
    missing: set[str] = set()
    for engine in candidates:
        if engine is None:
            missing.add("draco_encoder")
            continue
        unsupported = unsupported_params(engine, settings, max_extent)
        if not unsupported:
            return engine
        missing |= unsupported
    raise EngineError("engine_unavailable", ", ".join(sorted(missing)))


__all__ = [
    "CliEngine", "DracoPyEngine", "Engine", "EngineError", "decoder", "find_binaries", "reference_engine",
    "select_engine",
]
