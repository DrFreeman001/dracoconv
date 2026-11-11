"""Archives ZIP : inventaire sans extraction et réécriture entrée par entrée."""
from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable

from .paths import long_path
from .sniff import MODEL_KINDS, FileKind, kind_from_name

_LISTED = MODEL_KINDS | {FileKind.DRC}
_ENCRYPTED_FLAG = 0x1


def list_models(zip_path: Path) -> list[tuple[str, FileKind, int, int]]:
    """Modèles et fichiers .drc d'une archive : nom, type, taille décompressée, taille compressée.

    Lève ``zipfile.BadZipFile`` ou ``OSError`` si l'archive est illisible.
    """
    found = []
    with zipfile.ZipFile(long_path(zip_path)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            kind = kind_from_name(info.filename)
            if kind in _LISTED:
                found.append((info.filename, kind, info.file_size, info.compress_size))
    return found


class EncryptedZipError(Exception):
    """Archive protégée par mot de passe."""


@dataclass
class ZipReport:
    converted: int = 0
    copied: int = 0
    skipped: dict[str, str] = field(default_factory=dict)  # nom de l'entrée -> raison


def is_unsafe_name(name: str) -> bool:
    """Vrai si l'entrée sortirait du dossier de destination une fois extraite."""
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        return True
    return ".." in normalized.split("/")


def _copy_info(info: zipfile.ZipInfo, name: str) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(name, date_time=info.date_time)
    entry.external_attr = info.external_attr
    return entry


def rewrite_zip(src: Path, dst: Path, transform: Callable[[str, bytes], "tuple[str, bytes] | None"]) -> ZipReport:
    """Recopie ``src`` vers ``dst`` en passant chaque fichier par ``transform``.

    ``transform(nom, contenu)`` rend ``(nouveau nom, nouveau contenu)`` pour une entrée convertie,
    ou ``None`` pour la recopier telle quelle. ``dst`` est écrit en ``.part`` puis renommé ;
    il n'est pas créé si aucune entrée n'a été convertie. ``src`` n'est jamais modifié.
    """
    src, dst = Path(src), Path(dst)
    if os.path.lexists(long_path(dst)):
        raise FileExistsError(str(dst))
    report = ZipReport()
    part = dst.with_name(dst.name + ".part")
    try:
        with zipfile.ZipFile(long_path(src)) as source:
            infos = source.infolist()
            if any(info.flag_bits & _ENCRYPTED_FLAG for info in infos):
                raise EncryptedZipError(str(src))
            original_names = {info.filename for info in infos}
            used: set[str] = set()
            os.makedirs(long_path(dst.parent), exist_ok=True)
            with zipfile.ZipFile(long_path(part), "w", zipfile.ZIP_DEFLATED) as target:
                for info in infos:
                    name = info.filename
                    if is_unsafe_name(name):
                        report.skipped[name] = "unsafe_zip_entry"
                        continue
                    if info.is_dir():
                        target.writestr(_copy_info(info, name), b"")
                        continue
                    data = source.read(info)
                    converted = None
                    if name.lower().endswith(".zip"):
                        report.skipped[name] = "nested_zip"  # recopiée telle quelle
                    else:
                        converted = transform(name, data)
                    if converted is None:
                        stored = info.compress_type == zipfile.ZIP_STORED
                        target.writestr(
                            _copy_info(info, name), data,
                            compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED,
                        )
                        used.add(name)
                        if name not in report.skipped:
                            report.copied += 1
                        continue
                    new_name, new_data = converted
                    if new_name in used or (new_name in original_names and new_name != name):
                        new_name = name + PurePosixPath(new_name).suffix  # modele.stl.drc
                    # Contenu déjà compressé : le stocker tel quel évite un travail inutile.
                    target.writestr(_copy_info(info, new_name), new_data, compress_type=zipfile.ZIP_STORED)
                    used.add(new_name)
                    report.converted += 1
        if report.converted == 0:
            os.remove(long_path(part))
            return report
        os.rename(long_path(part), long_path(dst))
    except BaseException:
        try:
            os.remove(long_path(part))
        except OSError:
            pass
        raise
    return report
