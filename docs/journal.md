# Journal d'avancement — logicAI

Une entrée par session, la plus récente en haut. Le cahier des charges (`docs/cahier_des_charges.md`) reste la référence.

---

## 10 octobre 2026 — Session 4 : phase 4 (IA évolutionnaire), étapes 1 à 4 faites

### Plan validé par Téo (« OK avec tes recommandations »)

Étapes : (1) filtres, (2) mutations, (3) récompense, (4) boucle d'évolution, (5) paliers, (6) test de la phase. Pas de NumPy (aucune bibliothèque ajoutée).
Réponses de Téo, toutes prises comme recommandées :

| # | Question | Décision |
| --- | --- | --- |
| Q1 | Choix des parents (récompense unique par signature) | Le plus petit circuit par signature trouvée (idée de MAP-Elites), plus quelques circuits récents |
| Q2 | Score d'un circuit ni nouveau ni plus petit | 0 ; la pénalité k·N_NAND ne s'applique que sur une nouveauté ou un record ; un circuit rejeté vaut 0 |
| Q3 | Réutilisation | Bonus ajouté au score de la nouvelle découverte + compteur de réutilisations par composant ; pas d'effet sur la fréquence de choix |
| Q4 | Entrées et sorties aux paliers 1 à 3 | Une seule sortie : « ajouter une sortie » interdit ; « ajouter une entrée » s'arrête au maximum du palier |
| Q5 | Boucles en phase 4 | Les mutations des paliers 1 à 3 ne créent pas de boucle (la règle de câblage ne change pas) |

La branche est repartie de `main` après la fusion de la PR n°1 (avance rapide, rien perdu).

### Étape 1 faite : filtres anti-triche (`filters.py`, `tests/test_filters.py`)

- `find_rejections(circuit, definitions)` aplatit le circuit, calcule sa table de vérité, puis renvoie les motifs de rejet (tuple vide = accepté).
  `rejections_of_table(table, input_count)` fait la même chose sur une table. Les 5 filtres du cahier sont des motifs de l'énumération `Rejection`.
- Les filtres jugent le **comportement** (table de vérité), pas le câblage. Un circuit instable n'a que le motif `UNSTABLE` (sa table n'est pas significative).
- Un circuit invalide (composant inconnu...) lève l'erreur d'aplatissement au lieu d'être « rejeté ».
- `Library.register` lève `UnstableCircuitError` pour un circuit instable : l'évolution devra donc passer par les filtres **avant** l'enregistrement.

Preuves :

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `31 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 14 source files` |
| `pytest` | `477 passed` (439 avant, 38 nouveaux) |
| Mutations (copie hors du projet) | 14 erreurs volontaires dans `filters.py`, 14 détectées, 0 survivante |

Deux tests vérifient des chiffres du cahier : sur toutes les fonctions à 1 sortie, il en reste **1, 10 et 218** après les filtres (tableau des paliers) ;
et toutes les petites tables (jusqu'à 3 entrées à 1 sortie, 2 entrées à 2 sorties) sont comparées à un calcul indépendant, combinaison par combinaison.

Erreur de ma part, trouvée et corrigée : un test aléatoire demandait des entiers de 2³² bits (mauvais argument de `getrandbits`) et bloquait ; le module n'était pas en cause.

### Étape 2 faite : mutations (`mutations.py`, `tests/test_mutations.py`, `errors.py`)

- Les 7 mutations du cahier (`Mutation`) : ajouter une NAND, ajouter un composant, ajouter un câble, retirer un câble, retirer un nœud, ajouter une entrée,
  ajouter une sortie. `apply_mutation` applique une mutation précise, `mutate` en tire une au hasard parmi les possibles (toujours possible : ajouter une NAND).
- Le parent n'est jamais modifié (travail sur `Circuit.copy()`). Une mutation impossible rend `None` et ne change rien.
- `MutationRules(max_inputs, max_outputs, allow_loops=False)` : réglages du palier. Q4 : une seule sortie aux paliers 1 à 3 (`max_outputs=1`) ;
  Q5 : pas de boucle (`allow_loops=False` : un câble n'est proposé que si le nœud du puits ne mène pas déjà au nœud de la source).
  Erreur dédiée : `InvalidMutationRulesError` (maximum négatif).
- Tout le hasard vient du `random.Random` donné par l'appelant : même graine, même résultat (testé, et l'état global de `random` est sans effet).

**Interprétation à confirmer par Téo** : le cahier dit « retirer un nœud » sans préciser. J'ai retenu : seulement les NAND et les composants ; les entrées et sorties du
circuit ne se retirent pas (on en ajoute dans la limite du palier, et une entrée inutile est refusée par les filtres). Changer cela tient en une ligne (`_REMOVABLE_KINDS`).
Le choix de la mutation est uniforme (pas de poids inventés) ; on les réglera par essais si besoin.

À savoir pour l'étape 4 : « ajouter une entrée » ou « ajouter une NAND » seule donne un circuit refusé par les filtres (entrée ou NAND non câblée). Un enfant devra donc
recevoir **plusieurs mutations** d'affilée.

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `33 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 15 source files` |
| `pytest` | `627 passed` (477 avant, 150 nouveaux) |
| Mutations (copie hors du projet) | 22 erreurs volontaires dans `mutations.py` : 21 détectées, 1 équivalente |

La première série en avait laissé survivre 5 : 4 venaient d'un vrai trou de **mes tests** (je ne vérifiais pas que les choix sont bien aléatoires : un code qui prenait toujours
le premier élément passait). 4 tests de répartition ajoutés. Le mutant équivalent : sans `remaining.remove(kind)`, on retire au sort jusqu'à tomber sur une mutation possible ;
la répartition des résultats est la même (uniforme parmi les possibles), seul le nombre de tirages change. Le code garde `remove` pour borner les essais à 7.

