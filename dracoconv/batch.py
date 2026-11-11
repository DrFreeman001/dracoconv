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
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
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
# Mémoire estimée d'une conversion : une base par processus, plus un multiple de la taille du fichier
# (lecture, fusion des sommets, encodage, relecture de vérification).
_MEMORY_BASE = 300 << 20
_MEMORY_FACTOR = 20
_MEMORY_SHARE = 0.6  # part de la mémoire disponible que le lot s'autorise
_DRIVE_FIXED = 3
_MAX_POOL_RESTARTS = 3
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


def _plain_stem(src: Path, kind: FileKind, tag: str) -> str:
    stem = src.stem
    if Path(stem).suffix.lower() in _STRIPPED_SUFFIXES and (kind is FileKind.ZIP or tag != "drc"):
        stem = Path(stem).stem
    return stem


def _already_converted(
    src: Path, mtime: float, kind: FileKind, tag: str, folder: Path, owns_stem: bool = True
) -> Path | None:
    """Fichier déjà produit pour cette source lors d'un passage précédent, s'il existe.

    Un fichier produit reçoit la date de modification de sa source : même nom attendu et même
    date signifient que la conversion a déjà eu lieu et que la source n'a pas changé depuis.

    ``owns_stem`` dit si cette source est celle à qui le plan donnerait le nom court
    (``piece.drc``). Quand deux sources partagent le même nom sans extension, seule la première
    y a droit ; l'autre ne peut avoir produit que ``piece.stl.drc``. Sans cette règle, le
    ``piece.drc`` de l'une passerait pour la conversion de l'autre.
    """
    stem = _plain_stem(src, kind, tag)
    if kind is FileKind.ZIP:
        names = [f"{stem}.{tag}.zip"] if owns_stem else []
    elif tag == "drc":
        names = [f"{stem}.drc", f"{src.name}.drc"] if owns_stem else [f"{src.name}.drc"]
    else:
        names = [f"{stem}.{tag}"] if owns_stem else []
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
    tag = "drc" if encoding else options.output_format

    def wanted(entry) -> bool:
        if encoding:
            return entry.kind in MODEL_KINDS or (entry.kind is FileKind.ZIP and entry.archive_models > 0)
        return entry.kind is FileKind.DRC or (entry.kind is FileKind.ZIP and entry.archive_drc > 0)

    def folder_of(entry) -> Path:
        if options.originals == "mirror":
            return _mirror_folder(entry.path, list(roots), Path(options.mirror_dir))
        return entry.path.parent

    entries = [e for e in sorted(inv.entries, key=lambda e: str(e.path).lower()) if wanted(e)]
    # Première source de chaque nom sans extension, par dossier de destination et par famille
    # (archives d'un côté, modèles de l'autre) : c'est elle qui reçoit le nom court.
    owners: dict[tuple, Path] = {}
    for entry in entries:
        key = (folder_of(entry), entry.kind is FileKind.ZIP, _plain_stem(entry.path, entry.kind, tag).lower())
        owners.setdefault(key, entry.path)
    for entry in entries:
        folder = folder_of(entry)
        replace_allowed = entry.kind not in NEVER_REPLACED
        key = (folder, entry.kind is FileKind.ZIP, _plain_stem(entry.path, entry.kind, tag).lower())
        existing = _already_converted(entry.path, entry.mtime, entry.kind, tag, folder,
                                      owns_stem=owners[key] == entry.path)
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

    def add_plan(self, items: list[PlanItem], settings: EncodeSettings, options: BatchOptions | None = None) -> None:
        """Inscrit le plan. Un fichier déjà présent dans le journal garde son état.

        Le mode du lot (sens, sort des originaux, dossier miroir) est mémorisé à la première
        inscription : les destinations ont été calculées pour ce mode, il ne doit plus changer.
        """
        text = settings.to_json()
        if options is not None and self.options() is None:
            stored = {
                "direction": options.direction, "originals": options.originals,
                "mirror_dir": str(options.mirror_dir) if options.mirror_dir else None,
                "confirm_replace": options.confirm_replace, "output_format": options.output_format,
                "prefer_engine": options.prefer_engine, "skip_if_no_gain": options.skip_if_no_gain,
            }
            with self._lock, self._db:
                self._db.execute("INSERT OR REPLACE INTO meta VALUES ('options', ?)", (json.dumps(stored),))
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

    def options(self) -> BatchOptions | None:
        """Mode mémorisé du lot, ou None si le journal n'en a pas."""
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = 'options'").fetchone()
        if not row or not row[0]:
            return None
        stored = json.loads(row[0])
        if stored.get("mirror_dir"):
            stored["mirror_dir"] = Path(stored["mirror_dir"])
        return BatchOptions(**stored)

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


