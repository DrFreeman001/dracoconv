"""Recensement des fichiers 3D d'un dossier ou d'un disque. Lecture seule."""
from __future__ import annotations

import os
import threading
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .io.archive import list_models
from .io.paths import long_path
from .io.sniff import MODEL_KINDS, FileKind, detect_kind, kind_from_name

DEFAULT_EXCLUDES = ("Windows", "$Recycle.Bin", "System Volume Information", "node_modules", "WinSxS")
_PROGRESS_EVERY = 200


@dataclass(frozen=True)
class FileEntry:
    path: Path
    kind: FileKind
    size: int
    mtime: float
    archive_models: int = 0  # modèles STL/OBJ/PLY/3MF contenus dans un ZIP
    archive_drc: int = 0  # fichiers .drc contenus dans un ZIP


@dataclass
class ScanOptions:
    kinds: frozenset[FileKind] = frozenset(MODEL_KINDS | {FileKind.ZIP, FileKind.DRC})
    exclude_dirs: tuple[str, ...] = DEFAULT_EXCLUDES
    look_inside_zips: bool = True


@dataclass
class Inventory:
    entries: list[FileEntry] = field(default_factory=list)
    ignored: Counter = field(default_factory=Counter)  # raison -> nombre

    def _select(self, kind: FileKind | None) -> list[FileEntry]:
        return self.entries if kind is None else [e for e in self.entries if e.kind is kind]

    def count(self, kind: FileKind | None = None) -> int:
        return len(self._select(kind))

    def total_bytes(self, kind: FileKind | None = None) -> int:
        return sum(e.size for e in self._select(kind))

    def by_kind(self) -> dict[FileKind, list[FileEntry]]:
        grouped: dict[FileKind, list[FileEntry]] = {}
        for entry in self.entries:
            grouped.setdefault(entry.kind, []).append(entry)
        return grouped


def _walk(root: str, excluded: set[str], inventory: Inventory, stop: threading.Event | None):
    """Parcourt un dossier sans suivre les liens ; rend les entrées de fichiers."""
    pending = [root]
    while pending:
        if stop is not None and stop.is_set():
            return
        folder = pending.pop()
        try:
            with os.scandir(folder) as listing:
                items = list(listing)
        except OSError:
            inventory.ignored["access_denied"] += 1
            continue
        for item in items:
            try:
                if item.is_dir(follow_symlinks=False):
                    if item.name.lower() not in excluded and not item.is_symlink():
                        pending.append(item.path)
                elif item.is_file(follow_symlinks=False):
                    yield item.path, item.stat(follow_symlinks=False)
            except OSError:
                inventory.ignored["access_denied"] += 1


def _entry(path_text: str, stat: os.stat_result, options: ScanOptions, inventory: Inventory) -> FileEntry | None:
    kind = kind_from_name(os.path.basename(path_text))
    if kind is FileKind.UNKNOWN:
        return None
    path = Path(path_text[4:] if path_text.startswith("\\\\?\\") and not path_text.startswith("\\\\?\\UNC") else path_text)
    if kind is FileKind.OBJ:
        kind = detect_kind(path)
        if kind is FileKind.COMPILER_OBJ:
            inventory.ignored["compiler_obj"] += 1
            return None
    if kind not in options.kinds:
        return None
    models = drc = 0
    if kind is FileKind.ZIP and options.look_inside_zips:
        try:
            listed = list_models(path)
        except (zipfile.BadZipFile, OSError, NotImplementedError):
            inventory.ignored["unreadable"] += 1
            return None
        models = sum(1 for _, k, _, _ in listed if k in MODEL_KINDS)
        drc = sum(1 for _, k, _, _ in listed if k is FileKind.DRC)
        if models == 0 and drc == 0:
            inventory.ignored["zip_without_models"] += 1
            return None
    return FileEntry(path, kind, stat.st_size, stat.st_mtime, models, drc)


def scan(
    roots: Iterable[Path],
    options: ScanOptions | None = None,
    on_progress: Callable[[int], None] | None = None,
    stop: threading.Event | None = None,
) -> Inventory:
    """Recense les fichiers convertibles sous ``roots`` (fichiers ou dossiers)."""
    options = options or ScanOptions()
    excluded = {name.lower() for name in options.exclude_dirs}
    inventory = Inventory()
    for root in roots:
        if stop is not None and stop.is_set():
            break
        root_text = long_path(root)
        if os.path.isfile(root_text):
            files = [(root_text, os.stat(root_text))]
        elif os.path.isdir(root_text):
            files = _walk(root_text, excluded, inventory, stop)
        else:
            inventory.ignored["access_denied"] += 1
            continue
        for path_text, stat in files:
            entry = _entry(path_text, stat, options, inventory)
            if entry is None:
                continue
            inventory.entries.append(entry)
            if on_progress is not None and len(inventory.entries) % _PROGRESS_EVERY == 0:
                on_progress(len(inventory.entries))
    inventory.entries.sort(key=lambda e: str(e.path).lower())
    if on_progress is not None:
        on_progress(len(inventory.entries))
    return inventory