### Étape 3 faite : récompense (`reward.py`, `tests/test_reward.py`, `errors.py`)

- `RewardTracker(library, settings).evaluate(circuit)` suit le chemin du cahier : nettoyage, filtres (étape 1), enregistrement dans la bibliothèque, puis récompense.
  Issues (`TrialKind`) : `REJECTED` (0 point), `NEW`, `RECORD`, `NOTHING` (0 point). Le résultat (`TrialResult`) donne l'issue, le score, le composant concerné,
  les motifs de refus et les composants réutilisés. Seule la bibliothèque change, et seulement pour une nouveauté ou un record.
- Formule : nouveauté = `novelty + reuse × (composants distincts réutilisés) − k × N_NAND` ; record = `record − k × N_NAND` ; refusé ou rien = 0 (décision Q2).
  Le terme mémoire vaut 0 (phase 6). `RewardSettings` porte les 4 poids ; poids négatif refusé (`InvalidRewardSettingsError`).
- **Valeurs de départ, à régler par essais** : nouveauté 100, record 30, réutilisation 5, k = 1 par NAND (ordres de grandeur « grand, moyen, petit, petit » du cahier).
  Ce sont des valeurs que j'ai choisies pour pouvoir démarrer, pas des valeurs du cahier.
- Compteur de réutilisations par composant (`reuse_count`), sans effet sur les choix de l'IA (décision Q3).
- On juge le circuit **après nettoyage** (celui qui sera enregistré). Sinon une NAND rebouclée qui n'alimente aucune sortie le rendrait « instable », alors que la
  bibliothèque le garde stable une fois nettoyé (la stabilité porte sur toutes les NAND).
- Un circuit sans sortie est refusé (0 point, sans motif de filtre) : le cahier ne le range pas dans les 5 filtres, mais la bibliothèque le refuse.
  Un circuit invalide (composant inconnu) ou plus grand que les limites de la bibliothèque lève l'erreur au lieu d'être « refusé » : c'est une erreur de réglage.

**Interprétations à confirmer par Téo** (le cahier ne précise pas) :

1. Le bonus de réutilisation ne vaut que pour une **nouveauté** (« une nouvelle découverte »), pas pour un record.
2. Il se compte **par composant distinct** posé dans le circuit gardé : poser trois fois NOT = une réutilisation de NOT.
3. Seuls les composants du circuit **gardé** comptent : un composant posé sans servir à rien ne rapporte rien (anti-triche).

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `35 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 16 source files` |
| `pytest` | `656 passed` (627 avant, 29 nouveaux) |
| Mutations (copie hors du projet) | 23 erreurs volontaires dans `reward.py` : 22 détectées, 1 équivalente |

Le mutant équivalent : enregistrer le circuit déjà nettoyé au lieu de l'original donne le même résultat, car `register` nettoie lui-même (le nettoyage est idempotent).

### Étape 4 faite : boucle d'évolution (`evolution.py`, `tests/test_evolution.py`, `errors.py`)

