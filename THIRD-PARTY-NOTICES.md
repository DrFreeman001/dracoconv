# Composants tiers

dracoconv est sous licence Apache-2.0 (voir `LICENSE`). Ce dépôt ne contient aucun code ni binaire tiers : les composants ci-dessous sont installés par `pip` ou téléchargés par les scripts du dépôt. Qui redistribue un paquet les incluant (exécutable, installateur) doit respecter leurs licences.

## Bibliothèques Python (installées par `pip`)

| Composant | Licence déclarée par le paquet |
|---|---|
| DracoPy | Apache-2.0 |
| numpy | BSD-3-Clause et autres licences permissives |
| scipy | BSD |
| trimesh | MIT |
| networkx | BSD-3-Clause |
| lxml | BSD-3-Clause |
| Send2Trash | BSD-3-Clause |
| PySide6 (Qt pour Python) | LGPL-3.0-only, GPL-2.0-only ou GPL-3.0 |

## Outils de référence Draco (compilés par `tools/build_draco.ps1`)

Google Draco, Apache-2.0. https://github.com/google/draco

## Lecteur STEP de l'extension Explorateur (téléchargé par `windows/preview/fetch_occt.py`)

- Open CASCADE Technology 8.0.1 : LGPL-2.1 avec l'exception Open CASCADE. https://dev.opencascade.org
- DLL dont OpenCascade dépend, paquets conda-forge : FreeImage, FreeType, Imath, libjpeg-turbo, libpng, LibRaw, libtiff, libwebp, zlib, OpenEXR, OpenJPEG, LERC, libdeflate, Zstandard, liblzma, Little CMS, OpenJPH. Chacune garde sa propre licence, fournie dans son paquet conda-forge ; elles n'ont pas été relevées une à une ici.
