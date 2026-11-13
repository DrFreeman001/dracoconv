# Prototype d’extension Windows Draco

Prototype de faisabilité : deux classes COM x64, miniatures et aperçu 3D isolés. Lire [verification.md](verification.md) avant utilisation. Ne pas présenter cette version comme une extension finale pour toute la collection.

Depuis la racine du dépôt, PowerShell :

```powershell
.venv/Scripts/python.exe windows/preview/configure.py
./windows/preview/build.ps1
.venv/Scripts/python.exe -m pytest tests/test_shell_preview.py tests/test_shell_registration.py -q
./windows/preview/build/probe.exe
.venv/Scripts/python.exe windows/preview/test_failure.py
.venv/Scripts/python.exe windows/preview/register.py install
./windows/preview/build/cache_probe.exe (Join-Path $PWD 'windows\preview\cube.drc')
```

Dans Explorer, sélectionner `windows/preview/cube.drc`, ouvrir le volet avec Alt+P. Glisser pour tourner, molette pour zoomer, R pour réinitialiser. L’installation est par utilisateur, uniquement les gestionnaires `.drc`. Elle refuse les gestionnaires étrangers trouvés directement ou par ProgID associé, y compris UserChoice ; le programme d’ouverture par défaut reste intact.

Retrait :

```powershell
.venv/Scripts/python.exe windows/preview/register.py uninstall
.venv/Scripts/python.exe windows/preview/register.py status
```

Conserver `build/registration.json` tant que l’installation est active : ce manifeste permet le retour exact des valeurs antérieures. Le retrait laisse intactes les valeurs modifiées entre-temps par une autre application. Les chemins Python/source sont propres à cette copie du dépôt dans `build/preview.ini` ; garder les fichiers en place pendant l’essai. Ne pas exécuter test_failure.py pendant une installation active : il remplace temporairement ce fichier de configuration pour simuler un auxiliaire défaillant.

Limites : 64 Mio comprimés, 1536 Mio par job, 20 s pour une miniature ou le chargement initial. Toutes les faces sont dessinées par OpenGL ; sans OpenGL, un dessin échantillonné de 12 000 faces prend le relais et l’annonce. Le clavier ne fonctionne qu’après un clic dans le modèle (R pour réinitialiser) : Tab et Maj+Tab n’entrent pas dans l’aperçu et n’en sortent pas. Ne jamais arrêter `prevhost.exe` de force pendant qu’Explorer tourne : l’aperçu resterait vide jusqu’au redémarrage d’Explorer. Pour recharger la DLL : arrêter Explorer, puis les `prevhost.exe`, puis relancer Explorer. Le lancement Python dans le venv utilise un petit processus relais ; les descendants restent dans le job tué à la fermeture. L’aperçu et les miniatures ont chacun une limite de concurrence de1. Aucun réglage d’isolation Windows n’est modifié.

`inspect_integrity.py PID...` relève les niveaux d’intégrité sans modifier les processus. Les entrées temporaires sont privées au profil utilisateur sous LocalLow/DracoConvPreview et supprimées au déchargement normal. Une interruption brutale de l’hôte peut laisser un dossier temporaire ; une collecte de ces restes reste à implémenter avant distribution.

État final du contrôle : prototype désinstallé. Le parcours Tab/Shift+Tab reste non validé dans Explorer ; voir le compte rendu. Ne pas laisser cette version activée pour un usage quotidien.