- `Evolution(library, rules, settings, reward_settings, seed)` ; `step()` fait une génération et rend un `GenerationReport` (numéro, nombre d'essais, découvertes =
  nouveautés et records, récompense totale, `new_count` = nombre de nouveautés, records exclus : c'est ce que le changement de palier regardera).
- Un enfant = un parent tiré au hasard + un nombre de mutations d'affilée tiré entre `min_mutations` et `max_mutations`, puis évaluation par `RewardTracker` (étape 3).
- **Parents (décision Q1)** : le circuit vide (1 entrée, 1 sortie), la **définition de chaque composant** de la bibliothèque (c'est déjà le plus petit circuit de la signature,
  un record la remplace), et les `recent_size` derniers circuits acceptés par les filtres, nettoyés. Les parents ne sont jamais modifiés (copies).
- `rules` (palier) est un attribut modifiable entre deux générations : l'étape 5 s'en servira.
- Le hasard vient d'un `random.Random(seed)` créé par l'IA : même graine, même déroulement (testé, état global de `random` sans effet).
- Erreur dédiée : `InvalidEvolutionSettingsError`.

**Valeurs de départ (à confirmer par Téo, à régler par essais)** : 50 enfants par génération, 1 à **12** mutations par enfant, 20 circuits récents.
Choisies par un essai chiffré (script jetable, 2 à 8 graines par cas, pas un test) :

| Essai | Résultat |
| --- | --- |
| Palier 1 : générations pour trouver NOT (8 graines, 50 enfants) | Toujours trouvé ; au plus 43 générations (max 4 mutations), au plus 19 (max 8), au plus 15 (max 12) ; moins d'une demi-seconde pour 8 graines |
| Palier 2, 300 générations | max 6 : NOT, NAND, ORNOT, AND ; max 12 : en plus OR et ANDNOT |
| Palier 2, 2000 générations, max 12 | selon la graine : 7 à 9 composants (une exécution a trouvé les 8 portes du palier 2 en 500 générations, d'autres n'ont pas encore NOR/XOR/XNOR) ; max 16 n'apporte rien de plus ; 100 circuits récents au lieu de 20 : résultats mélangés |
| Vitesse | environ 10 ms par génération de 50 enfants (environ 5 000 essais par seconde) |

**À retenir pour l'étape 6** : la boucle fonctionne, mais **trouver les 8 portes du palier 2 avec les tailles minimales à coup sûr n'est pas acquis**. Une exécution a trouvé XOR avec 5 NAND
(le minimum est 4) et s'y est arrêtée ; d'autres n'ont pas trouvé NOR en 2000 générations. Il faudra régler (nombre de générations, mutations, circuits récents) et peut-être
revoir le choix des parents. L'échantillon de l'essai est petit (2 graines pour les longues exécutions).

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `37 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 17 source files` |
| `pytest` | `677 passed` (656 avant, 21 nouveaux) |
| Mutations (copie hors du projet) | 25 erreurs volontaires dans `evolution.py`, 25 détectées |

Les mutations ont trouvé un trou dans **mes tests** (2 survivantes) : mes exécutions de test ne contenaient aucun record, donc « les records sont des découvertes » et « new_count ignore les records »
tournaient à vide. Test remplacé par une exécution déterministe qui produit des records (graine 4, palier 2). Autre erreur de ma part, corrigée avant le commit : 4 tests supposaient
qu'on trouve NOT en 10 générations de 20 enfants ; ils partent maintenant d'un état explicite (NOT déjà trouvé).

### Environnement de cette session

Machine Linux, Python 3.13.16 (vérifié), `python/.venv` recréé avec `requirements-dev.txt` (versions identiques : pytest 9.1.1, ruff 0.17.0, mypy 2.4.0).
L'état de départ était le même que dans le journal (439 tests). Python 3.11 : toujours pas vérifié par exécution.

### Ce qui reste (phase 4)

Étapes 5 et 6 (paliers, test de la phase). Aucune n'est commencée.
Toujours ouverts : interprétation de la CLK (phase 6), valeur de N et poids de la récompense (par essais).
Rappel : reporter dans le document en ligne les modifications du cahier (voir `docs/modifications_cahier_proposees.md`, points 1 à 9).

---

## 10 octobre 2026 — Mise à jour de la copie locale du cahier

### Ce qui est fait

Sur demande explicite de Téo (« modifie la copie du cahier »), les 6 points de `docs/modifications_cahier_proposees.md` ont été appliqués à
`docs/cahier_des_charges.md` : T_max + 1 tops (texte et tableau des trois cas), composants équivalents (entrées échangées, une seule découverte),
cases cochées dans « Points à trancher » (composants équivalents ; 15 et 15 par défaut, réglable jusqu'à aucune limite), palier 2 et test de la
phase 4 (8 découvertes), liste des noms connus, précisions sur le JSON (`x`/`y` calculés par Python, type `COMPOSANT`, clé `etat`).
Une note a été ajoutée dans l'en-tête de la copie : elle diffère maintenant du document en ligne.

Chaque point a été vérifié avant d'être écrit : décisions de Téo relues dans ce journal (sessions 2 et 3), et valeurs relues dans le code
(`simulation.py` : T_max + 1 ; `signature.py` : noms connus ; `library.py` : 15 et 15 ; `serialization.py` et `layout.py` : format JSON).

### Contrôles

Aucun code modifié (documentation seulement), donc `ruff`, `mypy` et `pytest` n'ont pas été relancés. Le dossier `python/.venv` n'existe pas
sur la machine de cette session (Linux, pas le Mac de Téo) : ces contrôles ne pouvaient de toute façon pas y être exécutés.

### Ce qui reste

- **Reporter les 6 modifications dans le document en ligne** (claude.ai), sinon une ré-exportation les effacerait.
- Palier 3 : « 218 » fonctions restent après les filtres, soit **68 découvertes** (calcul indépendant, voir point 9 de
  `docs/modifications_cahier_proposees.md`). Le cahier n'a pas été modifié sur ce point (proposé seulement).
- Points à trancher : **tranchés par Téo avant la phase 4** : taille maximale d'un circuit = aucune limite fixe, seulement la pénalité de taille ;
  critère de changement de palier = N réglable, valeur de départ trouvée par essais en phase 4 (points 7 et 8 de
  `docs/modifications_cahier_proposees.md`, pas encore appliqués au cahier). Toujours ouverts : interprétation de la CLK
  (Téo a noté dans le cahier : « CLK = horloge donc un petit composant qui peut faire une horloge », à clarifier avant la phase 6)
  et poids de la récompense (par essais, phase 4).
- **Phase 4** : un plan est proposé à Téo avant tout code (aucun fichier de code écrit).

---

## 10 octobre 2026 — Session 3 : phase 3 (affichage Unity statique)

### Ce qui est fait

Quatre sous-étapes, chacune testée, éprouvée par mutations puis commitée :

| # | Commit | Contenu |
| --- | --- | --- |
| 1 | `ed4f143` | Python `layout.py` : placement des nœuds (colonnes, boucles ignorées, lignes) |
| 2 | `c05c3a5` | Python `snapshot.py` (valeurs 0/1), JSON avec `x`, `y` et `etat`, `examples.py` + dossier `circuits/` (31 fichiers) |
| 3 | `d607114` | Unity : lecture et vérification du JSON, géométrie (boîtes, broches, tracé des câbles) |
| 4 | `cede146` | Unity : dessin (câbles et portes colorés par valeur), viewer qui démarre au Play ; correctifs de lisibilité vus sur les images |

Le test de la phase 3 du cahier est atteint : les circuits de la phase 1 s'affichent, câbles colorés selon leur valeur. La preuve est
automatique (couleur lue **au pixel** de chaque câble des 31 fichiers, dans une image rendue par Unity) et visuelle (images regardées).
**Il reste à faire une vérification visuelle par Téo dans son éditeur** (voir « Ce qui reste »).

Réponses de Téo en début de session : JSON avec `entrees` et `sorties` sur un nœud composant (oui), liste de noms connus (oui),
repli au-delà de 5 040 ordres (acceptable). Et : « Python calcule, Unity ne fait que du front end » : Python calcule les positions
`x` et `y` et les valeurs 0/1 des fils.

### Résultats des contrôles (fin de session)

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `29 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 13 source files` |
| `pytest` | `439 passed` (369 en début de session) |
| Unity EditMode | 65 réussis (`tools/run_unity_tests.sh EditMode`) |
| Unity PlayMode | 2 réussis (`tools/run_unity_tests.sh PlayMode`) |

Mutations sur une copie hors du projet : 35 erreurs volontaires dans le Python, 29 dans le C# ; toutes détectées. Deux survivantes ont
été examinées au lieu d'être ignorées : une condition inutile de `HasState` (simplifiée) et un test du placement qui ne distinguait pas la
hauteur d'une broche de celle du centre du composant (réécrit).

### Décisions prises (plan validé par Téo avec « OK avec tes recommandations »)

1. `x` et `y` sont calculés par Python et **écrits partout**, bibliothèque comprise. Un NOT redonne exactement l'exemple du cahier
   ((0,0), (2,0), (4,0)). Cela remplace la décision de la phase 2 (« jamais écrits »).
2. Format `etat` : `{"top", "stable", "noeuds": [...], "cables": [...]}`, listes dans l'ordre de `noeuds` et `cables`. Ignoré à la lecture.
   Pas de valeurs pour un circuit qui contient des composants (câbles gris neutre).
3. Unity lit directement le dossier `circuits/` (outil de développement ; en phase 5, ce sera le socket).
4. Placement des nœuds en Python, tracé exact des câbles entre deux broches en Unity.
5. Un peu d'interface : liste cliquable (IMGUI, car seul le **nouveau** Input System est actif).
6. Aucune modification de la scène, de `ProjectSettings/`, de `Packages/` ni d'un `.meta` existant : le viewer démarre tout seul au Play.
7. Les champs des classes C# de données sont en français (`noeuds`, `cables`, `etat`...) : `JsonUtility` exige les noms des clés du fichier.

### Ce que la vérification a appris

- **Les tests de pixels ne suffisent pas, il faut regarder les images.** Elles ont montré deux défauts de lisibilité que mes points de mesure
  ne pouvaient pas voir : (a) un câble qui saute une colonne passait **à travers** une porte (tronçon vertical au milieu) : corrigé dans Unity ;
  (b) deux câbles se **superposaient** à droite de la bascule SR (la porte Q̄ à la même hauteur que le câble de Q) : corrigé dans le placement Python,
  où une boîte est descendue si elle tombe sur un câble qui saute sa colonne.
- Un test de la phase 2 que j'avais annoncé « 2 » à modifier était en fait **3** (le dictionnaire d'un nœud composant). Un test de la sous-étape 3
  a été modifié parce que la règle de tracé a changé après avoir regardé l'image.
- Unity ne peut pas être lancé une 2e fois sur un projet déjà ouvert : les tests tournent sur une **copie** (`tools/run_unity_tests.sh`,
  environ 40 s pour la première importation). Le rendu hors écran fonctionne en mode batch (Metal, URP).

### Limites connues

- Le tracé des câbles reste simple. Un câble qui revient en arrière passe par un couloir au-dessus des deux broches : il peut traverser une boîte
  haute d'une colonne intermédiaire. Deux câbles de sources différentes qui montent au même `x` vers la même numéro de broche peuvent se confondre.
- Les valeurs 0/1 ne sont pas calculées pour un circuit avec composants (leurs fils internes ne sont pas suivis).
- La règle de hauteur d'une boîte (`box_height`) est écrite deux fois (Python et C#) ; les deux sont testées avec les mêmes valeurs, mais un changement
  doit être fait des deux côtés. Idem pour `XScale`, `YScale` côté Unity.
- Si le placement change, `circuits/` doit être régénéré (commande dans `CLAUDE.md`).
- `JsonUtility` ne distingue pas une clé `noeuds` absente d'une liste vide : un fichier sans `noeuds` est lu comme un circuit vide.
- Pas de navigation au clavier dans le viewer (il faudrait le nouveau Input System).
- Python 3.11 : toujours pas vérifié par exécution.

### Points à valider par Téo

- **Vérification visuelle dans Unity** : ouvrir l'éditeur (hors Play), laisser Unity importer, puis lancer le Play : la liste des 31 circuits
  apparaît à gauche ; cliquer sur quelques circuits. Les couleurs (0 bleu-gris, 1 jaune, instable en rouge sombre), les étiquettes
  (A, B, NAND, S, S1, S2) et la disposition te conviennent-elles ?
- **Fichiers `.meta`** : ton Unity doit générer ceux de `Assets/Scripts/`, `Assets/Tests/` et de leurs fichiers ; ils seront commités à part.
- `tools/run_unity_tests.sh` est un fichier ajouté en dehors du plan (pour rendre la vérification Unity reproductible).
- Cahier : un fichier de circuit contient maintenant `x`, `y` et, facultativement, `etat` ; le message « etat » du cahier et la clé `etat` du fichier
  ont la même forme.

### Ce qui reste

- Commit des `.meta` générés par Unity, puis vérification visuelle par Téo.
- **Phase 4** (IA évolutionnaire, paliers 1 à 3 : mutations, récompense, filtres, changement de palier) : non commencée.

---

## 10 octobre 2026 — Session 2 : phase 2 (bibliothèque et encapsulation)

### Ce qui est fait

Cinq sous-étapes, chacune testée, éprouvée par mutations puis commitée :

| # | Commit | Modules | Contenu |
| --- | --- | --- | --- |
| 1 | `b9e8ddd` | `circuit.py`, `flatten.py` | Type `COMPONENT` posé par référence, aplatissement (retards exacts), coût |
| 2 | `90f6f3f` | `cleanup.py` | Nettoyage : retire ce qui n'a aucun chemin vers une sortie |
| 3 | `be7972a` | `signature.py`, `behavior.py` | Signature canonique (entrées permutées = même signature), noms connus |
| 4 | `eb94dc1` | `library.py` | Bibliothèque : `NEW` / `RECORD` / `KNOWN`, nommage, limites 15/15 réglables |
| 5 | `dff5c0d` | `serialization.py`, `library.py` | JSON : sauvegarde et relecture (un fichier `<nom>.json` par composant) |

Le test de la phase 2 du cahier est atteint : un XOR construit avec des composants NOT et AND a la même signature
(`0b0110`) que sa version aplatie, avec 12 NAND, puis la bibliothèque le remplace par la version à 4 NAND (record).

Réponses de Téo prises en compte : composants équivalents par entrées inversées = **une seule découverte** ;
nombre maximal d'entrées et de sorties par composant = **15 et 15**, avec la possibilité de n'avoir **aucune limite**
(`LibraryLimits.unlimited()`).

### Résultats des contrôles (fin de session)

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `22 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 10 source files` |
| `pytest` | `369 passed` (99 en début de session ; +270 en phase 2) |

Les tests ont été éprouvés par mutations sur une copie hors du projet (62 erreurs volontaires dans le code).
Chaque série a trouvé des trous dans **mes tests**, tous comblés : test de refus d'un composant trop faible (sous-étape 1),
test de l'ordre des broches qui ne couvrait que des échanges et pas des cycles de 3 entrées (sous-étape 4), test d'identifiant
booléen qui échouait pour une autre raison (sous-étape 5). Un mutant était équivalent (une sortie ne peut jamais être
retirée par le nettoyage) : vérifié par une mutation combinée. Une série n'avait rien affiché (la commande `timeout` n'existe
pas sur macOS) : reconnue comme invalide et refaite avec `perl`.

