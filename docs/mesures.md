# Mesures réelles

Relevées le 2026-11-11 sur une collection de modèles d'impression 3D (Windows 11, Ryzen 9 9950X3D, 32 cœurs logiques, 125 Go de RAM). Toutes les mesures lisent les originaux sans jamais les modifier.

## 1. Essai complet sur un dossier

Dossier de 36 fichiers, dont 15 STL et 14 fichiers 3MF (parmi lesquels 8 `.gcode.3mf`). Réglages par défaut (sans quantification, niveau 10). Conversion vers un dossier miroir, puis retour en STL.

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

## 3. Ratios calibrés sur la collection

Échantillon tiré au hasard parmi 7 621 fichiers STL, OBJ et PLY de 300 Mo au plus (63,0 Go), 5 fichiers par type et par classe de taille, soit 42 fichiers réellement encodés pour chaque réglage. Taille obtenue en proportion de la taille d'origine :

| Réglage | STL | OBJ | PLY |
|---|---|---|---|
| Sans quantification | 12,1 % | 9,9 % | 16,5 % |
| 14 bits | 5,1 % | 1,1 % | 3,3 % |
| 16 bits | 5,6 % | 1,6 % | 4,1 % |
| 20 bits | 7,0 % | 2,8 % | 5,9 % |
| 25 bits | 8,9 % | 4,3 % | 8,4 % |

Ces valeurs sont livrées dans `dracoconv/data/ratios.json` et servent à la projection instantanée. À lire avec prudence :

- Ce sont des estimations sur 42 fichiers, pas un recensement. Le PLY ne repose que sur 2 fichiers.
- Avec quantification, un STL de l'échantillon (139 Mo) n'avait pas pu être encodé lors du calibrage, à cause d'un défaut de vérification corrigé depuis ; il a été compté à sa taille d'origine. Les ratios STL avec quantification sont donc un peu pessimistes : ce fichier seul descend à 1,3 % à 14 bits.
- Les ratios 3MF et ZIP du fichier ne sont pas mesurés : ce sont des valeurs de départ.
- Les fichiers de plus de 300 Mo ont été écartés du calibrage pour en borner la durée.

Appliqué aux 73,6 Go de STL recensés sur C, D, E et F, le ratio sans quantification donne un ordre de grandeur de 9 Go après conversion. La projection par échantillon du logiciel donnera un chiffre et une marge propres à chaque dossier.

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
