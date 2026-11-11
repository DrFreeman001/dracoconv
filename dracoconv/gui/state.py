"""État partagé entre les étapes de la fenêtre."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..batch import Journal
from ..estimate import Projection
from ..scan import Inventory


@dataclass
class AppState:
    roots: list[Path] = field(default_factory=list)
    direction: Literal["encode", "decode"] = "encode"
    inventory: Inventory | None = None
    projection: Projection | None = None
    journal: Journal | None = None
    reference_extent: float | None = None  # taille médiane des modèles mesurés, en mm
