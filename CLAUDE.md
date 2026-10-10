# logicAI — instructions permanentes pour Claude Code

## Le projet en bref

Une IA part de la seule porte NAND, découvre seule des circuits logiques, les encapsule en composants
et les réutilise. Python fait la simulation et l'IA ; Unity (dossier `Assets/`) ne fait qu'afficher.

**Référence unique : `docs/cahier_des_charges.md`.** Lis-le en entier au début de chaque session,
avant toute proposition. Le suivi d'avancement est dans `docs/journal.md`.

## L'utilisateur

- Téo, étudiant en BUT GEII. Il lit le code (C#, Python de base) mais n'en écrit pas encore.
- Réponds toujours en **français**, avec un vocabulaire simple mais techniquement précis.
- Après chaque fichier créé ou modifié, explique-le **bloc par bloc** : ce que fait chaque bloc et pourquoi.
- Utilise des tableaux ou des schémas ASCII quand ça aide à comprendre.

## Règles anti-erreur (prioritaires sur tout le reste)

1. **Le cahier des charges fait foi.** N'invente aucune règle, aucun comportement ni aucune fonctionnalité qui n'y figure pas.
   En cas d'ambiguïté, de contradiction ou de cas non prévu : **arrête-toi et pose la question**.
   Ne tranche jamais seul un élément de la liste « Points à trancher ».
2. **Vérifie, ne suppose pas.** Avant de t'appuyer sur un fait de l'environnement (OS, shell, version de Python,
   git, paquet installé, version d'un paquet), vérifie-le par une commande et montre le résultat.
3. **Aucune API inventée.** N'utilise une fonction, une option ou un paramètre d'une bibliothèque que si tu l'as vérifié
   (documentation officielle, `help()`, ou un petit essai exécuté). Pour la bibliothèque standard, même règle en cas de doute.
4. **Rien n'est « fait » sans preuve.** N'affirme jamais qu'un code fonctionne ou qu'un test passe sans l'avoir exécuté.
   Montre la sortie réelle des commandes (le résumé et les lignes importantes).
5. **Honnêteté.** Si tu ne sais pas, dis-le et propose un moyen de vérifier. Si tu t'es trompé, dis-le clairement.
6. **Tests intouchables.** Ne modifie jamais un test pour le faire passer. Si un test te semble faux,
   explique pourquoi et demande avant de le changer.
7. **Périmètre strict.** Une session = la phase demandée, rien de plus. Ne commence pas la phase suivante,
   n'ajoute pas de fonctionnalité « bonus », ne réorganise pas du code qui n'a pas besoin de l'être.
8. **Petits pas.** D'abord un plan à valider, ensuite une implémentation par étapes courtes ; chaque étape est testée
   avant de passer à la suivante.
9. **Dépendances.** N'ajoute aucune bibliothèque sans l'accord explicite de Téo.
   Ne note jamais un numéro de version de mémoire : installe, puis relève la version réellement installée.

## Fichiers et dossiers

```
logicAI/                     <- racine du projet Unity (et du dépôt git)
├── CLAUDE.md                <- ce fichier
├── docs/
│   ├── cahier_des_charges.md   (lecture seule : propose les modifications, ne les fais pas)
│   ├── journal.md              (avancement, mis à jour à chaque fin de session)
│   └── prompts/                (prompts de lancement des sessions)
├── python/                  <- TOUT le code Python (hors Assets/, donc ignoré par Unity)
│   ├── pyproject.toml
│   ├── src/logicai/         <- le paquet
│   └── tests/               <- les tests pytest
└── Assets/ ...              <- Unity : à partir de la phase 3 seulement
```

Ne modifie **jamais** : `Library/`, `Temp/`, `Logs/`, `UserSettings/`, `ProjectSettings/`, `Packages/`,
les fichiers `*.meta`, ni `Assets/` avant la phase 3.

## Qualité du code Python

- Python **3.11 ou plus récent**. Si la version installée est plus ancienne, arrête-toi et demande.
- Environnement virtuel dans `python/.venv` ; n'installe jamais rien dans le Python global.
- Outils : **pytest** (tests), **ruff** (lint et formatage), **mypy** en mode strict sur `src/`.
  Les versions installées sont figées dans `python/requirements-dev.txt`, à partir de `pip freeze`.
- Noms dans le code (variables, fonctions, classes) en **anglais** ; commentaires, docstrings et messages d'erreur en **français**.
- Annotations de type partout. Une docstring pour chaque module, classe et fonction publique.
- Fonctions courtes, une seule responsabilité. Pas d'état global. Pas de `print` dans le paquet.
- Pas de nombre magique : utilise des constantes nommées.
- Erreurs : des exceptions dédiées, avec un message qui dit ce qui est refusé et pourquoi. Une opération refusée laisse l'objet inchangé.
- Tout tirage aléatoire (à partir de la phase 4) passe par un générateur avec une graine, pour que les résultats soient reproductibles.
- Chaque règle du cahier des charges a au moins un test, et chaque test indique en commentaire la règle qu'il vérifie.

### Contrôle obligatoire avant de dire « terminé »

Les quatre contrôles suivants doivent réussir, et leur sortie doit être montrée :

1. `ruff check`
2. `ruff format --check`
3. `mypy` (strict, sur `src/`)
4. `pytest`

Les commandes exactes pour cette machine sont dans la section « Commandes vérifiées » ci-dessous.

## Git

- Un commit à chaque étape validée, avec un message clair en français.
- Pas de `push`, pas de réécriture d'historique (`rebase`, `reset --hard`, `--force`) sans demande explicite.
- Ne commite jamais `python/.venv/`, `Library/`, `Temp/`, `Logs/`, `UserSettings/` ni les caches (`__pycache__`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`).

## Fin de session

1. Lance les quatre contrôles et montre leurs résultats.
2. Ajoute une entrée datée dans `docs/journal.md` : ce qui est fait, résultats des contrôles, ce qui reste, questions ouvertes.
3. Fais un commit.
4. Fais un résumé à Téo en français : les fichiers créés, à quoi ils servent, et les questions en attente.

## Commandes vérifiées

Vérifiées le 10 octobre 2026 sur cette machine (macOS, zsh, Python 3.14.7 de Homebrew), depuis la racine du projet.

- Activer l'environnement : `source python/.venv/bin/activate` (puis `cd python` ; `deactivate` pour sortir).
  Sans activer, on peut appeler les outils directement : `python/.venv/bin/pytest`, etc.
- Lancer les tests : `cd python && pytest` (la config est dans `python/pyproject.toml`).
- Lint / formatage / types, toujours depuis `python/` :
  - `ruff check`
  - `ruff format --check`
  - `mypy` (strict, sur `src/`)
