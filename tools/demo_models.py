"""Modèles de démonstration pour les captures d'écran (dracoconv et explorer-draco-step-preview).

Usage : python tools/demo_models.py <dossier> [--collection]
- sans option : une vitrine de formats (STL, OBJ, PLY, 3MF Bambu multicolore, GLB, DRC) ;
- avec --collection : en plus, une petite collection de modèles plus lourds, avec des doublons, pour montrer
  l'estimation du gain et la recherche des doublons.
Tout est généré : aucun modèle tiers.
"""
from __future__ import annotations

import argparse
import io
import math
import shutil
import zipfile
from pathlib import Path

import numpy as np


# -- formes ------------------------------------------------------------------------------------------------------


def revolve(profile: list[tuple[float, float]], segments: int = 96) -> tuple[np.ndarray, np.ndarray]:
    """Surface de révolution autour de Z, fermée en haut et en bas. ``profile`` : (rayon, z) de bas en haut."""
    rings = len(profile)
    angles = np.linspace(0, 2 * np.pi, segments, endpoint=False)
    pts = [(r * np.cos(a), r * np.sin(a), z) for r, z in profile for a in angles]
    pts += [(0, 0, profile[0][1]), (0, 0, profile[-1][1])]
    faces = []
    for i in range(rings - 1):
        for j in range(segments):
            a, b = i * segments + j, i * segments + (j + 1) % segments
            c, d = a + segments, b + segments
            faces += [(a, b, d), (a, d, c)]
    bottom, top = rings * segments, rings * segments + 1
    for j in range(segments):
        faces.append((bottom, (j + 1) % segments, j))
        last = (rings - 1) * segments
        faces.append((top, last + j, last + (j + 1) % segments))
    return np.array(pts, dtype=np.float32), np.array(faces, dtype=np.uint32)


def extrude(outline: np.ndarray, height: float, layers: int = 1, twist_deg: float = 0.0,
            scale_top: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Extrusion d'un contour étoilé autour de l'origine (fermé par des éventails), avec torsion possible."""
    n = len(outline)
    pts, faces = [], []
    for k in range(layers + 1):
        t = k / layers
        angle = math.radians(twist_deg) * t
        scale = 1 + (scale_top - 1) * t
        c, s = math.cos(angle), math.sin(angle)
        for x, y in outline:
            pts.append(((x * c - y * s) * scale, (x * s + y * c) * scale, height * t))
    for k in range(layers):
        for j in range(n):
            a, b = k * n + j, k * n + (j + 1) % n
            faces += [(a, b, b + n), (a, b + n, a + n)]
    bottom, top = len(pts), len(pts) + 1
    pts += [(0, 0, 0), (0, 0, height)]
    for j in range(n):
        faces.append((bottom, (j + 1) % n, j))
        faces.append((top, layers * n + j, layers * n + (j + 1) % n))
    return np.array(pts, dtype=np.float32), np.array(faces, dtype=np.uint32)


def gear_outline(teeth: int = 18, radius: float = 30.0, depth: float = 4.0, steps: int = 8) -> np.ndarray:
    pts = []
    for i in range(teeth * steps):
        a = 2 * np.pi * i / (teeth * steps)
        phase = (i % steps) / steps
        r = radius + (depth if 0.15 < phase < 0.6 else 0.0)
        pts.append((r * np.cos(a), r * np.sin(a)))
    return np.array(pts)


def tube(curve: np.ndarray, radius: float, sides: int = 24) -> tuple[np.ndarray, np.ndarray]:
    """Tube fermé le long d'une courbe fermée."""
    n = len(curve)
    tangents = np.roll(curve, -1, axis=0) - np.roll(curve, 1, axis=0)
    tangents /= np.linalg.norm(tangents, axis=1, keepdims=True)
    helper = np.array([0.0, 0.0, 1.0])
    normal = np.cross(tangents, helper)
    normal /= np.linalg.norm(normal, axis=1, keepdims=True)
    binormal = np.cross(tangents, normal)
    angles = np.linspace(0, 2 * np.pi, sides, endpoint=False)
    pts = (curve[:, None, :] + radius * (np.cos(angles)[None, :, None] * normal[:, None, :]
                                         + np.sin(angles)[None, :, None] * binormal[:, None, :])).reshape(-1, 3)
    faces = []
    for i in range(n):
        for j in range(sides):
            a, b = i * sides + j, i * sides + (j + 1) % sides
            c, d = ((i + 1) % n) * sides + j, ((i + 1) % n) * sides + (j + 1) % sides
            faces += [(a, c, d), (a, d, b)]
    return pts.astype(np.float32), np.array(faces, dtype=np.uint32)


def torus_knot(p: int = 2, q: int = 3, scale: float = 22.0, samples: int = 600, radius: float = 4.5,
               sides: int = 28):
    t = np.linspace(0, 2 * np.pi, samples, endpoint=False)
    r = np.cos(q * t) + 2
    curve = np.stack([r * np.cos(p * t), r * np.sin(p * t), -np.sin(q * t)], axis=1) * scale / 3
    pts, faces = tube(curve, radius, sides)
    pts[:, 2] -= pts[:, 2].min()
    return pts, faces


def sphere(subdivisions: int, radius: float):
    import trimesh

    s = trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)
    pts = np.asarray(s.vertices, dtype=np.float32)
    pts[:, 2] += radius
    return pts, np.asarray(s.faces, dtype=np.uint32)