#: Variables qui fixent le nombre de fils des bibliothèques de calcul (numpy, scipy).
THREAD_VARIABLES = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")


@contextmanager
def _single_threaded_children():
    """Les processus de travail héritent de ces variables à leur création.

    Le parallélisme vient déjà des processus ; sans cela, chacun réserverait en plus des tampons
    pour autant de fils qu'il y a de cœurs, ce qui épuise la mémoire sur une machine à 32 cœurs.
    """
    saved = {name: os.environ.get(name) for name in THREAD_VARIABLES}
    os.environ.update({name: "1" for name in THREAD_VARIABLES})
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def available_memory() -> int | None:
    """Mémoire que Windows accepte encore de réserver, en octets ; None si inconnue.

    C'est la limite de réservation (« commit ») qui compte, pas la mémoire physique libre :
    sans fichier d'échange, elle peut être épuisée alors qu'il reste de la mémoire physique.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes

        class _Status(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _Status()
        status.dwLength = ctypes.sizeof(_Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(min(status.ullAvailPageFile, status.ullAvailPhys))
    except Exception:
        return None


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


def recycle_bin_available(path: Path) -> bool:
    """Vrai si le volume de ``path`` a une corbeille utilisable.

    Sans corbeille (partage réseau, clé USB, volume sans dossier de corbeille), Windows supprime
    définitivement et sans erreur ce qu'on lui demande de « recycler ». Dans le doute, on répond
    non : l'original est alors conservé.
    """
    if os.name != "nt":
        return True
    try:
        import ctypes

        root = os.path.splitdrive(os.path.abspath(str(path)))[0] + "\\"
        if ctypes.windll.kernel32.GetDriveTypeW(root) != _DRIVE_FIXED:
            return False

        class _BinInfo(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]

        info = _BinInfo()
        info.cbSize = ctypes.sizeof(_BinInfo)
        return ctypes.windll.shell32.SHQueryRecycleBinW(root, ctypes.byref(info)) == 0
    except Exception:
        return False


def _already_written(item: PlanItem, preexisting: set[Path]) -> FileResult | None:
    """Résultat d'un fichier que son processus a écrit avant de disparaître, s'il existe.

    Un fichier n'est renommé à son nom définitif qu'après vérification et relecture, et reçoit la
    date de sa source. S'il n'existait pas au début du lot et qu'il est là avec cette date, c'est
    ce lot qui l'a produit. Un fichier déjà présent au début du lot ne prouve rien.
    """
    if item.dst in preexisting:
        return None
    try:
        source, produced = os.stat(long_path(item.src)), os.stat(long_path(item.dst))
    except OSError:
        return None
    if abs(produced.st_mtime - source.st_mtime) > _SAME_MTIME_S:
        return None
    return FileResult(item.src, item.dst, "done", None, source.st_size, size_after=produced.st_size)


def _safe_convert(item: PlanItem, settings: EncodeSettings, options: BatchOptions) -> FileResult:
    started = time.perf_counter()
    try:
        return _convert_item(item, settings, options)
    except Exception as exc:  # l'échec d'un fichier ne doit jamais arrêter le lot
        return FileResult(item.src, None, "failed", reason_for(exc), item.size, duration_s=time.perf_counter() - started)


def _isolated_convert(item: PlanItem, settings: EncodeSettings, options: BatchOptions) -> FileResult:
    """Convertit un fichier suspect dans un processus à lui.

    Un fichier présent quand un processus de travail est mort a peut-être causé cette mort.
    Le retenter dans le processus principal ferait tomber toute l'application, à chaque reprise.
    Ici, s'il tue encore son processus, il est mis en échec et le lot continue.
    """
    crashed = FileResult(item.src, None, "failed", "worker_crashed", item.size)
    try:
        with _single_threaded_children(), ProcessPoolExecutor(max_workers=1) as pool:
            try:
                future = pool.submit(_convert_item, item, settings, options)
            except BrokenProcessPool:
                # Impossible de lancer le moindre processus : il ne reste que le processus principal.
                return _safe_convert(item, settings, options)
            try:
                return future.result()
            except BrokenProcessPool:
                return crashed
            except BaseException as exc:
                return FileResult(item.src, None, "failed", reason_for(exc), item.size)
    except BrokenProcessPool:
        return crashed


def run(
    journal: Journal,
    settings: EncodeSettings,
    options: BatchOptions,
    on_progress: Callable[[FileResult], None] | None = None,
    stop: threading.Event | None = None,
) -> dict:
    """Exécute les fichiers en attente du journal ; rend le résumé. Relancer reprend là où on s'est arrêté."""
    if options.originals == "replace" and not options.confirm_replace:
        raise ValueError("replace_not_confirmed")
    stored = journal.options()
    if stored is not None and (stored.direction, stored.originals, stored.mirror_dir) != (
            options.direction, options.originals, options.mirror_dir):
        # Les destinations du journal ont été calculées pour un autre mode : on ne mélange pas.
        raise ValueError("journal_mode_mismatch")
    journal.set_paused(None)
    items = journal.pending()
    preexisting = {item.dst for item in items if os.path.lexists(long_path(item.dst))}
    small = [i for i in items if i.size < options.big_file_bytes]
    big = [i for i in items if i.size >= options.big_file_bytes]
    paused: list[str] = []

    def halted() -> bool:
        return bool(paused) or (stop is not None and stop.is_set())

    def finish(item: PlanItem, result: FileResult) -> None:
        if result.reason == "disk_full":
            paused.append("disk_full")  # le fichier reste en attente
            return
        if result.state == "done" and options.originals == "replace":
            if not item.replace_allowed or result.lossy_source:
                # La conversion a écarté des données (textures, couleurs, triangles…) : l'original reste.
                result.note = result.note or "replace_forbidden"
            elif not recycle_bin_available(item.src):
                result.note = "recycle_unavailable"  # original conservé
            else:
                try:
                    send2trash(str(item.src))
                except Exception:
                    result.note = "recycle_unavailable"  # original conservé
        journal.record(result)
        if on_progress is not None:
            on_progress(result)

    workers = min(options.resolved_workers(), len(small))
    alone: list[PlanItem] = []  # mémoire insuffisante en parallèle : repris un par un
    suspects: list[PlanItem] = []  # en cours quand un processus de travail est mort
    remaining = list(small)
    if workers > 1:
        available = available_memory()
        budget = available * _MEMORY_SHARE if available else None
        restarts = 0
        while remaining and not halted() and restarts <= _MAX_POOL_RESTARTS:
            queue = list(reversed(remaining))
            running: dict = {}
            needs: dict = {}
            try:
                with _single_threaded_children(), ProcessPoolExecutor(max_workers=workers) as pool:
                    while True:
                        while queue and not halted() and len(running) < workers:
                            need = _MEMORY_BASE + queue[-1].size * _MEMORY_FACTOR
                            if running and budget is not None and sum(needs.values()) + need > budget:
                                break  # attendre qu'une conversion en cours libère de la mémoire
                            item = queue[-1]
                            future = pool.submit(_convert_item, item, settings, options)
                            queue.pop()  # retiré seulement une fois confié au pool
                            running[future] = item
                            needs[future] = need
                        if not running:
                            break
                        finished, _ = wait(running, return_when=FIRST_COMPLETED)
                        for future in finished:
                            item = running.pop(future)
                            needs.pop(future, None)
                            try:
                                result = future.result()
                            except BrokenProcessPool:
                                suspects.append(item)  # déjà retiré des conversions en cours : ne pas le perdre
                                raise
                            except BaseException as exc:
                                result = FileResult(item.src, None, "failed", reason_for(exc), item.size)
                            if result.reason == "out_of_memory":
                                alone.append(item)
                            else:
                                finish(item, result)
                remaining = []  # le pool est allé au bout (ou l'arrêt a été demandé)
            except BrokenProcessPool:
                # Un processus de travail est mort : ce qui était en cours devient suspect,
                # le reste repart dans un pool neuf.
                suspects.extend(running.values())
                remaining = list(reversed(queue))
                restarts += 1
        if halted():
            remaining, suspects, alone = [], [], []
    else:
        for item in small:
            if halted():
                break
            finish(item, _safe_convert(item, settings, options))
        remaining = []
    # Suspects : un processus a pu finir d'écrire son fichier juste avant de mourir (il est alors
    # bon) ; sinon le fichier est retenté dans un processus à lui.
    for item in suspects + remaining:
        if halted():
            break
        finish(item, _already_written(item, preexisting) or _isolated_convert(item, settings, options))
    for item in alone:
        if halted():
            break
        finish(item, _already_written(item, preexisting) or _safe_convert(item, settings, options))
    # Les très gros fichiers passent un par un pour borner la mémoire.
    for item in big:
        if halted():
            break
        finish(item, _safe_convert(item, settings, options))
    if paused:
        journal.set_paused(paused[0])
    return journal.summary()
