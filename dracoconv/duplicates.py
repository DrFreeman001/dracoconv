"""Recherche des doublons de modèles 3D. Lecture seule.

Deux sortes de doublons :
- fichiers identiques octet pour octet ;
- même modèle sous une autre forme : un STL et le .drc qui en vient, ou deux .drc du même modèle faits avec
  d'autres réglages ou une ancienne version de dracoconv.

Le second cas ne peut pas se juger sur le contenu exact : Draco arrondit les coordonnées. Chaque modèle est
donc résumé par des mesures qui ne dépendent ni de l'ordre des triangles ni de la position du modèle (nombre
de triangles, dimensions, surface, volume, centre et répartition de la surface), comparées avec une tolérance
qui couvre l'arrondi de Draco. Un déplacement de trou ou une variante paramétrique change le centre ou la
répartition, et ne passe pas pour un doublon. Les ZIP ne sont pas ouverts.

Les mesures sont gardées dans un cache (%LOCALAPPDATA%\\dracoconv\\empreintes.sqlite) : une seconde recherche
ne relit que les fichiers nouveaux ou modifiés.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .config import data_dir
from .io.paths import long_path
from .io.sniff import MODEL_KINDS, FileKind
from .scan import FileEntry

#: Version des mesures : la changer invalide le cache.
FINGERPRINT_VERSION = 1
#: Tolérances relatives (à la plus grande dimension, ou à la valeur mesurée).
SIZE_TOLERANCE = 2e-3
MEASURE_TOLERANCE = 5e-3
KINDS = frozenset(MODEL_KINDS | {FileKind.DRC})


@dataclass(frozen=True)
class Fingerprint:
    digest: str  # empreinte du contenu exact
    vertices: int
    triangles: int
    size: tuple[float, float, float]  # dimensions de la boîte englobante
    area: float
    volume: float
    centroid: tuple[float, float, float]  # centre de la surface, depuis le coin de la boîte
    spread: tuple[float, float, float]  # écart type de la surface autour de ce centre, par axe

    def extent(self) -> float:
        return max(self.size) if self.size else 0.0


@dataclass
class DuplicateGroup:
    files: list[FileEntry]
    identical: bool  # tous identiques octet pour octet

    @property
    def total(self) -> int:
        return sum(e.size for e in self.files)

    @property
    def recoverable(self) -> int:
        """Place libérée en ne gardant que le plus petit fichier du groupe."""
        return self.total - min(e.size for e in self.files)


@dataclass
class DuplicateReport:
    groups: list[DuplicateGroup] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    examined: int = 0
    skipped_zips: int = 0

    @property
    def recoverable(self) -> int:
        return sum(g.recoverable for g in self.groups)


def _read_mesh(kind: FileKind, data: bytes):
    if kind is FileKind.DRC:
        from .engine import decoder

        return decoder().decode(data)
    from .io import mesh_from_bytes

    return mesh_from_bytes(kind, data)


def fingerprint_bytes(data: bytes, kind: FileKind) -> Fingerprint:
    """Mesures d'un modèle (contenu d'un fichier STL, OBJ, PLY, 3MF ou DRC)."""
    digest = hashlib.blake2b(data, digest_size=16).hexdigest()
    mesh = _read_mesh(kind, data)
    mesh.validate()
    points = mesh.positions.astype(np.float64)
    low, high = points.min(axis=0), points.max(axis=0)
    size = high - low
    tris = points[mesh.faces] if len(mesh.faces) else np.zeros((0, 3, 3))
    cross = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]) if len(tris) else np.zeros((0, 3))
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    keep = areas > 0
    tris, areas, cross = tris[keep], areas[keep], cross[keep]
    area = float(areas.sum())
    if area > 0:
        centers = tris.mean(axis=1) - low
        centroid = (centers * areas[:, None]).sum(axis=0) / area
        spread = np.sqrt((((centers - centroid) ** 2) * areas[:, None]).sum(axis=0) / area)
        volume = abs(float(np.einsum("ij,ij->", tris[:, 0], cross))) / 6.0
    else:  # nuage de points : la répartition des points remplace celle de la surface
        centroid = (points - low).mean(axis=0)
        spread = (points - low).std(axis=0)
        volume = 0.0
    return Fingerprint(digest, int(len(points)), int(len(tris)), tuple(map(float, size)), area, volume,
                       tuple(map(float, centroid)), tuple(map(float, spread)))


def _fingerprint_file(path_text: str, kind_value: str) -> tuple[str, dict | None, str | None]:
    """Travail d'un processus : (chemin, mesures ou None, raison de l'échec)."""
    from .convert import reason_for

    try:
        with open(long_path(Path(path_text)), "rb") as f:
            data = f.read()
        return path_text, asdict(fingerprint_bytes(data, FileKind(kind_value))), None
    except Exception as exc:  # noqa: BLE001 - un fichier illisible ne doit pas arrêter la recherche
        return path_text, None, reason_for(exc)


def _close(a: float, b: float, tolerance: float, floor: float) -> bool:
    return abs(a - b) <= tolerance * max(abs(a), abs(b)) + floor


def same_model(a: Fingerprint, b: Fingerprint) -> bool:
    """Vrai si les deux mesures décrivent le même modèle, à l'arrondi de Draco près."""
    if a.digest == b.digest:
        return True
    if a.triangles != b.triangles or (a.triangles == 0 and a.vertices != b.vertices):
        return False
    extent = max(a.extent(), b.extent())
    if extent <= 0:
        return False
    step = SIZE_TOLERANCE * extent
    for x, y in zip(a.size + a.centroid + a.spread, b.size + b.centroid + b.spread):
        if abs(x - y) > step:
            return False
    return (_close(a.area, b.area, MEASURE_TOLERANCE, step * step)
            and _close(a.volume, b.volume, MEASURE_TOLERANCE, step * extent * extent * 1e-3))