def torus(major: float = 22.0, minor: float = 7.0, rings: int = 96, sides: int = 48):
    t = np.linspace(0, 2 * np.pi, rings, endpoint=False)
    curve = np.stack([major * np.cos(t), major * np.sin(t), np.zeros_like(t)], axis=1)
    pts, faces = tube(curve, minor, sides)
    pts[:, 2] += minor
    return pts, faces


def vase(height: float = 80.0):
    zs = np.linspace(0, height, 40)
    profile = [(14 + 9 * math.sin(z / height * math.pi * 1.6) + 4 * (z / height), z) for z in zs]
    return revolve(profile, 120)


def twisted_tower(height: float = 90.0):
    outline = np.array([(18 * math.cos(a) * (1 + 0.12 * math.cos(6 * a)), 18 * math.sin(a) * (1 + 0.12 * math.cos(6 * a)))
                        for a in np.linspace(0, 2 * np.pi, 72, endpoint=False)])
    return extrude(outline, height, layers=90, twist_deg=120, scale_top=0.6)


def gear():
    return extrude(gear_outline(), 8.0)


# -- écriture ----------------------------------------------------------------------------------------------------


def write_stl(path: Path, pts: np.ndarray, faces: np.ndarray) -> None:
    tris = pts[faces].astype("<f4")
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    record = np.zeros(len(tris), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    record["n"], record["v"] = normals, tris
    with open(path, "wb") as f:
        f.write(b"demo".ljust(80, b"\0") + np.uint32(len(tris)).tobytes() + record.tobytes())


def write_obj(path: Path, pts: np.ndarray, faces: np.ndarray, colors: np.ndarray | None = None) -> None:
    lines = []
    for i, p in enumerate(pts):
        extra = "" if colors is None else " " + " ".join(f"{c / 255:.3f}" for c in colors[i][:3])
        lines.append(f"v {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}{extra}")
    lines += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in faces]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def rainbow(pts: np.ndarray) -> np.ndarray:
    z = (pts[:, 2] - pts[:, 2].min()) / max(1e-9, np.ptp(pts[:, 2]))
    angle = np.arctan2(pts[:, 1], pts[:, 0])
    hue = (angle / (2 * np.pi) + 0.5 + z * 0.3) % 1.0
    # Arc-en-ciel doux : trois cosinus décalés d'un tiers de tour.
    rgb = 0.5 + 0.5 * np.cos(2 * np.pi * (hue[:, None] + np.array([0.0, 2 / 3, 1 / 3])[None, :]))
    return np.hstack([(rgb * 210 + 30).astype(np.uint8), np.full((len(pts), 1), 255, np.uint8)])


