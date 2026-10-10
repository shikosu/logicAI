# Journal d'avancement — logicAI

Une entrée par session, la plus récente en haut. Le cahier des charges (`docs/cahier_des_charges.md`) reste la référence.

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