### Décisions prises (plan validé par Téo avec « OK avec tes recommandations »)

1. **Entrées « inversées »** = entrées **échangées** (permutation), pas niées. AND et NOR restent deux découvertes. Les sorties
   ne sont jamais permutées. Conséquence : au palier 2, les 10 fonctions du cahier font **8 découvertes** (vérifié par test).
2. **Forme canonique** : entrées rangées par une grandeur invariante, entrées symétriques regroupées, puis on essaie les ordres
   restants. Exacte jusqu'à `MAX_ARRANGEMENTS = 5040` ordres à essayer ; au-delà, l'ordre d'origine est gardé et
   `CanonicalForm.exact` vaut `False` (jamais de fausse fusion, seul un doublon peut échapper). Vérifiée contre le lemme de Burnside :
   2, 4, 12, 80 et 3 984 signatures pour toutes les fonctions à 0, 1, 2, 3 et 4 entrées.
3. **Ordre des broches** d'un composant = celui de sa première découverte. Un record équivalent est réordonné pour le garder
   (les circuits qui utilisent le composant ne changent pas de comportement).
4. **Signature = table de vérité** : un circuit instable est refusé. Les composants à mémoire attendent la phase 6.
5. **Noms connus** : NOT, AND, OR, NAND, NOR, XOR, XNOR, ANDNOT (A ET NON B), ORNOT (A OU NON B), MAJ, MUX. Sinon `C-001`, `C-002`...
6. **JSON** : format de l'exemple du cahier ; ajout du type `COMPOSANT` avec `ref`, `entrees`, `sorties` ; `x` et `y` acceptés à la
   lecture et ignorés, jamais écrits ; un fichier `<nom>.json` par composant dans un dossier donné par l'appelant.
