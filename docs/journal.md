# Journal d'avancement — logicAI

Une entrée par session, la plus récente en haut. Le cahier des charges (`docs/cahier_des_charges.md`) reste la référence.

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
