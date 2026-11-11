# Prise en charge des paramètres par moteur

Relevé par essais réels le 2026-11-11.

## Moteur intégré : DracoPy 2.2.0

Signature relevée :

```
encode(points, faces=None, quantization_bits=11, compression_level=1,
       quantization_range=-1, quantization_origin=None, create_metadata=False,
       preserve_order=False, colors=None, tex_coord=None, normals=None,
       generic_attributes=None, tex_coord_quantization_bits=None,
       normal_quantization_bits=None)
decode(buffer) -> DracoMesh | DracoPointCloud
```

Constats sur une icosphère de 20 480 triangles (STL de 1 024 084 octets) :

| Essai | Résultat |
|---|---|
| `quantization_bits=0` | Accepté. Aller-retour exact au bit près. 123 018 octets, soit 12 % du STL. |
| `quantization_bits=14` | 16 550 octets (1,6 %), écart maximal 0,005 mm. |
| `quantization_bits=25` | 60 789 octets (5,9 %). |
| `quantization_bits=29` | Accepté. |
| `quantization_bits=30` | `MemoryError: bad allocation` à l'encodage. |
| Bits ≥ 22 | L'écart mesuré ne descend plus sous 0,000014 mm environ : plancher des flottants 32 bits. |
| `compression_level` 0 / 1 / 7 / 10 à 14 bits | 166 279 / 40 377 / 17 503 / 16 550 octets. |
| `compression_level` 7 et 10 sans quantification | Taille identique. |
| `preserve_order=True` | Ordre des sommets et des faces conservé ; fichier 2 à 10 fois plus gros. |
| `faces=None` | Nuage de points (`DracoPointCloud`). |
| `tex_coord`, `normals` | Exigent des tableaux `float64`. |
| `create_metadata=True` | Ajoute 26 octets de contenu non documenté ; ne correspond pas à `--metadata` de l'encodeur officiel. |
| Triangle dégénéré en entrée | Supprimé à l'encodage. |
| Tampon invalide | `FileTypeException`. |

## Tableau de prise en charge

| Paramètre | Intégré (DracoPy) | Référence (outils officiels) |
|---|---|---|
| `compression_level` | oui | oui (`-cl`) |
| `position_bits` | 0 à 29 | 0 à 30 (`-qp`) |
| `tolerance_mm` | résolu en `position_bits` avant le moteur | idem |
| `texcoord_bits` | oui | oui (`-qt`) |
| `normal_bits` | oui | oui (`-qn`) |
| `generic_bits` | non | oui (`-qg`), sur le fichier d'origine |
| `skip_attributes` | oui (appliqué avant le moteur) | oui (appliqué avant le moteur, ou `--skip` sur le fichier d'origine) |
| `point_cloud` | oui | oui (`-point_cloud`) |
| `preserve_order` | oui | non (absent de la ligne de commande) |
| `metadata` | non | oui (`--metadata`), sur le fichier OBJ d'origine |
| `preserve_polygons` | non | oui (`-preserve_polygons`), sur le fichier OBJ/PLY d'origine |

## Moteur de référence : Draco 1.5.9 compilé

| Essai | Résultat |
|---|---|
| `-qp 0` | Aller-retour exact au bit près. |
| `-qp 30` aux niveaux 0 à 8 | Accepté. |
| `-qp 30` aux niveaux 9 et 10 | L'encodeur plante (code 0xC0000409). Le moteur ramène alors le niveau à 8. |
| `-qp 31` | Refusé : « The maximum number of quantization bits for the position attribute is 30 ». |
| Fichiers croisés | Un `.drc` de DracoPy est lu par `draco_decoder`, et inversement. |
