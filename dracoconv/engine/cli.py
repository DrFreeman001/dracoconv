"""Moteur de référence : outils officiels draco_encoder / draco_decoder, lancés en sous-processus."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..io.obj import obj_to_bytes
from ..io.paths import long_path
from ..io.ply import ply_from_bytes, ply_to_bytes
from ..mesh import Mesh, MeshReadError
from ..settings import EncodeSettings, resolved
from .base import EngineError, prepare, unsupported_params

_SKIP_FLAGS = {"normal": "NORMAL", "texcoord": "TEX_COORD", "generic": "GENERIC"}
_TIMEOUT_S = 3600
_MAX_LEVEL_AT_30_BITS = 8


def find_binaries() -> tuple[Path, Path] | None:
    """Cherche draco_encoder et draco_decoder : %DRACOCONV_BIN%, dracoconv/bin, puis le PATH."""
    suffix = ".exe" if os.name == "nt" else ""
    folders = []
    if os.environ.get("DRACOCONV_BIN"):
        folders.append(Path(os.environ["DRACOCONV_BIN"]))
    folders.append(Path(__file__).resolve().parent.parent / "bin")
    for folder in folders:
        encoder, decoder = folder / f"draco_encoder{suffix}", folder / f"draco_decoder{suffix}"
        if encoder.is_file() and decoder.is_file():
            return encoder, decoder
    encoder, decoder = shutil.which("draco_encoder"), shutil.which("draco_decoder")
    if encoder and decoder:
        return Path(encoder), Path(decoder)
    return None


def _run(command: list[str]) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = subprocess.run(command, capture_output=True, timeout=_TIMEOUT_S, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EngineError("engine_error", str(exc)) from exc
    if done.returncode != 0:
        message = (done.stderr or done.stdout).decode("utf-8", "replace").strip()[-500:]
        raise EngineError("engine_error", message or f"code de retour {done.returncode}")


class CliEngine:
    name = "reference"
    supports = frozenset({
        "compression_level", "position_bits", "texcoord_bits", "normal_bits", "generic_bits",
        "skip_attributes", "point_cloud", "metadata", "preserve_polygons",
    })
    max_position_bits = 30

    def __init__(self, encoder: Path, decoder: Path):
        self.encoder, self.decoder = Path(encoder), Path(decoder)

    def can_encode(self, settings: EncodeSettings, max_extent: float) -> bool:
        return not unsupported_params(self, settings, max_extent)

    def _check(self, settings: EncodeSettings, max_extent: float) -> None:
        missing = unsupported_params(self, settings, max_extent)
        if missing:
            raise EngineError("engine_unavailable", f"non pris en charge par l'encodeur officiel : {sorted(missing)}")

    def _encode_file(self, source: Path, final: EncodeSettings, folder: Path, skip: bool) -> bytes:
        target = folder / "out.drc"
        level = final.compression_level
        if final.position_bits >= 30:
            # Mesuré sur Draco 1.5.9 : à 30 bits, l'encodeur plante aux niveaux 9 et 10.
            level = min(level, _MAX_LEVEL_AT_30_BITS)
        command = [
            str(self.encoder), "-i", str(source), "-o", str(target),
            "-cl", str(level), "-qp", str(final.position_bits),
            "-qt", str(final.texcoord_bits), "-qn", str(final.normal_bits), "-qg", str(final.generic_bits),
        ]
        if final.point_cloud:
            command.append("-point_cloud")
        if final.metadata:
            command.append("--metadata")
        if final.preserve_polygons:
            command.append("-preserve_polygons")
        if skip:
            for attribute in sorted(final.skip_attributes):
                if attribute in _SKIP_FLAGS:
                    command += ["--skip", _SKIP_FLAGS[attribute]]
        _run(command)
        if not target.is_file():
            raise EngineError("engine_error", "l'encodeur n'a produit aucun fichier")
        return target.read_bytes()

    def encode(self, mesh: Mesh, settings: EncodeSettings) -> bytes:
        self._check(settings, mesh.max_extent())
        mesh, final = prepare(mesh, settings)
        with tempfile.TemporaryDirectory(prefix="dracoconv-") as tmp:
            folder = Path(tmp)
            if mesh.texcoords is not None:
                # Le lecteur PLY de Draco ignore les coordonnées de texture ; l'OBJ les porte.
                source = folder / "in.obj"
                source.write_bytes(obj_to_bytes(mesh))
            else:
                source = folder / "in.ply"
                source.write_bytes(ply_to_bytes(mesh))
            return self._encode_file(source, final, folder, skip=False)

    def encode_source(self, path: Path, settings: EncodeSettings, max_extent: float = 0.0) -> bytes:
        """Encode le fichier OBJ/PLY d'origine tel quel : seul chemin qui honore
        ``preserve_polygons``, ``metadata`` et ``generic_bits``."""
        self._check(settings, max_extent)
        final = resolved(settings, max_extent)
        path = Path(path)
        with tempfile.TemporaryDirectory(prefix="dracoconv-") as tmp:
            folder = Path(tmp)
            # Copie sous un nom simple : l'outil officiel n'ouvre pas les chemins accentués ou longs.
            source = folder / ("in" + path.suffix.lower())
            shutil.copyfile(long_path(path), source)
            return self._encode_file(source, final, folder, skip=True)

    def decode(self, data: bytes) -> Mesh:
        with tempfile.TemporaryDirectory(prefix="dracoconv-") as tmp:
            folder = Path(tmp)
            source, target = folder / "in.drc", folder / "out.ply"
            source.write_bytes(data)
            try:
                _run([str(self.decoder), "-i", str(source), "-o", str(target)])
            except EngineError as exc:
                raise EngineError("unreadable", str(exc)) from exc
            if not target.is_file():
                raise EngineError("unreadable", "le décodeur n'a produit aucun fichier")
            try:
                mesh = ply_from_bytes(target.read_bytes())
            except MeshReadError as exc:
                raise EngineError("unreadable", str(exc)) from exc
        mesh.source_kind, mesh.source_size = "drc", len(data)
        return mesh
