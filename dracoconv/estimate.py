"""Projection du gain de place : instantanée (ratios) puis affinée (échantillon réellement encodé)."""
from __future__ import annotations

import json
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

import numpy as np

from .config import config_dir
from .convert import VerifyError, encode_bytes
from .engine import EngineError
from .io import MODEL_KINDS, FileKind, detect_kind_from_bytes, load_mesh, mesh_from_bytes
from .io.paths import long_path
from .mesh import MeshReadError
from .quality import bits_for_tolerance
from .scan import FileEntry, Inventory
from .settings import EncodeSettings

SIZE_CLASS_BOUNDS = (1 << 20, 10 << 20, 100 << 20)  # 1 Mo, 10 Mo, 100 Mo
#: Marge appliquée quand rien n'a été mesuré (projection instantanée, classe non échantillonnée).
UNMEASURED_MARGIN = 0.30
_BOOTSTRAP_ROUNDS = 1000
_PERCENTILES = (1.0, 99.0)
_TYPICAL_EXTENT_MM = 100.0  # taille supposée d'un modèle quand seule une tolérance est connue
_CONVERTIBLE = MODEL_KINDS | {FileKind.ZIP}


def size_class(size: int) -> int:
    """Classe de taille : 0 sous 1 Mo, 1 de 1 à 10 Mo, 2 de 10 à 100 Mo, 3 au-delà."""
    return sum(1 for bound in SIZE_CLASS_BOUNDS if size >= bound)


def profile_key(settings: EncodeSettings) -> str:
    if settings.tolerance_mm is not None:
        return "tol"
    return "lossless" if settings.position_bits == 0 else f"q{settings.position_bits}"


def _shipped_ratios() -> dict:
    path = Path(__file__).parent / "data" / "ratios.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _user_ratios_file() -> Path:
    return config_dir() / "ratios.json"


def load_ratios() -> dict:
    """Ratios livrés, complétés par ceux mesurés chez l'utilisateur."""
    ratios = {k: dict(v) for k, v in _shipped_ratios().items() if not k.startswith("_")}
    path = _user_ratios_file()
    if path.exists():
        try:
            for kind, values in json.loads(path.read_text(encoding="utf-8")).items():
                ratios.setdefault(kind, {}).update(values)
        except (OSError, ValueError, AttributeError):
            pass
    return ratios


def save_ratios(ratios: dict) -> None:
    current = {}
    path = _user_ratios_file()
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
    for kind, values in ratios.items():
        current.setdefault(kind, {}).update(values)
    path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")


def ratio_for(ratios: dict, kind: FileKind, settings: EncodeSettings) -> float:
    """Ratio taille finale / taille d'origine pour ce type et ces réglages."""
    table = ratios.get(kind.value) or {}
    if not table:
        return 1.0
    key = profile_key(settings)
    if key in table:
        return float(table[key])
    bits = settings.position_bits
    if settings.tolerance_mm is not None:
        bits = bits_for_tolerance(_TYPICAL_EXTENT_MM, settings.tolerance_mm)
    lossless = float(table.get("lossless", 1.0))
    if bits == 0:
        return lossless
    known = sorted((int(k[1:]), float(v)) for k, v in table.items() if k[:1] == "q" and k[1:].isdigit())
    if not known:
        return lossless
    if bits <= known[0][0]:
        return known[0][1] * bits / known[0][0]
    xs = [b for b, _ in known] + [32]  # au-delà des bits connus, on tend vers le sans-perte
    ys = [r for _, r in known] + [max(lossless, known[-1][1])]
    return float(np.interp(bits, xs, ys))


@dataclass
class KindProjection:
    files: int = 0
    current_bytes: int = 0
    projected_bytes: int = 0
    low_bytes: int = 0
    high_bytes: int = 0


@dataclass
class Projection:
    current_bytes: int
    projected_bytes: int
    low_bytes: int
    high_bytes: int
    by_kind: dict[FileKind, KindProjection]
    method: Literal["instant", "sampled"]
    no_gain: list[Path] = field(default_factory=list)
    sampled_files: int = 0

    @property
    def saved_bytes(self) -> int:
        return self.current_bytes - self.projected_bytes

    @property
    def saved_pct(self) -> float:
        return 100.0 * self.saved_bytes / self.current_bytes if self.current_bytes else 0.0


