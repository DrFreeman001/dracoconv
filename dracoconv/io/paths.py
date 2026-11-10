"""Chemins Windows de plus de 260 caractères."""
from __future__ import annotations

import os
from pathlib import Path

_LIMIT = 248


def long_path(path: Path | str) -> str:
    """Rend un chemin utilisable par le système même s'il dépasse la limite classique."""
    text = os.path.abspath(str(path))
    if os.name != "nt" or len(text) < _LIMIT or text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text
