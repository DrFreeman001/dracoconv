"""Lecture des fichiers STEP pour l'aperçu : step_mesh.exe (OpenCascade natif) découpe en triangles.

L'outil natif tourne dans son propre processus, enfant de l'auxiliaire d'aperçu et donc dans le même
job Windows. Il écrit un maillage compact que l'on relit et vérifie ici.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
import numpy as np
from dracoconv.preview_rendering import MAX_FACES, MAX_VERTICES, DisplayMesh, prepare_arrays

STEP_TOOL = Path(__file__).resolve().parents[1] / 'windows' / 'preview' / 'build' / 'step' / 'step_mesh.exe'
MAGIC = b'DCMESH2\0'
# L’auxiliaire dispose de 90 s en tout (bridge.cpp) ; on garde de quoi démarrer Qt et dessiner.
TIMEOUT = 80
# Un assemblage STEP complet dépasse vite 100 Mo (Rat Rig V-Core 4.1 : 142 Mo, lu en 47 s avec 1,6 Gio).
MAX_INPUT = 200 * 1024 * 1024
_ERRORS = {2: 'Invalid STEP input', 3: 'STEP file has no surfaces', 4: 'STEP model exceeds preview limit',
           5: 'Cannot write STEP mesh', 6: 'STEP reader failed'}


def is_step(head: bytes) -> bool:
    return head.lstrip(b'\xef\xbb\xbf').lstrip(b' \t\r\n').startswith(b'ISO-10303-21')


def read_mesh_file(path: Path) -> DisplayMesh:
    data = Path(path).read_bytes()
    if len(data) < 16 or data[:8] != MAGIC:
        raise ValueError('Invalid STEP mesh')
    vertices, faces = (int(n) for n in np.frombuffer(data, '<u4', 2, 8))
    if not 0 < vertices <= MAX_VERTICES or not 0 < faces <= MAX_FACES:
        raise ValueError('Invalid STEP mesh counts')
    if len(data) != 16 + 15 * vertices + 12 * faces:
        raise ValueError('Truncated STEP mesh')
    points = np.frombuffer(data, '<f4', vertices * 3, 16).reshape(-1, 3)
    indices = np.frombuffer(data, '<u4', faces * 3, 16 + 12 * vertices).reshape(-1, 3)
    mesh = prepare_arrays(points, indices)
    # Couleur sRGB de chaque sommet, lue dans le fichier STEP (bleu par défaut pour les faces sans couleur).
    mesh.colors = np.frombuffer(data, np.uint8, vertices * 3, 16 + 12 * vertices + 12 * faces).reshape(-1, 3).copy()
    return mesh


def mesh_step(source: Path, output: Path, tool: Path = STEP_TOOL, timeout: float = TIMEOUT) -> DisplayMesh:
    """Découpe source en triangles ; le fichier intermédiaire output est supprimé après lecture."""
    tool, output = Path(tool), Path(output)
    if not tool.exists():
        raise ValueError('STEP reader is not installed')
    try:
        result = subprocess.run([str(tool), str(source), str(output)], capture_output=True, timeout=timeout,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError(_ERRORS.get(result.returncode, f'STEP reader failed ({result.returncode})'))
        return read_mesh_file(output)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('STEP reading took too long') from exc
    finally:
        for leftover in (output, output.with_name(output.name + '.part')):
            leftover.unlink(missing_ok=True)
