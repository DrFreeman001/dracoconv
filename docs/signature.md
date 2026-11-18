# Signer les installateurs (dracoconv et explorer-draco-step-preview)

Sans signature, Windows SmartScreen affiche « éditeur inconnu » au premier lancement des installateurs. Ce
document prépare la demande de signature gratuite ; rien n'est encore signé.

## Quelle offre

| Offre | Pour un particulier en France | Coût |
|---|---|---|
| [SignPath Foundation](https://signpath.org/) (projets open source) | Oui, sur dossier | Gratuit |
| [Azure Artifact Signing](https://learn.microsoft.com/azure/artifact-signing/quickstart) (ex-Trusted Signing) | Non : particuliers des États-Unis et du Canada seulement (organisations : aussi Union européenne et Royaume-Uni) | Environ 10 $ par mois |
| Certificat classique (OV) d'une autorité de certification | Oui | Plusieurs centaines d'euros par an, clé sur support matériel |

Choix retenu : **SignPath Foundation**.

## Conditions de SignPath Foundation (relevées en novembre 2026)

Source : [conditions de SignPath Foundation](https://signpath.org/terms).

- Licence open source approuvée par l'OSI, sans double licence commerciale : **remplie** (Apache-2.0 pour les deux).
- Projet maintenu, déjà publié sous la forme à signer, fonctions décrites sur la page de téléchargement :
  **rempli** (versions publiées sur GitHub avec leurs installateurs, README).
- Binaires construits **automatiquement et de façon vérifiable** depuis le dépôt : **à faire**. Aujourd'hui,
  les installateurs sont fabriqués sur le PC (`tools/build_installer.ps1`, `windows/installer/build_installer.ps1`).
  Il faut un flux GitHub Actions qui les construit à chaque version, avec un nom de produit et un numéro de
  version identiques d'une construction à l'autre.
- Composants tiers non modifiés (Python, Qt, OpenCascade, runtime Visual C++) : autorisés tels quels, non signés
  par nous.
- Installateurs qui annoncent ce qu'ils changent et se désinstallent proprement : **rempli** (registre remis à
  l'identique, tâche planifiée retirée).
- Authentification à deux facteurs pour GitHub et SignPath, pour chaque membre : **à vérifier** sur le compte
  DrFreeman001.
- Rôles déclarés (auteurs, relecteurs, approbateurs) et **approbation manuelle de chaque signature** : un seul
  membre ici, qui tient les trois rôles.
- Une page « Code signing policy » sur la page d'accueil et la page de téléchargement, avec la mention de
  SignPath Foundation, les rôles et une phrase sur la vie privée : **à publier une fois la demande acceptée**
  (modèle ci-dessous).

## Ce que tu fais toi-même

1. Activer l'authentification à deux facteurs sur GitHub, si ce n'est pas déjà fait.
2. Remplir la demande sur [signpath.org/apply](https://signpath.org/apply), une par projet ou une pour les
   deux, avec les liens des dépôts et des versions publiées. Ce formulaire t'engage personnellement : je ne le
   remplis pas à ta place.
3. Attendre la réponse de SignPath Foundation, qui peut refuser sans avoir à se justifier.

## Ce que je fais ensuite, une fois la demande acceptée

1. Un flux GitHub Actions `release.yml` par dépôt : sur une étiquette `v*`, il construit l'installateur sur
   `windows-latest`, puis l'envoie à SignPath avec l'action officielle de SignPath, et joint le fichier signé à
   la version publiée.
2. Pour la visionneuse, ce flux construit aussi la DLL et le lecteur STEP (outils C++ du runner, OpenCascade
   téléchargé par `fetch_occt.py`, Python embarqué vérifié).
3. La page « Code signing policy » dans chaque README, à partir du modèle ci-dessous.
4. Une nouvelle version signée de chaque programme, puis la mise à jour des demandes winget.

## Modèle de « Code signing policy » (à publier seulement après acceptation)

> **Code signing policy**
>
> Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by
> [SignPath Foundation](https://signpath.org/).
>
> - Committers and reviewers: [DrFreeman001](https://github.com/DrFreeman001)
> - Approvers: [DrFreeman001](https://github.com/DrFreeman001)
>
> Every signed release is built by GitHub Actions from this repository and approved by hand before signing.
>
> **Privacy** (dracoconv): this program does not send any information to other networked systems, except the
> optional update check, which asks GitHub for the latest release number and can be turned off in the Help menu.
>
> **Privacy** (explorer-draco-step-preview): this program makes no network connection at all.