class _Cache:
    """Mesures déjà faites, par chemin, taille et date de modification."""

    def __init__(self, path: Path | None):
        self._db = None
        if path is None:
            return
        try:
            self._db = sqlite3.connect(str(path), check_same_thread=False)
            self._db.execute("CREATE TABLE IF NOT EXISTS prints (path TEXT PRIMARY KEY, size INTEGER, "
                             "mtime REAL, version INTEGER, data TEXT)")
        except sqlite3.Error:
            self._db = None

    def get(self, entry: FileEntry) -> Fingerprint | None:
        if self._db is None:
            return None
        row = self._db.execute("SELECT size, mtime, version, data FROM prints WHERE path = ?",
                               (str(entry.path).lower(),)).fetchone()
        if row is None or row[0] != entry.size or row[1] != entry.mtime or row[2] != FINGERPRINT_VERSION:
            return None
        return _from_dict(json.loads(row[3]))

    def put(self, entry: FileEntry, value: Fingerprint) -> None:
        if self._db is None:
            return
        self._db.execute("INSERT OR REPLACE INTO prints VALUES (?, ?, ?, ?, ?)",
                         (str(entry.path).lower(), entry.size, entry.mtime, FINGERPRINT_VERSION,
                          json.dumps(asdict(value))))

    def close(self) -> None:
        if self._db is not None:
            self._db.commit()
            self._db.close()


def _from_dict(data: dict) -> Fingerprint:
    return Fingerprint(**{k: tuple(v) if isinstance(v, list) else v for k, v in data.items()})


def default_cache() -> Path:
    return data_dir() / "empreintes.sqlite"


def group(prints: dict[int, Fingerprint]) -> list[list[int]]:
    """Regroupe les numéros dont les mesures décrivent le même modèle (union de proches en proches)."""
    parent = {i: i for i in prints}

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_digest: dict[str, int] = {}
    buckets: dict[tuple, list[int]] = {}
    for i, fp in prints.items():
        if fp.digest in by_digest:
            parent[root(i)] = root(by_digest[fp.digest])
        else:
            by_digest[fp.digest] = i
        buckets.setdefault((fp.triangles, fp.vertices if fp.triangles == 0 else -1), []).append(i)
    for members in buckets.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda i: prints[i].area)
        for n, i in enumerate(members):
            a = prints[i]
            limit = a.area * (1 + 2 * MEASURE_TOLERANCE) + (SIZE_TOLERANCE * a.extent()) ** 2 * 2
            for j in members[n + 1:]:
                b = prints[j]
                if b.area > limit:
                    break
                if root(i) != root(j) and same_model(a, b):
                    parent[root(j)] = root(i)
    groups: dict[int, list[int]] = {}
    for i in prints:
        groups.setdefault(root(i), []).append(i)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def find_duplicates(
    entries: list[FileEntry],
    workers: int = 1,
    on_progress: Callable[[int, int], None] | None = None,
    stop: threading.Event | None = None,
    cache_path: Path | None | bool = True,
) -> DuplicateReport:
    """Cherche les doublons parmi les fichiers recensés (les ZIP sont laissés de côté)."""
    report = DuplicateReport()
    models = [e for e in entries if e.kind in KINDS]
    report.skipped_zips = sum(1 for e in entries if e.kind is FileKind.ZIP)
    cache = _Cache(default_cache() if cache_path is True else (cache_path or None))
    prints: dict[int, Fingerprint] = {}
    todo: list[int] = []
    for index, entry in enumerate(models):
        known = cache.get(entry)
        if known is not None:
            prints[index] = known
        else:
            todo.append(index)
    done = len(prints)
    if on_progress is not None:
        on_progress(done, len(models))

    def record(index: int, data: dict | None, reason: str | None) -> None:
        nonlocal done
        done += 1
        if data is None:
            report.failed.append((models[index].path, reason or "unreadable"))
        else:
            prints[index] = _from_dict(data)
            cache.put(models[index], prints[index])
        if on_progress is not None:
            on_progress(done, len(models))

    try:
        if workers <= 1 or len(todo) < 4:
            for index in todo:
                if stop is not None and stop.is_set():
                    break
                record(index, *_fingerprint_file(str(models[index].path), models[index].kind.value)[1:])
        else:
            from .batch import _single_threaded_children

            queue = list(reversed(todo))
            while queue and not (stop is not None and stop.is_set()):
                running: dict = {}
                try:
                    with _single_threaded_children(), ProcessPoolExecutor(max_workers=workers) as pool:
                        while queue or running:
                            while queue and len(running) < workers * 2 and not (stop is not None and stop.is_set()):
                                index = queue.pop()
                                running[pool.submit(_fingerprint_file, str(models[index].path),
                                                    models[index].kind.value)] = index
                            if not running:
                                break
                            finished, _ = wait(running, timeout=0.5, return_when=FIRST_COMPLETED)
                            for future in finished:
                                result = future.result()  # BrokenProcessPool si un processus est mort
                                record(running.pop(future), *result[1:])
                except BrokenProcessPool:
                    # Un processus est mort (mémoire) : les fichiers en cours sont comptés en échec,
                    # le reste repart dans un pool neuf.
                    for index in running.values():
                        record(index, None, "out_of_memory")
    finally:
        cache.close()
    report.examined = len(prints)
    for members in group(prints):
        files = [models[i] for i in members]
        identical = len({prints[i].digest for i in members}) == 1
        report.groups.append(DuplicateGroup(sorted(files, key=lambda e: (e.size, str(e.path).lower())), identical))
    report.groups.sort(key=lambda g: -g.recoverable)
    return report
