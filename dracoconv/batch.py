"""Traitement par lots : plan, exécution parallèle, journal de reprise, sort des originaux."""
from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from send2trash import send2trash

from .convert import (
    FileResult, decode_file, decode_zip, encode_file, encode_zip, output_path, reason_for, zip_output_path,
)
from .io import MODEL_KINDS, FileKind
from .io.paths import long_path
from .scan import Inventory
from .settings import EncodeSettings

#: Types dont l'original n'est jamais remplacé : la conversion y perd des données.
NEVER_REPLACED = {FileKind.THREEMF, FileKind.ZIP}
_MTIME_TOLERANCE_S = 0.001
_SAME_MTIME_S = 2.0  # certains systèmes de fichiers arrondissent les dates à 2 secondes
_STRIPPED_SUFFIXES = {".stl", ".obj", ".ply", ".3mf", ".drc"}


@dataclass
class BatchOptions:
    direction: Literal["encode", "decode"] = "encode"
    originals: Literal["keep", "mirror", "replace"] = "keep"
    mirror_dir: Path | None = None
    confirm_replace: bool = False
    workers: int | None = None
    output_format: Literal["stl", "obj", "ply"] = "stl"
    big_file_bytes: int = 500 << 20
    prefer_engine: str | None = None
    skip_if_no_gain: bool = True

    def resolved_workers(self) -> int:
        """Par défaut, un processus par cœur physique (la moitié des cœurs logiques)."""
        return self.workers if self.workers else max(1, (os.cpu_count() or 2) // 2)


@dataclass
class PlanItem:
    src: Path
    dst: Path
    kind: FileKind
    size: int
    mtime: float
    replace_allowed: bool
    warning: str | None = None  # « data_loss » ou « not_replaceable »
    skip_reason: str | None = None  # rien à faire pour ce fichier, et pourquoi


def check_free_space(dest: Path, needed_bytes: int) -> bool:
    """Vrai si le volume de ``dest`` a au moins ``needed_bytes`` de libre."""
    folder = Path(dest)
    while not folder.exists() and folder.parent != folder:
        folder = folder.parent
    return shutil.disk_usage(folder).free >= needed_bytes


def _mirror_folder(src: Path, roots: list[Path], mirror_dir: Path) -> Path:
    """Dossier miroir d'un fichier : même arborescence que sous sa racine."""
    best: Path | None = None
    for root in roots:
        root = Path(root)
        base = root if root.is_dir() else root.parent
        try:
            src.relative_to(base)
        except ValueError:
            continue
        if best is None or len(str(base)) > len(str(best)):
            best = base
    if best is None:
        return mirror_dir
    relative = src.parent.relative_to(best)
    if len(roots) > 1:
        label = best.name or best.drive.rstrip(":") or "racine"
        return mirror_dir / label / relative
    return mirror_dir / relative


def _already_converted(src: Path, mtime: float, kind: FileKind, tag: str, folder: Path) -> Path | None:
    """Fichier déjà produit pour cette source lors d'un passage précédent, s'il existe.

    Un fichier produit reçoit la date de modification de sa source : même nom attendu et même
    date signifient que la conversion a déjà eu lieu et que la source n'a pas changé depuis.
    """
    stem = src.stem
    if Path(stem).suffix.lower() in _STRIPPED_SUFFIXES and (kind is FileKind.ZIP or tag != "drc"):
        stem = Path(stem).stem
    if kind is FileKind.ZIP:
        names = [f"{stem}.{tag}.zip"]
    elif tag == "drc":
        names = [f"{stem}.drc", f"{src.name}.drc"]
    else:
        names = [f"{stem}.{tag}"]
    for name in names:
        candidate = folder / name
        try:
            if abs(os.stat(long_path(candidate)).st_mtime - mtime) <= _SAME_MTIME_S and candidate != src:
                return candidate
        except OSError:
            continue
    return None


def build_plan(inv: Inventory, roots: list[Path], settings: EncodeSettings, options: BatchOptions) -> list[PlanItem]:
    """Liste des conversions à faire, avec le nom de chaque fichier produit."""
    if options.originals == "replace" and not options.confirm_replace:
        raise ValueError("replace_not_confirmed")
    if options.originals == "mirror" and options.mirror_dir is None:
        raise ValueError("mirror_dir_required")
    settings.validate()
    taken: set[Path] = set()
    items: list[PlanItem] = []
    encoding = options.direction == "encode"
    for entry in sorted(inv.entries, key=lambda e: str(e.path).lower()):
        if encoding:
            wanted = entry.kind in MODEL_KINDS or (entry.kind is FileKind.ZIP and entry.archive_models > 0)
        else:
            wanted = entry.kind is FileKind.DRC or (entry.kind is FileKind.ZIP and entry.archive_drc > 0)
        if not wanted:
            continue
        folder = entry.path.parent
        if options.originals == "mirror":
            folder = _mirror_folder(entry.path, list(roots), Path(options.mirror_dir))
        tag = "drc" if encoding else options.output_format
        replace_allowed = entry.kind not in NEVER_REPLACED
        existing = _already_converted(entry.path, entry.mtime, entry.kind, tag, folder)
        if existing is not None:
            items.append(PlanItem(entry.path, existing, entry.kind, entry.size, entry.mtime, replace_allowed,
                                  skip_reason="already_converted"))
            continue
        if entry.kind is FileKind.ZIP:
            dst = zip_output_path(entry.path, tag, folder, taken)
        else:
            dst = output_path(entry.path, "." + tag, folder, taken)
        warning = None
        if entry.kind is FileKind.THREEMF:
            warning = "data_loss"
        elif options.originals == "replace" and not replace_allowed:
            warning = "not_replaceable"
        items.append(PlanItem(entry.path, dst, entry.kind, entry.size, entry.mtime, replace_allowed, warning))
    return items


_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    src TEXT PRIMARY KEY, dst TEXT, kind TEXT, size_before INTEGER, size_after INTEGER,
    settings_json TEXT, state TEXT, reason TEXT, note TEXT, duration_s REAL, src_mtime REAL,
    replace_allowed INTEGER, warning TEXT, position INTEGER
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
_CSV_COLUMNS = ("src", "dst", "kind", "size_before", "size_after", "state", "reason", "note", "duration_s")


class Journal:
    """Journal SQLite d'un lot : ce qui est prévu, fait, ignoré ou en échec. Permet la reprise."""

    def __init__(self, path: Path):
        self.path = Path(path)
        os.makedirs(long_path(self.path.parent), exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def add_plan(self, items: list[PlanItem], settings: EncodeSettings) -> None:
        """Inscrit le plan. Un fichier déjà présent dans le journal garde son état."""
        text = settings.to_json()
        with self._lock, self._db:
            start = self._db.execute("SELECT COALESCE(MAX(position), 0) FROM files").fetchone()[0]
            self._db.executemany(
                "INSERT OR IGNORE INTO files VALUES (?,?,?,?,NULL,?,?,?,NULL,NULL,?,?,?,?)",
                [
                    (str(i.src), str(i.dst), i.kind.value, i.size, text,
                     "skipped" if i.skip_reason else "pending", i.skip_reason,
                     i.mtime, int(i.replace_allowed), i.warning, start + n + 1)
                    for n, i in enumerate(items)
                ],
            )
            self._db.execute("INSERT OR REPLACE INTO meta VALUES ('settings', ?)", (text,))

    def settings(self) -> EncodeSettings:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = 'settings'").fetchone()
        return EncodeSettings.from_json(row[0]) if row else EncodeSettings()

    def pending(self) -> list[PlanItem]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM files WHERE state = 'pending' ORDER BY position").fetchall()
        return [
            PlanItem(Path(r["src"]), Path(r["dst"]), FileKind(r["kind"]), r["size_before"], r["src_mtime"],
                     bool(r["replace_allowed"]), r["warning"])
            for r in rows
        ]

    def record(self, result: FileResult) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE files SET state = ?, reason = ?, note = ?, size_after = ?, duration_s = ?, "
                "size_before = CASE WHEN ? > 0 THEN ? ELSE size_before END, dst = COALESCE(?, dst) WHERE src = ?",
                (result.state, result.reason, result.note, result.size_after, result.duration_s,
                 result.size_before, result.size_before, str(result.dst) if result.dst else None, str(result.src)),
            )

    def retry_failed(self) -> int:
        """Remet les échecs en attente ; rend leur nombre."""
        with self._lock, self._db:
            return self._db.execute(
                "UPDATE files SET state = 'pending', reason = NULL, note = NULL WHERE state = 'failed'"
            ).rowcount

    def set_paused(self, reason: str | None) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO meta VALUES ('paused', ?)", (reason,))

    def row(self, src: Path) -> dict | None:
        with self._lock:
            found = self._db.execute("SELECT * FROM files WHERE src = ?", (str(src),)).fetchone()
        return dict(found) if found else None

    def rows(self, state: str | None = None) -> list[dict]:
        query = "SELECT * FROM files" + (" WHERE state = ?" if state else "") + " ORDER BY position"
        with self._lock:
            return [dict(r) for r in self._db.execute(query, (state,) if state else ())]

    def summary(self) -> dict:
        counts: Counter = Counter()
        reasons: Counter = Counter()
        before = after = 0
        for r in self.rows():
            counts[r["state"]] += 1
            before += r["size_before"] or 0
            after += r["size_after"] if r["state"] == "done" and r["size_after"] is not None else (r["size_before"] or 0)
            if r["state"] in ("failed", "skipped") and r["reason"]:
                reasons[r["reason"]] += 1
        with self._lock:
            paused = self._db.execute("SELECT value FROM meta WHERE key = 'paused'").fetchone()
        return {
            "total": sum(counts.values()),
            "done": counts["done"], "skipped": counts["skipped"], "failed": counts["failed"],
            "pending": counts["pending"],
            "bytes_before": before, "bytes_after": after,
            "reasons": dict(reasons),
            "paused": paused[0] if paused else None,
        }

    def export_csv(self, path: Path) -> None:
        with open(long_path(path), "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(_CSV_COLUMNS)
            for r in self.rows():
                writer.writerow([r[c] for c in _CSV_COLUMNS])


def _convert_item(item: PlanItem, settings: EncodeSettings, options: BatchOptions) -> FileResult:
    """Convertit un fichier du plan. Exécuté dans un processus de travail ou dans le processus principal."""
    changed = False
    try:
        stat = os.stat(long_path(item.src))
        changed = stat.st_size != item.size or abs(stat.st_mtime - item.mtime) > _MTIME_TOLERANCE_S
    except OSError:
        pass
    if options.direction == "encode":
        if item.kind is FileKind.ZIP:
            result = encode_zip(item.src, item.dst, settings, options.prefer_engine)
        else:
            result = encode_file(item.src, item.dst, settings, options.prefer_engine, options.skip_if_no_gain)
    elif item.kind is FileKind.ZIP:
        result = decode_zip(item.src, item.dst, options.output_format)
    else:
        result = decode_file(item.src, item.dst, options.output_format)
    if changed and result.note is None:
        result.note = "changed"  # le fichier a changé depuis l'analyse : converti dans son état actuel
    return result


def _safe_convert(item: PlanItem, settings: EncodeSettings, options: BatchOptions) -> FileResult:
    started = time.perf_counter()
    try:
        return _convert_item(item, settings, options)
    except Exception as exc:  # l'échec d'un fichier ne doit jamais arrêter le lot
        return FileResult(item.src, None, "failed", reason_for(exc), item.size, duration_s=time.perf_counter() - started)


def run(
    journal: Journal,
    settings: EncodeSettings,
    options: BatchOptions,
    on_progress: Callable[[FileResult], None] | None = None,
    stop: threading.Event | None = None,
) -> dict:
    """Exécute les fichiers en attente du journal ; rend le résumé. Relancer reprend là où on s'est arrêté."""
    journal.set_paused(None)
    items = journal.pending()
    small = [i for i in items if i.size < options.big_file_bytes]
    big = [i for i in items if i.size >= options.big_file_bytes]
    paused: list[str] = []

    def halted() -> bool:
        return bool(paused) or (stop is not None and stop.is_set())

    def finish(item: PlanItem, result: FileResult) -> None:
        if result.reason == "disk_full":
            paused.append("disk_full")  # le fichier reste en attente
            return
        if result.state == "done" and options.originals == "replace" and item.replace_allowed:
            try:
                send2trash(str(item.src))
            except Exception:
                result.note = "recycle_unavailable"  # original conservé
        journal.record(result)
        if on_progress is not None:
            on_progress(result)

    workers = min(options.resolved_workers(), len(small))
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            queue = iter(small)
            running: dict = {}
            while True:
                while not halted() and len(running) < workers * 2:
                    item = next(queue, None)
                    if item is None:
                        break
                    running[pool.submit(_convert_item, item, settings, options)] = item
                if not running:
                    break
                finished, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in finished:
                    item = running.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = FileResult(item.src, None, "failed", reason_for(exc), item.size)
                    finish(item, result)
    else:
        for item in small:
            if halted():
                break
            finish(item, _safe_convert(item, settings, options))
    # Les très gros fichiers passent un par un pour borner la mémoire.
    for item in big:
        if halted():
            break
        finish(item, _safe_convert(item, settings, options))
    if paused:
        journal.set_paused(paused[0])
    return journal.summary()