def _convertible(inv: Inventory) -> list[FileEntry]:
    return [e for e in inv.entries if e.kind in _CONVERTIBLE and not (e.kind is FileKind.ZIP and e.archive_models == 0
                                                                      and e.archive_drc > 0)]


def _total(by_kind: dict[FileKind, KindProjection], method, **extra) -> Projection:
    return Projection(
        current_bytes=sum(k.current_bytes for k in by_kind.values()),
        projected_bytes=sum(k.projected_bytes for k in by_kind.values()),
        low_bytes=sum(k.low_bytes for k in by_kind.values()),
        high_bytes=sum(k.high_bytes for k in by_kind.values()),
        by_kind=by_kind,
        method=method,
        **extra,
    )


def instant(inv: Inventory, settings: EncodeSettings, ratios: dict | None = None) -> Projection:
    """Projection immédiate : volume de chaque type multiplié par son ratio connu."""
    ratios = load_ratios() if ratios is None else ratios
    by_kind: dict[FileKind, KindProjection] = {}
    for entry in _convertible(inv):
        kind = by_kind.setdefault(entry.kind, KindProjection())
        kind.files += 1
        kind.current_bytes += entry.size
    for kind, projection in by_kind.items():
        ratio = min(1.0, ratio_for(ratios, kind, settings))
        projection.projected_bytes = round(projection.current_bytes * ratio)
        projection.low_bytes = round(projection.projected_bytes * (1 - UNMEASURED_MARGIN))
        projection.high_bytes = min(projection.current_bytes, round(projection.projected_bytes * (1 + UNMEASURED_MARGIN)))
        projection.high_bytes = max(projection.high_bytes, projection.projected_bytes)
    return _total(by_kind, "instant")


def _encoded_size(entry: FileEntry, settings: EncodeSettings) -> tuple[int, bool]:
    """Taille qu'aurait le fichier après conversion, et s'il resterait tel quel faute de gain."""
    try:
        if entry.kind is FileKind.ZIP:
            return _encoded_zip_size(entry, settings)
        data, _ = encode_bytes(load_mesh(entry.path, entry.kind), settings)
    except (MeshReadError, EngineError, VerifyError, OSError, MemoryError, zipfile.BadZipFile):
        return entry.size, False  # illisible : le fichier resterait tel quel
    if len(data) >= entry.size:
        return entry.size, True
    return len(data), False


def _encoded_zip_size(entry: FileEntry, settings: EncodeSettings) -> tuple[int, bool]:
    """Taille de l'archive après conversion de ses modèles, comparée à l'archive actuelle."""
    size = entry.size
    converted = 0
    with zipfile.ZipFile(long_path(entry.path)) as archive:
        for info in archive.infolist():
            if info.is_dir() or info.flag_bits & 0x1:
                continue
            data = archive.read(info)
            kind = detect_kind_from_bytes(info.filename, data[:96])
            if kind not in MODEL_KINDS:
                continue
            try:
                encoded, _ = encode_bytes(mesh_from_bytes(kind, data), settings)
            except (MeshReadError, EngineError, VerifyError, MemoryError):
                continue
            if len(encoded) < len(data):
                size += len(encoded) - info.compress_size
                converted += 1
    if converted == 0 or size >= entry.size:
        return entry.size, True
    return size, False


