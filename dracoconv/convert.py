"""Conversion d'un fichier isolé, avec vérification avant écriture."""
from __future__ import annotations

import errno
import os
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .engine import EngineError, decoder, select_engine
from .engine.base import prepare
from .io import LOSSY_KINDS, MODEL_KINDS, FileKind, detect_kind, detect_kind_from_bytes, mesh_from_bytes, mesh_to_bytes
from .io.archive import EncryptedZipError, rewrite_zip
from .io.paths import long_path
from .io.sniff import kind_from_name
from .mesh import Mesh, MeshReadError
from .quality import QualityReport, error_bound_mm, float_floor_mm, measure
from .settings import EncodeSettings

State = Literal["done", "skipped", "failed"]
#: Raisons qui écartent un fichier sans que ce soit une erreur.
SKIP_REASONS = {"empty", "compiler_obj", "no_gain", "encrypted_zip", "zip_without_models"}
_SOURCE_KINDS = {FileKind.OBJ, FileKind.PLY}
_MODEL_SUFFIXES = {".stl", ".obj", ".ply", ".3mf"}
_ERROR_DISK_FULL_WINDOWS = 112
_ERROR_SHARING_VIOLATION = 32


@dataclass
class FileResult:
    src: Path
    dst: Path | None
    state: State
    reason: str | None
    size_before: int
    size_after: int | None = None
    duration_s: float = 0.0
    quality: QualityReport | None = None
    lossy_source: bool = False
    note: str | None = None  # information qui ne change pas l'état (ex. corbeille indisponible)


class VerifyError(Exception):
    """Le fichier produit ne redonne pas la géométrie attendue."""


def reason_for(exc: BaseException) -> str:
    """Code de raison correspondant à une exception d'accès aux fichiers ou de moteur."""
    if isinstance(exc, MeshReadError):
        return exc.reason
    if isinstance(exc, EngineError):
        return exc.reason
    if isinstance(exc, VerifyError):
        return "verify_failed"
    if isinstance(exc, MemoryError):
        return "out_of_memory"
    if isinstance(exc, FileExistsError):
        return "exists"
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) == _ERROR_DISK_FULL_WINDOWS:
            return "disk_full"
        if getattr(exc, "winerror", None) == _ERROR_SHARING_VIOLATION:
            return "locked"
        if isinstance(exc, PermissionError):
            return "access_denied"
        return "unreadable"
    return "engine_error"


def verify(source: Mesh, encoded: bytes, settings: EncodeSettings, exact_triangles: bool = True) -> tuple[bool, QualityReport]:
    """Décode ``encoded`` et le compare à ``source`` selon les réglages annoncés.

    ``exact_triangles=False`` sert quand l'encodeur a lu lui-même le fichier d'origine :
    sa découpe des polygones peut différer de la nôtre, on compare alors les sommets.
    """
    expected, final = prepare(source, settings)
    try:
        decoded = decoder().decode(encoded)
    except EngineError:
        empty = QualityReport(float("inf"), float("inf"), expected.triangle_count(), 0, 0, 0, False)
        return False, empty
    report = measure(expected, decoded, integrity=False)
    bits = final.position_bits
    if bits == 0 and exact_triangles:
        return report.identical, report
    if bits == 0:
        ok = report.max_error_mm <= float_floor_mm(expected) and decoded.triangle_count() == expected.triangle_count()
        return ok, report
    ok = report.max_error_mm <= error_bound_mm(expected, bits) and decoded.triangle_count() <= expected.triangle_count()
    if expected.triangle_count() and decoded.triangle_count() == 0:
        ok = False
    return ok, report


def _wants_source_file(settings: EncodeSettings) -> bool:
    return settings.preserve_polygons or settings.metadata or settings.generic_bits != EncodeSettings().generic_bits


def encode_bytes(
    mesh: Mesh,
    settings: EncodeSettings,
    prefer_engine: str | None = None,
    source_path: Path | None = None,
    source_kind: FileKind | None = None,
) -> tuple[bytes, QualityReport]:
    """Encode et vérifie en mémoire. Lève ``EngineError`` ou ``VerifyError``."""
    extent = mesh.max_extent()
    engine = select_engine(settings, prefer_engine, extent)
    from_source = (
        source_path is not None and source_kind in _SOURCE_KINDS
        and _wants_source_file(settings) and hasattr(engine, "encode_source")
    )
    if from_source:
        data = engine.encode_source(source_path, settings, extent)
    else:
        data = engine.encode(mesh, settings)
    ok, report = verify(mesh, data, settings, exact_triangles=not from_source)
    if not ok:
        raise VerifyError(f"écart {report.max_error_mm:.6g} mm, {report.triangles_after}/{report.triangles_before} triangles")
    return data, report