def write_ply(path: Path, pts: np.ndarray, faces: np.ndarray, colors: np.ndarray) -> None:
    header = (f"ply\nformat binary_little_endian 1.0\nelement vertex {len(pts)}\nproperty float x\nproperty float y\n"
              f"property float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\n"
              f"element face {len(faces)}\nproperty list uchar int vertex_indices\nend_header\n").encode()
    vertex = np.zeros(len(pts), dtype=[("p", "<f4", 3), ("c", "u1", 3)])
    vertex["p"], vertex["c"] = pts, colors[:, :3]
    face = np.zeros(len(faces), dtype=[("n", "u1"), ("i", "<i4", 3)])
    face["n"], face["i"] = 3, faces
    path.write_bytes(header + vertex.tobytes() + face.tobytes())


def write_glb(path: Path, pts: np.ndarray, faces: np.ndarray, color=(0.15, 0.55, 0.9)) -> None:
    import trimesh

    mesh = trimesh.Trimesh(pts.astype(np.float64), faces, process=False)
    mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=[*color, 1.0], metallicFactor=0.1, roughnessFactor=0.6))
    # glTF a Y vertical : la visionneuse le remet debout (Z vertical).
    mesh.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    path.write_bytes(mesh.export(file_type="glb"))


def _model_xml(pts: np.ndarray, faces: np.ndarray) -> str:
    vertices = "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in pts)
    triangles = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces)
    return f"<mesh><vertices>{vertices}</vertices><triangles>{triangles}</triangles></mesh>"


def write_bambu_3mf(path: Path, parts: list[tuple[np.ndarray, np.ndarray, int]], colours: list[str]) -> None:
    """Projet à la façon de Bambu Studio : un objet par pièce, filament par objet, couleurs du projet."""
    core = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    objects, items, settings = [], [], []
    for index, (pts, faces, extruder) in enumerate(parts, start=1):
        objects.append(f'<object id="{index}" type="model">{_model_xml(pts, faces)}</object>')
        items.append(f'<item objectid="{index}"/>')
        settings.append(f'<object id="{index}"><metadata key="extruder" value="{extruder}"/></object>')
    model = (f'<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xmlns="{core}">'
             f'<metadata name="Application">BambuStudio-demo</metadata><resources>{"".join(objects)}</resources>'
             f'<build>{"".join(items)}</build></model>')
    types = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
             'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
             'relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.'
             '3dmanufacturing-3dmodel+xml"/><Default Extension="config" ContentType="text/plain"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.'
            'microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/model_settings.config",
                   '<?xml version="1.0" encoding="UTF-8"?><config>' + "".join(settings) + "</config>")
        z.writestr("Metadata/project_settings.config",
                   '{"filament_colour": [' + ", ".join(f'"{c}"' for c in colours) + "]}")


def moved(pts: np.ndarray, dx=0.0, dy=0.0, dz=0.0) -> np.ndarray:
    return pts + np.array([dx, dy, dz], dtype=np.float32)


def encode_drc(pts: np.ndarray, faces: np.ndarray, **settings) -> bytes:
    from dracoconv.convert import encode_bytes
    from dracoconv.mesh import Mesh
    from dracoconv.settings import EncodeSettings
    from dataclasses import replace

    return encode_bytes(Mesh(pts, faces), replace(EncodeSettings(), **settings))[0]


# -- jeux de démonstration ----------------------------------------------------------------------------------------


