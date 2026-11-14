# Journal des versions

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