def _exists(path: Path) -> bool:
    return os.path.lexists(long_path(path))


def _open_part(path: Path):
    return open(long_path(path), "wb")


def write_atomic(dst: Path, data: bytes, mtime: float | None = None) -> None:
    """Écrit dans ``dst.part`` puis renomme ; ne remplace jamais un fichier existant."""
    dst = Path(dst)
    if _exists(dst):
        raise FileExistsError(str(dst))
    os.makedirs(long_path(dst.parent), exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    try:
        with _open_part(part) as f:
            f.write(data)
        if mtime is not None:
            os.utime(long_path(part), (mtime, mtime))
        os.rename(long_path(part), long_path(dst))  # échoue si dst est apparu entre-temps
    except BaseException:
        try:
            os.remove(long_path(part))
        except OSError:
            pass
        raise


def output_path(src: Path, target_ext: str, dest_dir: Path, taken: set[Path]) -> Path:
    """Nom du fichier produit, sans jamais viser un fichier existant ni un nom déjà attribué."""
    src, dest_dir = Path(src), Path(dest_dir)
    stem = src.stem
    if target_ext != ".drc" and Path(stem).suffix.lower() in _MODEL_SUFFIXES:
        stem = Path(stem).stem  # modele.stl.drc -> modele
    candidates = [dest_dir / (stem + target_ext)]
    fallback_stem = src.name if target_ext == ".drc" else stem
    if target_ext == ".drc":
        candidates.append(dest_dir / (src.name + target_ext))  # modele.stl.drc
    counter = 1
    while True:
        for candidate in candidates:
            if candidate not in taken and not _exists(candidate):
                taken.add(candidate)
                return candidate
        candidates = [dest_dir / f"{fallback_stem} ({counter}){target_ext}"]
        counter += 1


def _result(src, dst, state, reason, size_before, started, **extra) -> FileResult:
    return FileResult(Path(src), dst, state, reason, size_before, duration_s=time.perf_counter() - started, **extra)


def _failure(src, exc: BaseException, size_before: int, started: float, **extra) -> FileResult:
    reason = reason_for(exc)
    state = "skipped" if reason in SKIP_REASONS else "failed"
    return _result(src, None, state, reason, size_before, started, **extra)


def _read(path: Path) -> tuple[bytes, float]:
    text = long_path(path)
    with open(text, "rb") as f:
        data = f.read()
    return data, os.stat(text).st_mtime


def encode_file(
    src: Path,
    dst: Path,
    settings: EncodeSettings,
    prefer_engine: str | None = None,
    skip_if_no_gain: bool = True,
) -> FileResult:
    """Convertit un modèle en .drc. L'original n'est jamais modifié."""
    started = time.perf_counter()
    src, dst = Path(src), Path(dst)
    size_before, lossy = 0, False
    try:
        if _exists(dst):
            raise FileExistsError(str(dst))
        raw, mtime = _read(src)
        size_before = len(raw)
        kind = detect_kind(src)
        lossy = kind in LOSSY_KINDS
        mesh = mesh_from_bytes(kind, raw)
        del raw
        mesh.source_path = src
        data, report = encode_bytes(mesh, settings, prefer_engine, source_path=src, source_kind=kind)
        if skip_if_no_gain and len(data) >= size_before:
            return _result(src, None, "skipped", "no_gain", size_before, started, quality=report, lossy_source=lossy)
        write_atomic(dst, data, mtime)
        return _result(src, dst, "done", None, size_before, started, size_after=len(data), quality=report,
                       lossy_source=lossy)
    except (MeshReadError, EngineError, VerifyError, OSError, MemoryError) as exc:
        return _failure(src, exc, size_before, started, lossy_source=lossy)


def decode_bytes(data: bytes, fmt: Literal["stl", "obj", "ply"]) -> bytes:
    """Décode un .drc vers le format demandé et vérifie que le résultat se relit à l'identique."""
    mesh = decoder().decode(data)
    mesh.validate()
    out = mesh_to_bytes(mesh, fmt)
    back = mesh_from_bytes(kind_from_name("x." + fmt), out)
    if not measure(mesh, back, integrity=False).identical:
        raise VerifyError("le fichier décodé ne se relit pas à l'identique")
    return out


def decode_file(src: Path, dst: Path, fmt: Literal["stl", "obj", "ply"]) -> FileResult:
    """Convertit un .drc en STL binaire, OBJ ou PLY."""
    started = time.perf_counter()
    src, dst = Path(src), Path(dst)
    size_before = 0
    try:
        if _exists(dst):
            raise FileExistsError(str(dst))
        raw, mtime = _read(src)
        size_before = len(raw)
        out = decode_bytes(raw, fmt)
        write_atomic(dst, out, mtime)
        return _result(src, dst, "done", None, size_before, started, size_after=len(out))
    except (MeshReadError, EngineError, VerifyError, OSError, MemoryError) as exc:
        return _failure(src, exc, size_before, started)


def zip_output_path(src: Path, tag: str, dest_dir: Path, taken: set[Path]) -> Path:
    """``pack.zip`` -> ``pack.<tag>.zip`` ; ``pack.drc.zip`` -> ``pack.<tag>.zip``."""
    src, dest_dir = Path(src), Path(dest_dir)
    stem = src.stem
    if Path(stem).suffix.lower() in _MODEL_SUFFIXES | {".drc"}:
        stem = Path(stem).stem
    counter = 0
    while True:
        name = f"{stem}.{tag}.zip" if counter == 0 else f"{stem} ({counter}).{tag}.zip"
        candidate = dest_dir / name
        if candidate not in taken and not _exists(candidate):
            taken.add(candidate)
            return candidate
        counter += 1


def _swap_suffix(name: str, new_suffix: str) -> str:
    """Nom d'une entrée d'archive après conversion : a/m.stl -> a/m.drc ; a/m.stl.drc -> a/m.stl."""
    folder, _, base = name.rpartition("/")
    stem = base.rsplit(".", 1)[0]
    if new_suffix != ".drc" and "." in stem and "." + stem.rsplit(".", 1)[1].lower() in _MODEL_SUFFIXES:
        stem = stem.rsplit(".", 1)[0]
    return (folder + "/" if folder else "") + stem + new_suffix


def _convert_zip(src: Path, dst: Path, transform, started: float, lossy: list) -> FileResult:
    size_before = 0
    try:
        stat = os.stat(long_path(src))
        size_before = stat.st_size
        report = rewrite_zip(src, dst, transform)
        if report.converted == 0:
            return _result(src, None, "skipped", "no_gain", size_before, started)
        os.utime(long_path(dst), (stat.st_mtime, stat.st_mtime))
        note = ", ".join(f"{name}: {reason}" for name, reason in report.skipped.items()) or None
        return _result(src, dst, "done", None, size_before, started, size_after=os.stat(long_path(dst)).st_size,
                       lossy_source=bool(lossy), note=note)
    except EncryptedZipError:
        return _result(src, None, "skipped", "encrypted_zip", size_before, started)
    except (zipfile.BadZipFile, NotImplementedError):
        return _result(src, None, "failed", "unreadable", size_before, started)
    except (OSError, MemoryError) as exc:
        return _failure(src, exc, size_before, started)


def encode_zip(src: Path, dst: Path, settings: EncodeSettings, prefer_engine: str | None = None) -> FileResult:
    """Écrit une nouvelle archive où chaque modèle est converti en .drc ; le reste est recopié."""
    started = time.perf_counter()
    lossy: list[str] = []

    def transform(name: str, data: bytes):
        kind = detect_kind_from_bytes(name, data[:96])
        if kind not in MODEL_KINDS:
            return None
        try:
            encoded, _ = encode_bytes(mesh_from_bytes(kind, data), settings, prefer_engine)
        except (MeshReadError, EngineError, VerifyError, MemoryError):
            return None  # modèle illisible ou invérifiable : recopié tel quel
        if len(encoded) >= len(data):
            return None
        if kind in LOSSY_KINDS:
            lossy.append(name)
        return _swap_suffix(name, ".drc"), encoded

    return _convert_zip(Path(src), Path(dst), transform, started, lossy)


def decode_zip(src: Path, dst: Path, fmt: Literal["stl", "obj", "ply"]) -> FileResult:
    """Écrit une nouvelle archive où chaque .drc est reconverti dans le format demandé."""
    started = time.perf_counter()

    def transform(name: str, data: bytes):
        if kind_from_name(name) is not FileKind.DRC:
            return None
        try:
            return _swap_suffix(name, "." + fmt), decode_bytes(data, fmt)
        except (MeshReadError, EngineError, VerifyError, MemoryError):
            return None

    return _convert_zip(Path(src), Path(dst), transform, started, [])
