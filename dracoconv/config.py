"""Emplacements des fichiers propres à l'utilisateur."""
from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    """Dossier des réglages de l'utilisateur (%APPDATA%\\dracoconv)."""
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    path = Path(base) / "dracoconv"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    """Dossier des journaux de lots (%LOCALAPPDATA%\\dracoconv)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
    path = Path(base) / "dracoconv"
    path.mkdir(parents=True, exist_ok=True)
    return path
