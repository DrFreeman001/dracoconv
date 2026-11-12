# Prototype Windows Draco — vérification

État au 12 novembre 2026 : faisabilité démontrée sur cube synthétique, pas une extension prête à distribuer. Installation d’essai retirée : register.py status confirme « not installed ». Aucun auxiliaire shell_preview.py ni fichier temporaire résiduel constaté après désélection.

## Résultats observés
- DLL x64 compilée avec MSVC 14.51 et SDK 10.0.26100.0.
- COM direct : Initialize S_OK, seconde initialisation 800704df, miniature HBITMAP S_OK, DllCanUnloadNow S_OK.
- Cache Windows réel : IThumbnailCache::GetThumbnail avec WTS_FORCEEXTRACTION retourne S_OK sur cube.drc.
- Explorer réel : cube affiché dans son volet latéral ; glisser fait tourner, molette change le zoom, R restaure l’orientation et le zoom après focus souris.
- Redimensionnement du volet réussi après correction dimensions Win32 physiques / Qt logiques (écran à 150 %).
- Isolation vérifiée par OpenProcessToken/GetTokenInformation : prevhost PID80064 et Python PID80344,42568 ont tous le RID 0x1000 (Low). Aucun DisableLowILProcessIsolation/DisableProcessIsolation ajouté.
- Plusieurs sélections/désélections : disparition des processus auxiliaires et nettoyage du répertoire temporaire constatés.
- Régression panne : test_failure.py constate le défaut avant correction (Chargement persiste), puis succès après correction (Apercu indisponible), Unload S_OK.
- Régression démarrage bloqué : auxiliaire dormant60s, message d’indisponibilité après20s, Unload S_OK.
- Six tests Python ciblés passent : image réelle, géométrie/projection, invalides/nuages de points, registre/restauration, conflit ProgID par défaut et UserChoice.

## Dernière vérification et réserve clavier
Le 12 novembre à 19:38, le cube est de nouveau affiché dans le véritable volet Explorer avec la DLL corrigée (surveillance auxiliaire, focus enfant, dimensions à 150 %). Après clic dans le modèle, Tab et Shift+Tab ont été envoyés. Le fournisseur d’accessibilité conserve cependant le champ Address Bar comme focus et aucun indicateur visuel ne permet de confirmer la sortie et le retour du focus : parcours clavier non validé, correction à considérer provisoire. Le reset R était vérifié après focus souris lors du passage précédent, pas après parcours clavier. Ce point reste bloquant avant distribution.

La suite complète du dépôt exécutée par l’agent principal a terminé avec 325 tests réussis ; journal `.superpowers/validation-2026-11-11/pytest-prototype-final.log`. Aucun changement de code après ce résultat. Retour à Home dans Explorer, retrait avec register.py uninstall, puis status : not installed. Aucun processus Python de ce prototype ni résidu dans LocalLow/DracoConvPreview au contrôle final.

## Limites du prototype
Entrée comprimée plafonnée à32MiB ; le Bouddha validé de43,55MB est donc exclu. Budget du job complet1536MiB ;768MiB provoquait un arrêt0xc0000409 pendant le démarrage Python/Qt. Un seul aperçu et une seule miniature à la fois (deux jobs au maximum). Au-delà de12000 triangles, échantillonnage de faces pour affichage uniquement, annoncé « Affichage simplifié » ; ce n’est pas une décimation et peut rendre un modèle poreux. Géométrie seulement, sans textures ni couleurs ; nuages de points refusés. Aucun grand modèle fourni n’a été validé ici. Pas de modification des sources ni de changement de programme par défaut.
