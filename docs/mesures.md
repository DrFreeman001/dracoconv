# Mesures réelles

Relevées le 2026-11-11 sur une collection de modèles d'impression 3D (Windows 11, Ryzen 9 9950X3D, 32 cœurs logiques, 125 Go de RAM). Toutes les mesures lisent les originaux sans jamais les modifier.

## 1. Essai complet sur un dossier

Dossier de 36 fichiers, dont 15 STL et 14 fichiers 3MF (parmi lesquels 8 `.gcode.3mf`). Sans quantification, niveau 10, **« Préserver la topologie » décoché** : cet essai a été fait avant l'ajout de ce réglage, aujourd'hui coché par défaut. Conversion vers un dossier miroir, puis retour en STL.

Avec « Préserver la topologie » coché (le défaut actuel), les mêmes 15 STL donnent **184,2 Mo, soit 29,7 % de la taille d'origine**, au lieu de 76,4 Mo : la plupart de ces modèles ne sont pas étanches et sont donc réencodés sans dédoublement de sommets. Ce réglage réduit les différences de connectivité à la lecture dans OrcaSlicer, sans garantir des statistiques identiques (voir section 2).

| Étape | Résultat |
|---|---|
| Projection par échantillon | 620,3 Mo de STL → 76,4 Mo annoncés |
| Conversion réelle des STL | 15 sur 15 convertis : 620,3 Mo → 76,4 Mo, soit **12,3 % de la taille d'origine** |
| Écart projection / réel | Nul ici : les 15 STL faisaient tous partie de l'échantillon |
| Durée | 65 s pour la conversion, 10 s pour le retour en STL |
| Retour en STL | 16 fichiers sur 16 reconvertis |
| Comparaison au triangle près | **16 sur 16 identiques à leur original** |
| Originaux | Inchangés : mêmes 36 fichiers, mêmes tailles, mêmes dates |

Les 3MF du même dossier :

| Cas | Fichiers | Ce que fait le logiciel |
|---|---|---|
| Converti avec gain | 1 (252 Ko → 193 Ko) | Converti, signalé « perte de données » |
| Sans gain | 3 (60,5 Mo) | Laissés tels quels. Exemple : un 3MF de 60 Mo donnerait un `.drc` de 107 Mo, car le 3MF réutilise le même objet plusieurs fois et est déjà compressé. |
| Projet Bambu Studio / OrcaSlicer | 2 (83,9 Mo) | Non lus, laissés tels quels |
| `.gcode.3mf` (impressions tranchées) | 8 | Ignorés dès l'analyse |

Conclusion pratique : convertir les 3MF n'apporte rien sur cette collection. Le gain est dans les STL et les OBJ.

## 2. Ouverture dans OrcaSlicer 2.5.0

Un `.drc` produit par dracoconv a été soumis à OrcaSlicer en ligne de commande (`orca-slicer --info`), à côté du STL d'origine (334 858 triangles, 16,0 Mo).

| Fichier | Taille | Dimensions | Facettes | Arêtes ouvertes | Parties | Volume (mm³) |
|---|---|---|---|---|---|---|
| STL d'origine | 16,0 Mo | 48,68 × 88,27 × 90,00 | 334 854 | 268 | 53 | 49 634 |
| `.drc` par défaut | 2,0 Mo | identiques | 334 858 | 3 330 | 897 | 49 670 |
| `.drc` avec « Conserver l'ordre » | 4,7 Mo | identiques | 334 858 | 274 | 54 | 49 681 |
| `.drc` à 16 bits | 0,5 Mo | identiques | 334 858 | 3 330 | 897 | 49 671 |

Ce que cela montre :

- **OrcaSlicer ouvre les fichiers produits**, avec les bonnes dimensions.
- Ce modèle n'est pas étanche à l'origine (268 arêtes ouvertes dans le STL). Sur un tel modèle, l'encodage par défaut de Draco dédouble des sommets : 169 757 sommets au décodage pour 167 118 positions distinctes. Les triangles sont identiques à ceux du STL, mais OrcaSlicer, qui relie les triangles par numéro de sommet, compte alors bien plus d'arêtes ouvertes et de parties.
- Avec **« Conserver l'ordre »**, aucun sommet n'est dédoublé et OrcaSlicer retrouve presque les mêmes chiffres que pour le STL. Le fichier pèse alors 2,35 fois plus (4,7 Mo, soit 29 % du STL au lieu de 12 %).
- L'effet sur le tranchage lui-même n'a pas été mesuré.
- Sur un modèle étanche, Draco ne dédouble rien et la question ne se pose pas.

La commande `dracoconv quality <fichier>` affiche le nombre de sommets dédoublés.

Le sens inverse (un `.drc` exporté par OrcaSlicer puis relu par dracoconv) n'a pas été testé : l'export DRC d'OrcaSlicer passe par sa fenêtre.

### Vérification complémentaire : deux modèles fournis

Réglages par défaut actuels : niveau 10, sans quantification, topologie préservée. Mesures en octets décimaux (Mo = 1 000 000 octets).

