# Session 1 — Préparation (phase 0) et simulateur logique (phase 1)

Tu travailles sur le projet logicAI. Commence par lire en entier `CLAUDE.md` et `docs/cahier_des_charges.md`.
Les règles de `CLAUDE.md` sont prioritaires.

Le périmètre de cette session est **uniquement** : la phase 0 (préparation de l'environnement) et la phase 1 (le simulateur logique).
Hors périmètre : les composants et l'encapsulation (phase 2), le JSON (phase 2), Unity (phase 3), l'IA (phase 4) et la CLK (phase 6).
Conçois tout de même le code pour qu'on puisse ajouter plus tard de nouveaux types de nœuds (composant, CLK) sans tout réécrire.

## Étape 0 — Vérifications (aucune modification de fichier)

Exécute les commandes nécessaires et montre leurs résultats :

- système d'exploitation et shell utilisés ;
- version de Python disponible (3.11 minimum, sinon arrête-toi et demande) ;
- présence de git, et si ce dossier est déjà un dépôt git ;
- contenu de la racine du projet.

Propose ensuite, **sans l'exécuter**, la préparation suivante :

- `git init` si nécessaire ;
- un `.gitignore` couvrant Unity et Python ;
- la création de `python/.venv` ;
- l'installation de pytest, ruff et mypy ;
- un `pyproject.toml` avec la configuration de ruff, de mypy (strict) et de pytest ;
- une méthode qui rend le paquet importable par les tests (installation éditable, ou option `pythonpath` de pytest). Choisis-en une, explique ton choix et vérifie-le par une exécution.

**Attends mon accord avant d'exécuter quoi que ce soit.**

## Étape 1 — Plan (aucun code avant mon accord)

Présente :

- la liste des fichiers ;
- les classes et les fonctions publiques, avec leurs signatures typées ;
- la liste des tests, en reprenant au minimum le tableau de la section E.

Signale toute ambiguïté que tu repères dans la spécification ci-dessous **avant** de coder.

## Spécification de la phase 1 (contrat exact)

### A. Modèle de circuit

- Types de nœuds de la phase 1 :

  | Type | Puits | Sources |
  | --- | --- | --- |
  | INPUT (entrée du circuit) | 0 | 1 |
  | OUTPUT (sortie du circuit) | 1 | 0 |
  | NAND | 2 | 1 |

- Chaque nœud a un identifiant entier unique. Un identifiant n'est jamais réutilisé, même après la suppression du nœud.
- Une broche se désigne par (identifiant du nœud, index). L'index se compte séparément parmi les sources et parmi les puits du nœud.
- L'ordre des entrées et des sorties du circuit est leur ordre de création.
- Opérations : ajouter un nœud ; supprimer un nœud, ce qui supprime aussi ses câbles ; connecter(source, puits) ; déconnecter(puits).
- `connect` refuse avec une exception dédiée, et laisse le circuit inchangé, dans ces cas :
  - nœud inexistant ;
  - index de broche inexistant ;
  - puits déjà relié ;
  - broche du mauvais genre (une source donnée comme puits, ou l'inverse).
- Sont autorisés : les boucles, y compris d'une NAND sur elle-même ; un fan-out illimité.

### B. Simulation par tops

- L'état du circuit est la valeur de sortie de chaque NAND. Au départ, toutes ces valeurs sont à 0.
- Au cours d'un top, chaque NAND calcule NAND(puits 0, puits 1), avec :
  - un puits relié à une NAND : la valeur de cette NAND au top précédent ;
  - un puits relié à une INPUT : la valeur actuellement appliquée sur cette entrée, sans retard ;
  - un puits non relié : 0.

  Toutes les NAND sont mises à jour en même temps.
- La valeur d'une OUTPUT est celle de la source qui la pilote, sans retard, ou 0 si elle n'est pas reliée.
- La règle de stabilité :
  - T_max est le nombre de NAND du circuit ;
  - on calcule au plus T_max + 1 tops ;
  - le circuit est STABLE dès qu'un top ne change aucune valeur ;
  - il est UNSTABLE s'il change encore au top T_max + 1.

  Pourquoi ce compte suffit : un circuit sans boucle de profondeur d ≤ T_max est figé après d tops, et le top suivant le confirme.

### C. Simulation bit-parallèle

- Chaque signal est un entier Python. Le bit k vaut le signal pour la combinaison k.
- L'entrée numéro i (dans l'ordre de création) vaut le bit i de k.
- Avec n entrées, il y a 2^n combinaisons et le masque vaut `(1 << 2**n) - 1`.
- Le calcul d'une NAND est `~(a & b) & masque`.
- Le circuit est STABLE seulement si toutes les combinaisons sont stables.

### D. Résultats

- **Table de vérité** (signature combinatoire) : le statut (STABLE ou UNSTABLE) et un tuple d'entiers, un par sortie, dans l'ordre de création des sorties.
- **Séquence** :
  - on applique une suite de vecteurs d'entrée, un par pas, sur une seule combinaison ;
  - l'état est conservé d'un pas au suivant, et le départ est tout à 0 ;
  - à chaque pas, la simulation tourne jusqu'à la stabilité (règle B) ;
  - le résultat donne, pour chaque pas, les sorties et le statut ;
  - si un pas est instable, la séquence entière est instable.
- **Mémoire** : elle est détectée quand deux pas d'une séquence stable ont le même vecteur d'entrée mais des sorties différentes.

### E. Tests obligatoires (valeurs attendues)

Notation : l'entrée A est la première créée, B la deuxième. Avec 2 entrées, les valeurs s'écrivent sur 4 bits.

| Circuit | Construction | Résultat attendu |
| --- | --- | --- |
| NOT | NAND(A, A) — 1 entrée | `0b01`, stable |
| NAND | NAND(A, B) | `0b0111`, stable |
| AND | NOT(NAND(A, B)) — 2 NAND | `0b1000`, stable |
| OR | NAND(NOT A, NOT B) — 3 NAND | `0b1110`, stable |
| XOR | n1 = NAND(A, B) ; n2 = NAND(A, n1) ; n3 = NAND(B, n1) ; sortie = NAND(n2, n3) — 4 NAND | `0b0110`, stable |
| Constante 1 | une NAND sans aucun câble, reliée à une sortie — 0 entrée | `0b1`, stable |
| Sortie non reliée | une OUTPUT sans câble | 0 |
| NOT rebouclé | une NAND dont les deux puits sont reliés à sa propre sortie | UNSTABLE |
| Bascule SR (NAND) | Q = NAND(S̄, Q̄) ; Q̄ = NAND(R̄, Q) ; séquence (S̄, R̄) = (0,1), (1,1), (1,0), (1,1) | Q = 1, 1, 0, 0 ; chaque pas stable ; mémoire détectée |
| Métastabilité | la même bascule, partant de l'état tout à 0, avec (S̄, R̄) = (1,1) dès le premier pas | UNSTABLE |
| Règles de câblage | un 2e câble sur un même puits ; un index de broche inexistant ; un nœud inexistant ; une broche du mauvais genre | exception levée, circuit inchangé |
| Suppression | supprimer un nœud relié | ses câbles disparaissent aussi |

Si ton implémentation donne un résultat différent de ce tableau, **ne modifie ni le test ni la valeur attendue**.
Arrête-toi, montre le calcul top par top et explique l'écart.

## Étape 2 — Implémentation, en trois sous-étapes

Pour chaque sous-étape : code, puis tests, puis les quatre contrôles de `CLAUDE.md`, puis l'explication bloc par bloc, puis un commit.

1. Le modèle de circuit et les règles de câblage (section A).
2. La simulation par tops et la stabilité (section B).
3. Le bit-parallèle, la table de vérité, les séquences et la mémoire (sections C et D).

## Étape 3 — Fin de session

- Remplis la section « Commandes vérifiées » de `CLAUDE.md`.
- Crée `docs/journal.md` et ajoute-lui une première entrée.
- Suis ensuite la procédure « Fin de session » de `CLAUDE.md`.
- **Ne commence pas la phase 2.**
