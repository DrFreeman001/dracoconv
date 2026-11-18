# Journal des versions

## 0.3.0 — novembre 2026

- Clic droit « Ouvrir dans le trancheur » sur les `.drc` : décodage en STL temporaires vérifiés, toute la sélection dans une seule fenêtre de Bambu Studio, OrcaSlicer ou PrusaSlicer ; trancheur à choisir dans le menu « Trancheur ».
- Doublons : menu « Outils », « Chercher les doublons… », et commande `dracoconv duplicates`. Fichiers identiques, et même modèle sous une autre forme (STL et son `.drc`, `.drc` d'autres réglages ou d'une ancienne version). Corbeille des fichiers cochés après confirmation, au moins un fichier gardé par groupe.
- Dossiers surveillés : menu « Outils », « Dossiers surveillés… ». Conversion des nouveaux modèles par une tâche planifiée de Windows, sans programme résident ; priorité basse, pas de passage sur batterie.
- Glisser-déposer de fichiers et de dossiers sur la fenêtre.
- Avancement du lot dans l'icône de la barre des tâches, notification Windows en fin de lot quand la fenêtre n'est pas au premier plan.

## 0.2.0 — novembre 2026

- Avis de nouvelle version : une vérification par jour sur GitHub, à décocher dans le menu « Aide ».
- Menu « Aide » avec le lien vers la page du projet.

## 0.1.0 — novembre 2026

Première version.

- Conversion vers `.drc` depuis STL, OBJ, PLY, 3MF et ZIP ; retour vers STL, OBJ ou PLY ; par fichier, dossier ou disque.
- Fenêtre en cinq étapes et ligne de commande, en français et en anglais ; thèmes Système, Clair et Sombre.
- Projection du gain de place et mesure de la perte de qualité avant conversion.
- Vérification de chaque fichier produit ; originaux jamais touchés par défaut.
- Réglage « Préserver la topologie » pour les modèles non étanches.
- Clic droit de l'Explorateur « Convertir avec dracoconv » (une seule fenêtre pour toute une sélection).
- Installateur Windows par utilisateur (`tools/build_installer.ps1`, Inno Setup) et dossier autonome sans Python (`tools/build_exe.ps1`).
- L'extension pour l'Explorateur Windows (miniatures et aperçu 3D des `.drc` et STEP) est devenue un projet à part : [explorer-draco-step-preview](https://github.com/DrFreeman001/explorer-draco-step-preview).