| Modèle | STL | Draco | Gain | Encodage / retour vérifiés |
|---|---:|---:|---:|---:|
| thailand_buddha | 145,49 Mo | 43,55 Mo | 70,07 % | 18,89 s / 11,26 s |
| Genius_of_Evil_28cm | 16,74 Mo | 4,92 Mo | 70,62 % | 1,70 s / 0,74 s |

Contrôle indépendant des facettes binaires par tri canonique puis SHA-256 : tous les triangles orientés, leurs coordonnées et les bornes sont identiques après retour STL (2 909 880 et 334 858 triangles). Les originaux ont gardé leur empreinte SHA-256. L'en-tête et les normales STL sont reconstruits.

OrcaSlicer ouvre les six fichiers. Les STL reconstruits retrouvent exactement les statistiques des originaux. La lecture directe des Draco reste différente : volume du Bouddha +0,0044 % environ ; Génie 274 arêtes ouvertes et 55 parties contre 268 et 54 pour le STL, volume +0,12 % environ. **Préserver la topologie ne garantit pas une interprétation identique par le lecteur Draco d'OrcaSlicer.** La cause précise et le G-code n'ont pas été vérifiés.

Le mode remplacer a été testé sur une copie réelle du Génie : un succès, copie STL retrouvée dans la corbeille Windows, Draco conservé identique à celui validé, original de la collection inchangé. La corbeille n'a pas été vidée. Rapports locaux sous `.superpowers/validation-2026-11-11/` (non suivis par Git).

## 3. Ratios recalibrés avec préservation de topologie

Recalibrage du 2026-11-12 sur les originaux conservés sur NAS : **7224 fichiers, 58,89 Go**, fichiers de 300 Mio au plus. Niveau 10, `keep_topology` activé, graine 1, cinq fichiers par classe de taille, budget maximal de 3600 secondes par profil. Les cinq profils ont traité le **même échantillon complet de 40 fichiers** : 38 encodés et deux OBJ illisibles. Le compteur du journal dit « encodés », mais compte les tentatives ; les deux fichiers illisibles restent à leur taille d'origine dans la projection.

| Réglage | STL | OBJ | Fichiers tentés / encodés | Durée |
|---|---:|---:|---:|---:|
| Sans quantification | 22,15 % | 16,85 % | 40 / 38 | 289 s |
| 14 bits | 14,64 % | 9,60 % | 40 / 38 | 395 s |
| 16 bits | 15,16 % | 9,93 % | 40 / 38 | 463 s |
| 20 bits | 17,21 % | 10,86 % | 40 / 38 | 454 s |
| 25 bits | 18,84 % | 12,11 % | 40 / 38 | 461 s |

Ces proportions sont des estimations de taille restante, pas des gains garantis. Les intervalles d'incertitude sont larges : sans quantification, 7,33–30,43 % pour les STL et 5,52–41,77 % pour les OBJ. Utiliser la projection sur les fichiers concernés. Les ratios augmentent bien avec la précision sur cet échantillon commun, sans correction artificielle des résultats.

Aucun PLY n'est présent dans cet inventaire NAS. Les ratios PLY conservés proviennent des **deux fichiers mesurés le 2026-11-11** : 16,47 % sans quantification, puis 3,29 / 4,07 / 5,93 / 8,40 % à 14 / 16 / 20 / 25 bits. Les ratios ZIP et 3MF restent des valeurs de départ non mesurées. Cette provenance est enregistrée dans `_meta`, avec les réglages et les effectifs tentés, encodés et illisibles.

Commande utilisée, en lecture seule sur les originaux :

```powershell
.venv/Scripts/python tools/calibrate.py '<collection>' --budget 3600 --out dracoconv/data/ratios.json
```

Journal local : `.superpowers/validation-2026-11-11/calibration-nas.log`. La première calibration locale portait sur 7623 fichiers (dont deux STL reconstruits lors des contrôles) et utilisait des échantillons partiels différents. Sa reprise a été abandonnée lorsque seuls 341 fichiers admissibles restaient. L'utilisateur a confirmé avoir converti les originaux locaux ; les mesures NAS ci-dessus remplacent désormais les anciens ratios STL/OBJ partiels.

## 4. Limites mesurées des moteurs

Voir [engine-support.md](engine-support.md). En résumé :

- 0 bit : aller-retour exact au bit près avec les deux moteurs.
- Le moteur intégré plafonne à 29 bits ; le moteur de référence accepte 30 bits, mais seulement jusqu'au niveau de compression 8.
- À partir de 22 bits environ, pour un modèle d'une centaine de millimètres, l'écart mesuré ne baisse plus : c'est la précision des nombres 32 bits du fichier d'origine qui limite.

## 5. Mémoire

La machine de mesure n'a presque pas de fichier d'échange : Windows refuse de réserver de la mémoire bien avant que la mémoire physique soit pleine. Un premier lot lancé pendant un autre traitement lourd a vu 20 conversions échouer pour cette raison, sans toucher aux originaux. Le logiciel a depuis été modifié :

- chaque processus de travail n'utilise qu'un fil de calcul ;
- le nombre de conversions simultanées est borné par la mémoire encore réservable ;
- un fichier qui manque de mémoire en parallèle est repris seul à la fin ;
- si un processus de travail meurt, aucun fichier n'est perdu ni laissé en attente.