7. Petites décisions : le nettoyage retire aussi les composants inutiles ; le coût est recalculé à la demande (il baisse quand
   un composant utilisé est remplacé) ; une boucle de fils sans NAND est refusée à l'aplatissement ; un circuit sans sortie est
   refusé ; à coût égal ce n'est pas un record ; les filtres anti-triche restent en phase 4.

Écarts avec le plan : `Component` ne contient pas de coût (c'est `Library.cost`, recalculé) ; `input_patterns` est maintenant
construit par doublement (193 ms -> 0,03 ms à 15 entrées, résultat identique) ; `Node` se vérifie lui-même ;
`Circuit` gagne `add_component_node`, `copy`, `from_parts`, `with_inputs_reordered` ; `tests/builders.py` partage les petits circuits.

### Limites connues (à garder en tête)

- **Récursion** : `flatten` est récursif. Mesuré avec la limite par défaut de Python : OK jusqu'à 240 niveaux de composants dans des
  composants, `ComponentNestingError` (erreur dédiée, pas un plantage) à partir de 250. À réécrire sans récursion si la phase 4 en
  produit de si profonds.
- `Circuit.remove_node` relit tous les câbles à chaque appel (temps proportionnel au nombre de câbles) : à surveiller si les
  mutations de la phase 4 deviennent lentes.
- Au-delà de `MAX_ARRANGEMENTS`, deux circuits identiques à une permutation près peuvent compter pour deux découvertes.
- Après `Library.load`, `names()` suit l'ordre alphabétique des fichiers (pas l'ordre d'apparition).
- Une table de vérité occupe `2^n` bits par signal : « aucune limite » de la bibliothèque reste limitée par la mémoire.
- Python 3.11 : toujours pas vérifié par exécution (seul 3.14.7 est installé).

### Points à valider par Téo

- Les ajouts au format JSON (`entrees` et `sorties` sur un nœud composant, aucun `x` ni `y` écrit).
- La liste des noms connus, en particulier `ANDNOT`, `ORNOT`, `MAJ` et `MUX`.
- `MAX_ARRANGEMENTS = 5040` et le repli « non exact » au-delà.
- **Modifications à reporter dans le cahier** (lecture seule pour Claude) : (a) « Composants équivalents » et « Nombre maximal
  d'entrées et de sorties par composant » sont tranchés (une seule découverte pour des entrées échangées ; 15 et 15 par défaut, réglable
  jusqu'à aucune limite) ; (b) le test de la phase 4 parle des « 10 fonctions à 2 entrées » : avec la décision (a), ce sont 8 découvertes ;
  (c) le format JSON gagne le type `COMPOSANT` ; (d) rappel de la session 1 : « T_max tops » devient « T_max + 1 tops ».
- Erreur dans le message du commit `be7972a` : il annonce 59 tests pour `test_signature.py`, il y en a 64. Pas réécrit (`CLAUDE.md`
  interdit de réécrire l'historique sans demande).

### Ce qui reste

- **Phase 3** (affichage Unity statique) : Unity doit lire le JSON. `circuit_to_json` produit déjà le format. **À trancher en phase 3** :
  ni le modèle Python ni le JSON n'ont de positions `x` et `y` (l'exemple du cahier en contient). Qui les calcule : Unity (placement
  automatique) ou Python ?
- Phases 4 à 7 inchangées.

### Questions ouvertes

Parmi les « points à trancher » du cahier, il reste : taille maximale d'un circuit (aucune limite fixe proposée, à confirmer),
interprétation de la CLK, poids de la formule de récompense, critère de changement de palier.

---

## 10 octobre 2026 — Session 1 : phase 0 (environnement) et phase 1 (simulateur logique)

### Ce qui est fait

**Phase 0 — préparation** (commit `64598b3`)

- Dépôt git initialisé (branche `main`) et `.gitignore` Unity + Python + macOS.
- Environnement virtuel `python/.venv` (Python 3.14.7 de Homebrew) avec pytest, ruff et mypy.
  Versions installées, figées dans `python/requirements-dev.txt` : pytest 9.1.1, ruff 0.17.0, mypy 2.4.0.
- `python/pyproject.toml` : pytest (`pythonpath = ["src"]`), ruff (docstrings, annotations, pas de `print`,
  pas de nombre magique, complexité), mypy en mode strict sur `src/`.
- Méthode d'import choisie : `pythonpath` de pytest, sans installation éditable (aucune bibliothèque de plus).
  Prouvée par contraste : avec `-o pythonpath=`, le test échoue avec `ModuleNotFoundError`.

**Phase 1 — simulateur logique**, en trois sous-étapes, chacune testée puis commitée :

| Sous-étape | Commit | Fichiers | Contenu |
| --- | --- | --- | --- |
| 1 | `56234de` | `errors.py`, `circuit.py`, `test_circuit.py` | Nœuds, broches, câbles, règles de câblage (section A) |
| 2 | `b9b0259` | `simulation.py`, `test_simulation.py` (+ `SimulationError`) | Tops, retard de 1 top, règle de stabilité T_max + 1 (section B) |
| 3 | `6ed6eff` | `behavior.py`, `test_behavior.py` | Bit-parallèle, table de vérité, séquences, mémoire (sections C et D) |

Tout le tableau E de la spécification est testé, avec les valeurs attendues exactes
(NOT `0b01`, NAND `0b0111`, AND `0b1000`, OR `0b1110`, XOR `0b0110`, constante 1 `0b1`, sortie non reliée 0,
NOT rebouclé UNSTABLE, bascule SR Q = 1, 1, 0, 0 avec mémoire, métastabilité UNSTABLE, règles de câblage, suppression).
**Aucun écart** entre l'implémentation et le tableau E : aucun test ni aucune valeur attendue n'a été modifié.

Le test de la phase 1 du cahier est donc atteint : circuits écrits à la main (NOT, AND, OR, XOR, bascule SR) avec leur table
attendue, NAND rebouclée détectée instable, câble illégal refusé.

### Résultats des contrôles (fin de session)

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `9 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 5 source files` |
| `pytest` | `99 passed` (circuit 32, simulation 32, comportement 34, paquet 1) |

Les tests ont aussi été éprouvés par mutations, sur une copie hors du projet : 5 erreurs volontaires en sous-étape 1,
7 en sous-étape 2 et 7 en sous-étape 3 dans le code ; toutes ont fait échouer au moins un test.
Une mutation n'avait pas été appliquée par erreur de motif : elle a été refaite, puis détectée.

Deux défauts trouvés par les outils et corrigés dans le code (pas dans la config) :
`Pin` en `NamedTuple` écrasait `tuple.index` (mypy), et `2**n` est typé `Any` (mypy, remplacé par `1 << n`).

### Décisions prises (ambiguïtés du plan, validées par Téo avec « OK avec tes recommandations »)

1. **Mauvais genre de broche** : le genre est déduit de la place dans l'appel (`connect(source, sink)`), comme `de` / `vers`
   dans le JSON. « Mauvais genre » si l'index n'existe pas dans le genre attendu mais existe dans l'autre ;
   « index inexistant » s'il n'existe dans aucun.
2. **`disconnect` et `remove_node`** : toute situation anormale lève une exception (nœud, index ou genre faux, puits sans câble) ; circuit inchangé.
3. **Délai** : T_max + 1 tops (règle du prompt), pas T_max (formulation du cahier). Voir « Points à valider ».
4. **Résultat UNSTABLE** : les valeurs rendues sont celles du dernier top calculé, avec le statut UNSTABLE qui les rend non significatives.
5. **Séquence** : tous les pas sont simulés, même après un pas instable (état repris = dernier top calculé) ; la séquence entière est alors UNSTABLE.
6. **Mémoire** : cherchée seulement dans une séquence stable, sur le vecteur complet des sorties.
7. **Exceptions** : famille `CircuitError` (une classe par cas de refus) ; `SimulationError` pour les données de simulation invalides.
8. **Données de simulation invalides** (nombre d'entrées, valeur hors masque, masque non fait de 1, état de mauvaise taille) : `SimulationError`.
9. **Aucune limite** de taille de circuit ni de nombre d'entrées (deux « points à trancher » du cahier, hors phase 1).
10. **Moteur unique** : `settle` travaille sur des entiers avec un masque ; masque `1` pour une combinaison, `(1 << 2**n) - 1` pour le bit-parallèle.

Extensibilité : un `Node` stocke son propre nombre de puits et de sources ; le moteur décide à un seul endroit
(`_ORIGIN_OF_KIND` dans `simulation.py`) quels types de nœuds peuvent servir de source. Les composants (phase 2) et la CLK (phase 6)
s'ajouteront sans réécrire `Circuit`.

### Points à valider par Téo

- **Cahier des charges, section « La simulation par tops »** : il dit que la simulation « attend au maximum T_max tops ».
  Le prompt de la phase 1 dit T_max + 1, et c'est nécessaire (un NOT, 1 NAND, a besoin d'un 2e top pour être confirmé stable ;
  la bascule SR est stable exactement au top 3 = T_max + 1). Le cahier est en lecture seule pour Claude, donc voici une
  reformulation proposée : « La simulation calcule au plus T_max + 1 tops : jusqu'à T_max tops pour atteindre l'état final d'un
  circuit sans boucle, plus un top qui confirme que plus rien ne change. »
- **`pyproject.toml`, dossier `tests/`** : les règles D103 (docstring de fonction) et PLR2004 (nombre magique) y sont désactivées,
  car chaque test cite sa règle en commentaire et ses valeurs attendues (`0b0111`...) sont voulues. À confirmer.
- **Doublon du cahier** : `logicAI — Cahier des charges.md` à la racine est ignoré par git (la référence est
  `docs/cahier_des_charges.md`). À supprimer par Téo s'il n'est plus utile.
- **Python 3.11** : seul Python 3.14.7 est installé, donc tout a été exécuté en 3.14. La compatibilité 3.11 est configurée
  (`requires-python`, `target-version = "py311"`, `python_version = "3.11"` pour mypy) mais **pas vérifiée par exécution**.

### Ce qui reste

- Phase 2 (non commencée) : bibliothèque et encapsulation (nettoyage, coût, nommage, aplatissement, JSON).
- Le moteur utilise `NodeKind` ; la phase 2 y ajoutera le type « composant », et l'aplatissement se fera avant la simulation.

### Questions ouvertes

Les « points à trancher » du cahier restent ouverts. Deux concernent la phase 2 :

- composants équivalents par inversion des entrées (une seule découverte ou deux) ;
- nombre maximal d'entrées et de sorties par composant.

Les autres concernent les phases 4 et suivantes (taille maximale, interprétation de la CLK, poids de la récompense, critère de changement de palier).
