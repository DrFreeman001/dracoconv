"""Ouvrir des .drc dans un trancheur (Bambu Studio, OrcaSlicer, PrusaSlicer), qui ne lisent pas le Draco.

Chaque .drc est décodé en STL binaire dans un dossier temporaire, vérifié comme pour une conversion, puis le
trancheur est lancé sur ces STL. Les dossiers temporaires de plus de deux jours sont effacés au passage.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import load_prefs, save_prefs


@dataclass(frozen=True)
class Slicer:
    key: str
    name: str
    exe: str
    folders: tuple[str, ...]


KNOWN = (
    Slicer("bambu", "Bambu Studio", "bambu-studio.exe", ("Bambu Studio",)),
    Slicer("orca", "OrcaSlicer", "orca-slicer.exe", ("OrcaSlicer",)),
    Slicer("prusa", "PrusaSlicer", "prusa-slicer.exe", ("Prusa3D/PrusaSlicer", "PrusaSlicer")),
)
TEMP_ROOT_NAME = "dracoconv-trancheur"
MAX_AGE_S = 2 * 24 * 3600


class SlicerError(Exception):
    """Aucun trancheur utilisable, ou rien à ouvrir."""


def _registered_exes() -> dict[str, Path]:
    """Exécutables cités par les entrées de désinstallation (Windows), par nom de fichier en minuscules."""
    found: dict[str, Path] = {}
    if os.name != "nt":
        return found
    import winreg

    places = ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
              (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"))
    for hive, path in places:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            for index in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                        icon = str(winreg.QueryValueEx(key, "DisplayIcon")[0])
                except OSError:
                    continue
                exe = Path(icon.split(",")[0].strip().strip('"'))
                if exe.suffix.lower() == ".exe":
                    found.setdefault(exe.name.lower(), exe)
    return found


def find_slicers() -> dict[str, Path]:
    """Trancheurs installés : clé → exécutable, dans l'ordre de KNOWN."""
    registered = _registered_exes()
    bases = [Path(p) for p in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA", "") + "/Programs")
             if p]
    result: dict[str, Path] = {}
    for slicer in KNOWN:
        candidates = [registered.get(slicer.exe)] + [base / folder / slicer.exe
                                                     for base in bases for folder in slicer.folders]
        exe = next((c for c in candidates if c is not None and c.is_file()), None)
        if exe is not None:
            result[slicer.key] = exe
    return result


def chosen() -> tuple[str, Path] | None:
    """Trancheur à utiliser : le choix enregistré s'il existe encore, sinon le premier trouvé."""
    pref = load_prefs().get("slicer")
    if pref:
        path = Path(pref)
        if path.is_file():
            return label(path), path
    found = find_slicers()
    if pref in found:
        return label(found[pref]), found[pref]
    for key, exe in found.items():
        return label(exe), exe
    return None


def choose(value: str | Path | None) -> None:
    """Enregistre le trancheur : chemin d'un exécutable, ou None pour revenir au choix automatique."""
    save_prefs({"slicer": str(value) if value else None})


def label(exe: Path) -> str:
    for slicer in KNOWN:
        if exe.name.lower() == slicer.exe:
            return slicer.name
    return exe.stem


def clean_old(root: Path | None = None, now: float | None = None) -> None:
    root = root or Path(tempfile.gettempdir()) / TEMP_ROOT_NAME
    now = time.time() if now is None else now
    if not root.is_dir():
        return
    for folder in root.iterdir():
        try:
            if folder.is_dir() and now - folder.stat().st_mtime > MAX_AGE_S:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


def prepare(paths: list[Path], root: Path | None = None) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Décode les .drc en STL dans un nouveau dossier temporaire. Rend (STL prêts, échecs (chemin, raison))."""
    from .convert import decode_file

    root = root or Path(tempfile.gettempdir()) / TEMP_ROOT_NAME
    clean_old(root)
    folder = root / uuid.uuid4().hex[:12]
    folder.mkdir(parents=True, exist_ok=True)
    ready, failed, used = [], [], set()
    for src in paths:
        src = Path(src)
        if src.suffix.lower() != ".drc":
            failed.append((src, "not_draco"))
            continue
        name = src.stem
        while name.lower() in used:  # deux .drc du même nom dans des dossiers différents
            name += "_"
        used.add(name.lower())
        result = decode_file(src, folder / f"{name}.stl", "stl")
        if result.state == "done":
            ready.append(folder / f"{name}.stl")
        else:
            failed.append((src, result.reason or "failed"))
    return ready, failed


def launch(exe: Path, files: list[Path]) -> None:
    """Lance le trancheur sur les fichiers, sans attendre qu'il se ferme."""
    if not files:
        raise SlicerError("nothing")
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(exe), *map(str, files)], cwd=str(exe.parent), close_fds=True, creationflags=flags)