def sampled(
    inv: Inventory,
    settings: EncodeSettings,
    per_class: int = 12,
    time_budget_s: float = 60.0,
    seed: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    stop: threading.Event | None = None,
) -> Projection:
    """Projection affinée : encode réellement un échantillon tiré au hasard, sans rien écrire."""
    rng = np.random.default_rng(seed)
    ratios = load_ratios()
    strata: dict[tuple[FileKind, int], list[FileEntry]] = {}
    for entry in _convertible(inv):
        strata.setdefault((entry.kind, size_class(entry.size)), []).append(entry)
    # Les strates les plus volumineuses d'abord : ce sont elles qui pèsent sur le résultat.
    order = sorted(strata, key=lambda key: -sum(e.size for e in strata[key]))
    picks = {key: [strata[key][i] for i in rng.permutation(len(strata[key]))[:per_class]] for key in order}
    measured: dict[tuple[FileKind, int], list[tuple[int, int]]] = {key: [] for key in order}
    no_gain: list[Path] = []
    total = sum(len(p) for p in picks.values())
    done = 0
    started = time.perf_counter()
    out_of_time = False
    # Tour par tour : chaque strate reçoit un fichier avant qu'une autre en reçoive un second.
    for rank in range(per_class):
        for key in order:
            if rank >= len(picks[key]):
                continue
            if done and (out_of_time or (stop is not None and stop.is_set())):
                continue
            entry = picks[key][rank]
            size, kept = _encoded_size(entry, settings)
            measured[key].append((entry.size, size))
            if kept:
                no_gain.append(entry.path)
            done += 1
            if on_progress is not None:
                on_progress(done, total)
            out_of_time = time.perf_counter() - started >= time_budget_s

    by_kind: dict[FileKind, KindProjection] = {}
    boot: dict[FileKind, np.ndarray] = {}
    learned: dict[str, list[tuple[int, int]]] = {}
    for key in order:
        kind, _ = key
        entries, pairs = strata[key], measured[key]
        bytes_total = sum(e.size for e in entries)
        projection = by_kind.setdefault(kind, KindProjection())
        projection.files += len(entries)
        projection.current_bytes += bytes_total
        rounds = boot.setdefault(kind, np.zeros(_BOOTSTRAP_ROUNDS))
        if not pairs:
            estimate = bytes_total * min(1.0, ratio_for(ratios, kind, settings))
            spread = rng.uniform(1 - UNMEASURED_MARGIN, 1 + UNMEASURED_MARGIN, _BOOTSTRAP_ROUNDS)
            rounds += np.minimum(estimate * spread, bytes_total)
        else:
            learned.setdefault(kind.value, []).extend(pairs)
            source = np.array([p[0] for p in pairs], dtype=np.float64)
            encoded = np.array([p[1] for p in pairs], dtype=np.float64)
            estimate = bytes_total * encoded.sum() / source.sum()
            if len(pairs) == len(entries):
                estimate = float(encoded.sum())  # strate entièrement mesurée : valeur exacte
                rounds += estimate
            elif len(pairs) == 1:
                spread = rng.uniform(1 - UNMEASURED_MARGIN, 1 + UNMEASURED_MARGIN, _BOOTSTRAP_ROUNDS)
                rounds += np.minimum(estimate * spread, bytes_total)
            else:
                draws = rng.integers(0, len(pairs), size=(_BOOTSTRAP_ROUNDS, len(pairs)))
                resampled = bytes_total * encoded[draws].sum(axis=1) / source[draws].sum(axis=1)
                # Un petit échantillon sous-estime la dispersion : on l'élargit en conséquence.
                widen = 1.0 + 2.0 / len(pairs)
                rounds += estimate + (resampled - estimate) * widen
        projection.projected_bytes += round(estimate)

    all_rounds = np.zeros(_BOOTSTRAP_ROUNDS)
    for kind, projection in by_kind.items():
        low, high = np.percentile(boot[kind], _PERCENTILES)
        projection.low_bytes = min(projection.projected_bytes, max(0, int(np.floor(low))))
        projection.high_bytes = max(projection.projected_bytes, int(np.ceil(high)))
        all_rounds += boot[kind]
    result = _total(by_kind, "sampled", no_gain=no_gain, sampled_files=done)
    if by_kind:
        low, high = np.percentile(all_rounds, _PERCENTILES)
        result.low_bytes = min(result.projected_bytes, max(0, int(np.floor(low))))
        result.high_bytes = max(result.projected_bytes, int(np.ceil(high)))
    if learned:
        key = profile_key(settings)
        save_ratios({
            kind: {key: sum(e for _, e in pairs) / sum(s for s, _ in pairs)}
            for kind, pairs in learned.items() if sum(s for s, _ in pairs)
        })
    return result
