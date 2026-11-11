"""Moteur intégré : bibliothèque DracoPy, dans le processus, sans fichier temporaire."""
from __future__ import annotations

import numpy as np

from ..mesh import Mesh
from ..settings import EncodeSettings
from .base import EngineError, prepare, unsupported_params


def _array(value, columns: int | None = None) -> np.ndarray | None:
    if value is None:
        return None
    array = np.asarray(value)
    if array.size == 0:
        return None
    return array.reshape(-1, columns) if columns else array


class DracoPyEngine:
    name = "dracopy"
    #: Paramètres dont l'effet est prouvé par les tests de ce moteur.
    supports = frozenset({
        "compression_level", "position_bits", "texcoord_bits", "normal_bits",
        "skip_attributes", "point_cloud", "preserve_order",
    })
    #: DracoPy échoue à 30 bits (allocation mémoire) ; 29 est le maximum vérifié.
    max_position_bits = 29

    def can_encode(self, settings: EncodeSettings, max_extent: float) -> bool:
        return not unsupported_params(self, settings, max_extent)

    def encode(self, mesh: Mesh, settings: EncodeSettings) -> bytes:
        import DracoPy

        missing = unsupported_params(self, settings, mesh.max_extent())
        if missing:
            raise EngineError("engine_unavailable", f"non pris en charge par DracoPy : {sorted(missing)}")
        mesh, final = prepare(mesh, settings)
        options = dict(
            quantization_bits=final.position_bits,
            compression_level=final.compression_level,
            preserve_order=final.preserve_order,
        )
        if mesh.colors is not None:
            options["colors"] = np.ascontiguousarray(mesh.colors, dtype=np.uint8)
        if mesh.texcoords is not None:
            options["tex_coord"] = np.ascontiguousarray(mesh.texcoords, dtype=np.float64)
            if final.texcoord_bits:
                options["tex_coord_quantization_bits"] = final.texcoord_bits
        if mesh.normals is not None:
            options["normals"] = np.ascontiguousarray(mesh.normals, dtype=np.float64)
            if final.normal_bits:
                options["normal_quantization_bits"] = final.normal_bits
        faces = mesh.faces if len(mesh.faces) else None
        try:
            return bytes(DracoPy.encode(mesh.positions, faces, **options))
        except MemoryError as exc:
            raise EngineError("out_of_memory", str(exc)) from exc
        except Exception as exc:
            raise EngineError("engine_error", str(exc)) from exc

    def decode(self, data: bytes) -> Mesh:
        import DracoPy

        try:
            decoded = DracoPy.decode(data)
        except Exception as exc:
            raise EngineError("unreadable", str(exc)) from exc
        positions = np.asarray(decoded.points, dtype=np.float32).reshape(-1, 3)
        faces = getattr(decoded, "faces", None)
        faces = np.zeros((0, 3), np.uint32) if faces is None else np.asarray(faces, dtype=np.uint32).reshape(-1, 3)
        mesh = Mesh(positions, faces, source_kind="drc", source_size=len(data))
        count = len(positions)
        normals = _array(getattr(decoded, "normals", None), 3)
        if normals is not None and len(normals) == count:
            mesh.normals = normals.astype(np.float32)
        texcoords = _array(getattr(decoded, "tex_coord", None))
        if texcoords is not None and len(texcoords) == count:
            mesh.texcoords = texcoords.reshape(count, -1)[:, :2].astype(np.float32)
        colors = _array(getattr(decoded, "colors", None))
        if colors is not None and len(colors) == count:
            mesh.colors = colors.reshape(count, -1).astype(np.uint8)
        return mesh
