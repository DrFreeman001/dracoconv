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


def load_prefs() -> dict:
    """Préférences de l'interface (langue)."""
    import json

    try:
        return json.loads((config_dir() / "prefs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_prefs(values: dict) -> None:
    import json

    prefs = load_prefs()
    prefs.update(values)
    try:
        (config_dir() / "prefs.json").write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except OSError:
        pass


def data_dir() -> Path:
    """Dossier des journaux de lots (%LOCALAPPDATA%\\dracoconv)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
    path = Path(base) / "dracoconv"
    path.mkdir(parents=True, exist_ok=True)
    return path