def showcase(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    write_stl(folder / "engrenage.stl", *gear())
    pts, faces = torus_knot()
    write_obj(folder / "noeud.obj", pts, faces, rainbow(pts))
    pts, faces = sphere(5, 25.0)
    write_ply(folder / "sphere.ply", pts, faces, rainbow(pts))
    write_glb(folder / "tore.glb", *torus())
    (folder / "vase.drc").write_bytes(encode_drc(*vase()))
    write_stl(folder / "tour torsadee.stl", *twisted_tower())
    base_p, base_f = extrude(np.array([(-35, -22), (35, -22), (35, 22), (-35, 22)]), 6.0)
    post_p, post_f = revolve([(5, 6), (5, 42)], 48)
    ball_p, ball_f = sphere(3, 9.0)
    gear_p, gear_f = extrude(gear_outline(12, 11.0, 2.5, 8), 6.0)
    write_bambu_3mf(folder / "support.3mf", [
        (base_p, base_f, 1), (moved(post_p, -15), post_f, 2), (moved(ball_p, -15, 0, 40), ball_f, 3),
        (moved(gear_p, 16, 0, 6), gear_f, 4)], ["#2B2D31", "#F07818", "#F5C518", "#1E88E5"])
    step = Path(__file__).resolve().parents[2] / "explorer-draco-step-preview" / "tests" / "data" / "colored_block.step"
    if step.exists():
        shutil.copy2(step, folder / "bloc.step")


NAMES = {
    "fr": {"figurines": "Figurines", "mechanical": "Mécanique", "downloads": "Téléchargements",
           "archives": "Archives", "knot": "noeud {p}-{q}", "vase": "vase {n}", "ball": "boule lisse",
           "gear": "engrenage {n} dents", "tower": "tour torsadée", "oring": "joint torique",
           "colored": "boule colorée", "copy": "noeud 2-3 (1)", "gear_copy": "engrenage-18",
           "pack": "pack engrenages"},
    "en": {"figurines": "Figurines", "mechanical": "Mechanical", "downloads": "Downloads",
           "archives": "Archives", "knot": "knot {p}-{q}", "vase": "vase {n}", "ball": "smooth ball",
           "gear": "gear {n} teeth", "tower": "twisted tower", "oring": "o-ring", "colored": "colored ball",
           "copy": "knot 2-3 (1)", "gear_copy": "gear-18", "pack": "gear pack"},
}


def collection(folder: Path, lang: str = "fr") -> None:
    """Une collection plus lourde : figurines lisses, pièces mécaniques, doublons et une ancienne conversion."""
    n = NAMES[lang]
    figurines, mechanical = folder / n["figurines"], folder / n["mechanical"]
    downloads, archives = folder / n["downloads"], folder / n["archives"]
    for sub in (figurines, mechanical, downloads, archives):
        sub.mkdir(parents=True, exist_ok=True)
    for i, (p, q) in enumerate([(2, 3), (3, 4), (2, 5), (3, 5), (4, 5)]):
        pts, faces = torus_knot(p, q, 24 + 3 * i, 1400, 4.0 + 0.4 * i, 40)
        write_stl(figurines / (n["knot"].format(p=p, q=q) + ".stl"), pts, faces)
    for i in range(4):
        write_stl(figurines / (n["vase"].format(n=i + 1) + ".stl"), *revolve(
            [(14 + (6 + i) * math.sin(z / 90 * math.pi * (1.2 + 0.3 * i)), z) for z in np.linspace(0, 90, 180)], 360))
    write_stl(figurines / (n["ball"] + ".stl"), *sphere(6, 30.0))
    for teeth in (12, 18, 24, 36):
        write_stl(mechanical / (n["gear"].format(n=teeth) + ".stl"),
                  *extrude(gear_outline(teeth, teeth * 1.6, 3.0, 16), 10.0, layers=12))
    write_stl(mechanical / (n["tower"] + ".stl"), *twisted_tower())
    pts, faces = torus(30, 9, 360, 120)
    write_obj(mechanical / (n["oring"] + ".obj"), pts, faces)
    pts, faces = sphere(5, 20.0)
    write_ply(figurines / (n["colored"] + ".ply"), pts, faces, rainbow(pts))
    # Doublons : une copie téléchargée deux fois, et un modèle déjà converti par une ancienne version.
    shutil.copy2(figurines / (n["knot"].format(p=2, q=3) + ".stl"), downloads / (n["copy"] + ".stl"))
    shutil.copy2(mechanical / (n["gear"].format(n=18) + ".stl"), downloads / (n["gear_copy"] + ".stl"))
    pts, faces = revolve([(14 + 6 * math.sin(z / 90 * math.pi * 1.2), z) for z in np.linspace(0, 90, 180)], 360)
    (archives / (n["vase"].format(n=1) + ".drc")).write_bytes(encode_drc(pts, faces, position_bits=14))
    buffer = io.BytesIO()
    gear24 = n["gear"].format(n=24) + ".stl"
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(mechanical / gear24, gear24)
    (downloads / (n["pack"] + ".zip")).write_bytes(buffer.getvalue())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--collection", action="store_true")
    parser.add_argument("--lang", choices=("fr", "en"), default="fr")
    args = parser.parse_args()
    showcase(args.folder / "Vitrine")
    if args.collection:
        collection(args.folder / "Collection", args.lang)


if __name__ == "__main__":
    main()
