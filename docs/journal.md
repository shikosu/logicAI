# Journal d'avancement — logicAI

Une entrée par session, la plus récente en haut. Le cahier des charges (`docs/cahier_des_charges.md`) reste la référence.

---

## 10 octobre 2026 — Session 5 : phase 5 (liaison en direct), en cours

### Plan validé par Téo

Test du cahier : « on regarde l'IA construire pendant que l'entraînement continue à pleine vitesse ». Décisions de Téo : **Python écoute sur 127.0.0.1, Unity se connecte** ;
**Python testé ici, C# écrit ici mais vérifié par Téo sur son Mac** (ni Unity, ni dotnet, ni Mono sur cette machine : le C# ne peut être ni compilé ni testé ici ; vérifié par commande).
Étapes Python : (1) `protocol.py`, (2) `replay.py` (ordre de pose), (3) `live_server.py` (transport non bloquant), (4) `live_director.py` (quoi montrer, à quel rythme),
(5) branchement dans `Evolution` + `python -m logicai.live`, (6) test de la phase côté Python. Étapes C# : (7) messages, (8) connexion, (9) interface. Plan complet : voir le fichier de plan de la session.

Protocole proposé (le cahier ne le précise pas) : une ligne de JSON UTF-8 par message, clé `"message"` = type ; types `circuit`, `etat`, `decouverte`, `stats` (le type `action` est pour la phase 7).

### Étape 1 faite : messages (`protocol.py`, `tests/test_protocol.py`, `serialization.py`, `errors.py`)

- `circuit_message`, `state_message`, `discovery_message` (nom, genre `nouveaute`/`record`, coût, circuit avec composants, ordre de pose), `stats_message` ; `encode_message` (une seule ligne, UTF-8 sans échappement des accents,
  écriture compacte, NaN et infini refusés) et `decode_message` ; erreurs dédiées `ProtocolError` / `InvalidMessageError`.
- `serialization._state_to_dict` devient publique (`state_to_dict`) : la clé `etat` d'un fichier et le message `etat` ont la même forme (cahier).
- Vérifié : un socket local fonctionne dans cet environnement (essai jetable).

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `42 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 19 source files` |
| `pytest` | `723 passed` (701 avant, 22 nouveaux) |
| Mutations (copie hors du projet) | 17 erreurs volontaires dans `protocol.py`, 17 détectées |

Erreur de ma part, corrigée avant le commit : mon test supposait que le relevé d'un NOT stabilisé est au top 1 ; le code de la phase 3 donne le top 2 (le top 1 fait passer la NAND à 1, le top 2 confirme
que rien ne bouge), conformément à sa définition (« top de confirmation compris »).

### Étape 2 faite : ordre de pose (`replay.py`, `tests/test_replay.py`, `serialization.py`, `errors.py`)

- `placement_order(circuit)` : **les nœuds dans l'ordre des signaux, puis les câbles** (cahier). Nœuds triés par colonne `x` puis `y` (positions de `layout.py`), câbles après tous les nœuds, triés selon la pose de leur
  puits puis le numéro de broche. Chaque étape est `{"action":"poser","noeud":{...}}` (nœud écrit comme dans un fichier, avec `x` et `y`) ou `{"action":"cabler","de":[n,p],"vers":[n,p]}` : le vocabulaire du futur
  message « action » (phase 7).
- `circuit_from_placement(steps, count)` fait l'inverse (les `count` premières étapes) : c'est ce que fera Unity pour la rediffusion, et ce qui permet de tester l'ordre. Réutilise `circuit_from_dict`.
  Étapes incohérentes (action inconnue, câble avant son nœud, broche mal formée) : `InvalidPlacementError` ; règles du circuit violées (puits déjà relié, nœud posé deux fois) : `LibraryFormatError`.
- `serialization._node_to_dict` devient publique (`node_to_dict`).
- Le NOT redonne exactement l'exemple du cahier : entrée (0, 0), NAND (2, 0), sortie (4, 0), puis ses 3 câbles.
- Test principal : rejouer l'ordre redonne exactement le circuit (même nœuds et identifiants, mêmes câbles), y compris sur 40 circuits au hasard avec boucles, et le comportement (table de vérité) est conservé ;
  chaque préfixe de l'ordre est un circuit légal qui grandit d'une pièce à la fois.

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `44 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 20 source files` |
| `pytest` | `799 passed` en environ 59 s (723 avant, 76 nouveaux) |
| Mutations (copie hors du projet) | 18 erreurs volontaires dans `replay.py`, 17 détectées, 1 équivalente |

Deux trous de **mes tests**, trouvés par les mutations et comblés : (1) mes circuits câblaient toujours la broche 0 avant la broche 1, donc l'ordre d'insertion donnait par hasard le bon ordre des câbles ; test ajouté avec la
broche 1 câblée en premier ; (2) le cas « broche courte » échouait pour une autre raison (un autre nœud pas encore posé) et ne prouvait rien sur la broche ; sa mise en place pose maintenant tous les nœuds avant l'étape fautive.
Le mutant équivalent : retirer l'identifiant de la clé de tri des nœuds ne change rien, car le tri de Python est stable et `circuit.nodes()` est déjà dans l'ordre des identifiants (je garde l'identifiant : il rend le déterminisme explicite).

### Étape 3 faite : serveur de la liaison (`live_server.py`, `tests/test_live_server.py`, `errors.py`)

- `LiveServer(port, max_pending)` : Python **écoute sur 127.0.0.1** (jamais une autre interface), Unity se connecte. `start()` / `stop()` / `with`, `port`, `address`, `connected`, `dropped`, `send(message)`.
  Bibliothèque standard seulement (`socket`, `select`, `threading`) : aucune dépendance ajoutée.
- **L'entraînement n'attend jamais Unity** : un seul fil d'E/S avec `select` et des sockets non bloquants (il n'écrit que ce que le système accepte) ; `send` encode le message, le met dans une file bornée (200 messages)
  et rend la main. Si Unity ne suit pas : on jette les plus anciens `circuit`/`etat`/`stats` (`dropped` les compte) ; les `decouverte` ne sont **jamais** jetées.
- Le serveur garde toutes les découvertes et les dernières `stats` : un Unity qui se connecte en retard reçoit d'abord ce qu'il a manqué, puis le direct, chaque message une seule fois. Sans client, `circuit` et `etat`
  sont abandonnés. Un seul client à la fois (le nouveau remplace l'ancien) ; ce que Unity écrit est ignoré.
- `send` ne lève jamais d'erreur à cause du réseau (ni avant le démarrage, ni après l'arrêt) ; il refuse seulement un message mal formé. Erreur dédiée `LiveServerError` (port pris, 2e démarrage, file de 0).

**Défaut réel trouvé par un test instable, corrigé** : dans la boucle d'E/S, le client était mémorisé au début du tour. Si un nouveau client était accepté pendant ce tour, j'écrivais sur l'ancienne socket (fermée) : l'erreur
fermait le **nouveau** client. Environ 1 exécution sur 3 d'un test de remplacement échouait. Correction : traiter d'abord les événements du client du début du tour (seulement si c'est encore le client courant),
accepter en dernier. Vérifié : 60 exécutions de suite des tests de remplacement et de retour, 0 échec ; 8 puis 5 exécutions du fichier complet, 0 échec.
Autre simplification : trois mécanismes redondants de nettoyage de la file (qui se masquaient entre eux) ont été réduits à un seul, dans la fermeture du client, avec deux tests qui le prouvent.

À savoir : un message en direct envoyé *pendant* un remplacement de client est abandonné (seuls comptent les derniers états ; les découvertes et les stats sont dans l'historique). Les tests se synchronisent donc sur
la lecture de la première ligne d'historique.

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `46 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 21 source files` |
| `pytest` | `822 passed` en environ 68 s (799 avant, 23 nouveaux, environ 7,5 s pour ce fichier) |
| Mutations (copie hors du projet) | 22 erreurs volontaires dans `live_server.py`, 21 détectées, 1 équivalente |

La 1re série de mutations avait laissé survivre 7 erreurs : 3 trous de **mes tests** (adresse d'écoute vérifiée côté pair au lieu de côté serveur ; `dropped` non vérifié sans client ; seuls les `etat` inondés, pas les `stats` ni les
`circuit`), 3 mécanismes redondants (simplifiés, voir ci-dessus), et 1 équivalente : ne pas fermer explicitement la socket d'écoute à l'arrêt revient au même en CPython (elle est fermée à la destruction de l'objet) ;
je garde la fermeture explicite.

### Étape 4 faite : ce qu'on montre et à quel rythme (`live_show.py`, `live_director.py`, tests, `errors.py`)

**`live_show.py` — ce qu'on montre.** `trial_messages(circuit, definitions)` : un message `circuit` (le circuit **aplati puis nettoyé**, nom `essai`, avec ses positions) suivi, pour chaque combinaison d'entrées,
des messages `etat` **top par top**, du top 0 au premier top stable (ou jusqu'à T_max + 1 si le circuit est instable). L'entrée i de la combinaison k vaut le bit i de k (convention des tables de vérité) ; au plus
8 combinaisons (`MAX_SHOWN_COMBINATIONS`). Aplati parce que les valeurs ne sont pas suivies dans un composant (limite de la phase 3) ; nettoyé pour montrer ce que le simulateur garde.
Les images du NOT (A = 0 : top 0 la NAND vaut encore 0, top 1 elle vaut 1 ; A = 1 : déjà stable) ont été calculées **à la main** d'après le cahier avant de lancer le test, et le code les redonne.

**`live_director.py` — quand.** `LiveDirector(send, clock, trial_interval, frame_interval, stats_interval)`. Le fil d'entraînement ne fait que des appels courts : `wants_trial()`, `offer_trial(messages)`,
`announce_discovery(message)`, `update_stats(message)` ; il construit lui-même les messages (donc seul à toucher à la bibliothèque, pas de course). Un fil de présentation (`start`/`stop`) appelle `pump()` toutes les 20 ms :
un message par image toutes les `frame_interval` secondes (le 1er tout de suite, jamais deux d'un coup, même en retard) ; un nouvel essai n'est voulu que `trial_interval` après la dernière image ; stats au plus toutes les
`stats_interval` s et seulement si elles sont nouvelles ; découvertes envoyées au prochain `pump`, dans l'ordre, sans perturber le rythme des images. Une erreur d'envoi est journalisée et ignorée par le fil.
Horloge injectée : les tests utilisent une fausse horloge, sans attente réelle.

**Valeurs de départ (à régler par essais, de ma main)** : 3 s de pause entre deux essais montrés, 0,5 s par image, stats au plus 1 par seconde. À titre d'ordre de grandeur, un essai à 2 entrées dure de l'ordre de 5 à 6 s.

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `50 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 23 source files` |
| `pytest` | `854 passed` en environ 66 s (822 avant, 32 nouveaux : 13 + 19 ; 0,5 s pour ces deux fichiers) |
| Mutations (copie hors du projet) | `live_show.py` 13 erreurs volontaires, 13 détectées ; `live_director.py` 23, 23 détectées |

Deux trous de **mes tests**, trouvés par les mutations et comblés : le nom `essai` n'était comparé qu'à la constante qui le définit (donc toujours vrai) ; il est maintenant écrit en dur, car Unity l'affiche dans sa ligne d'état ;
et proposer une suite vide pendant un essai en cours (qui doit être ignorée sans interrompre l'essai) n'était testé qu'au repos.

### Étape 5 faite : branchement (`live.py`, crochet dans `evolution.py`, tests `test_live.py` et `test_evolution.py`)

- **Crochet** : `Evolution(..., on_trial=...)` rappelle `on_trial(enfant, résultat)` après chaque essai (l'enfant tel qu'essayé, nœuds inutiles compris). Facultatif, 9 lignes ; une erreur du crochet n'est pas cachée.
- **`LiveSession(director, seed, stalled_generations, ...)`** relie l'IA (bibliothèque vide, paliers via `Curriculum`) au directeur. À chaque essai : une **nouveauté ou un record** devient tout de suite un message `decouverte`
  (circuit tel que dans la bibliothèque à cet instant, coût aplati, ordre de pose de `replay.py`) ; sinon, si `director.wants_trial()`, un essai **accepté** est préparé (`live_show.trial_messages`) et proposé.
  À chaque génération : un message `stats` (palier, génération, nombre de découvertes, récompense moyenne = totale / essais). Une erreur d'affichage est journalisée et **ne casse jamais l'entraînement**.
- **Commande** : `cd python && PYTHONPATH=src .venv/bin/python -m logicai.live [--port N] [--seed S] [--generations G]` (sans `--generations`, jusqu'à Ctrl-C ; port 8765 par défaut). Journal sur stderr (pas de `print`),
  code de sortie 0, ou 2 si le port est pris (message clair, pas de traceback). **Vérifiée à la main sur cette machine** avec un faux Unity : NOT découvert, stats reçues, code 0.
  Elle n'est pas encore dans la section « Commandes vérifiées » de `CLAUDE.md` (fichier de Téo) : proposition d'y ajouter la ligne ci-dessus après sa propre vérification sur le Mac.
- **À retenir pour le C#** (constaté à la main) : un Unity qui se connecte en pleine animation reçoit des `etat` **sans** le message `circuit` qui les précède (parti avant sa connexion) ; il doit les ignorer tant qu'il n'a pas de circuit.
  Il peut donc se passer jusqu'à une pause + un essai (de l'ordre de 9 s) avant le premier essai visible ; la bibliothèque, elle, est remplie tout de suite par l'historique des `decouverte`.

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `52 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 24 source files` |
| `pytest` | `872 passed` en environ 70 s (854 avant, 18 nouveaux : 16 dans `test_live.py`, 2 pour le crochet) |
| Mutations (copie hors du projet) | `live.py` 26 erreurs volontaires, 26 détectées après correction ; crochet d'`Evolution` 5, 5 détectées |

Trous de **mes tests**, trouvés par les mutations et comblés : (1) mes essais (graine 0) ne contenaient aucun *record*, donc « record annoncé comme nouveauté » et « records ignorés » passaient ; trouvé la graine 5 (un NOT d'abord trouvé avec
plus de NAND, puis réduit) et ajouté un test qui exige un `record` après sa `nouveaute`, moins cher ; (2) la graine n'était jamais vérifiée (tout tournait avec 0) ; (3) la commande ne vérifiait pas qu'elle libère le port ni qu'elle arrête ses
fils en sortant ; (4) l'enfant « nettoyé » transmis à la place de l'enfant essayé : le contrat est maintenant figé par un test.

### Étape 6 faite : test de la phase 5 côté Python (`tests/test_phase5.py`)

Avec la vraie IA, le vrai serveur, le vrai fil de présentation et un faux Unity (client TCP), trois tests :

1. **Unity ne change jamais ce que fait l'IA, et ne la ralentit pas.** 60 générations (50 essais chacune), même graine, dans cinq conditions : l'IA nue (référence : ni directeur, ni crochet, ni réseau), l'affichage sans réseau, sans client,
   avec un client connecté qui **ne lit jamais**, avec un client qui lit. Les rapports de génération sont identiques dans les cinq, et chaque condition tient dans 1,5 fois le temps de l'IA nue plus 0,3 s.
2. **Un Unity en retard ne manque rien** : lancé après l'IA, il reçoit toutes les découvertes, chacune une fois, dans l'ordre, et les dernières stats.
3. **Unity peut partir et revenir pendant que l'IA continue** (IA dans un fil) : le Unity qui revient reçoit l'historique (NOT en premier) puis le direct, avec des générations plus avancées ; l'IA ne s'arrête pas.

**Débits mesurés sur cette machine** (meilleur de 4 répétitions, 60 générations) :

| Condition | Temps | Générations par seconde | Rapport à l'IA nue |
| --- | --- | --- | --- |
| IA nue (référence) | 0,762 s | 78,7 | 1,00 |
| Affichage sans réseau | 0,743 s | 80,7 | 0,98 |
| Serveur, aucun client | 0,729 s | 82,3 | 0,96 |
| Client connecté qui ne lit **jamais** | 0,772 s | 77,7 | 1,01 |
| Client qui lit | 0,776 s | 77,3 | 1,02 |

Les écarts (de -4 % à +2 %) sont du bruit de mesure : **l'affichage, même avec un Unity qui ne lit rien, ne coûte rien de mesurable à l'entraînement** (environ 4 000 essais par seconde). La marge du test (1,5 fois + 0,3 s) est large pour éviter
les faux échecs ; le test est stable (5 exécutions de suite, environ 11 s chacune). Le fait de comparer à l'IA nue (et non à l'affichage sans réseau) a été ajouté après réflexion : sinon un ralentissement présent dans toutes les conditions passait inaperçu.

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `53 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 24 source files` |
| `pytest` | `875 passed` en environ 80 s (872 avant, 3 nouveaux) |
| Erreurs volontaires pour ce test | une pause de 20 ms dans `update_stats` (appelé par l'entraînement) : détectée ; l'affichage qui glisse un NAND dans la bibliothèque (il change l'IA) : détectée |

Deux de mes erreurs volontaires étaient mal conçues et ont été refaites : réenregistrer un circuit déjà accepté ne change rien dans la bibliothèque, et glisser un NOT non plus (le NOT est déjà trouvé avant le premier essai montré). Une vraie interférence demandait un circuit que l'IA n'a
pas encore (un NAND à 2 entrées). Une 3e, « préparer un essai à chaque essai accepté », survit à ce test (le coût reste sous 50 %), mais elle est détectée par `test_display_work_is_done_only_when_the_director_asks` (étape 5).

### Vérification par Téo sur son Mac

Téo a lancé `cd python && PYTHONPATH=src .venv/bin/python -m logicai.live --generations 20` sur son Mac (10 octobre 2026) et obtenu, comme attendu :
`En écoute sur 127.0.0.1:8765 : lance Unity (Play). Ctrl-C pour arrêter.` / `Découverte (NEW) : NOT, 1 NAND` / `20 générations jouées.`
La commande fonctionne donc sur macOS (serveur local, IA, arrêt propre). Seul NOT apparaît en 20 générations : au palier 1 il n'y a que lui à trouver, et le palier 2 ne se débloque qu'après 400 générations sans nouveauté (N = 400).

### Bilan de la partie Python de la phase 5

Étapes 1 à 6 faites (protocole, ordre de pose, serveur non bloquant, essai montré + directeur, branchement + commande, test de la phase). 875 tests, 4 contrôles verts. **Reste le C#** (étapes 7 à 9), que je peux écrire ici mais pas compiler :
Téo le vérifie sur son Mac avec `tools/run_unity_tests.sh EditMode` puis `PlayMode`. La phase 5 ne sera jugée terminée qu'après la vérification visuelle dans Unity.

### Étape 7 faite : messages en C# (écrite ici, **vérifiée par Téo : 99 tests sur 99 verts**)

Fichiers (tous dans `Assets/`, aucun `.meta` créé ni modifié) :

- `Scripts/Runtime/LiveMessages.cs` : les classes `[Serializable]` des messages (`PlacementStep`, `DiscoveryData`, `StatsData` ; `StateData` et `CircuitFile` de la phase 3 sont réutilisées), les « enveloppes »
  dont `JsonUtility` a besoin pour lire une seule clé, et `LiveMessageParser.Parse(ligne)`, qui lit d'abord `message` (le type) puis la classe voulue. Toute ligne incorrecte lève `LiveMessageException`
  (Unity ne plante pas à cause d'une ligne). Pour une découverte, le parseur vérifie aussi que l'**ordre de pose redonne bien le circuit** du message (même nombre de nœuds et de câbles).
- `Scripts/Runtime/LivePlacement.cs` : `BuildCircuit(nom, étapes, n)` rejoue les `n` premières étapes de pose et renvoie le circuit partiel (c'est ce que l'interface de l'étape 9 redessinera à chaque étape).
  Incohérences refusées par `CircuitFormatException` : action inconnue, câble avant l'un de ses nœuds, broche mal écrite, nœud posé deux fois, `n` négatif.
- `Scripts/Runtime/CircuitLoader.cs` : `Validate` devient publique (une ligne modifiée, plus un commentaire) pour que les messages contenant un circuit soient vérifiés exactement comme un fichier de circuit.
- `Tests/EditMode/LiveSamples.cs` : **lignes de messages générées par le vrai code Python** (`protocol.py`, `replay.py`), pas écrites à la main (`'` à la place de `"` pour les écrire en C#). Le C# lit donc ce que Python écrit vraiment.
- `Tests/EditMode/LiveMessageTests.cs` (22 tests) et `LivePlacementTests.cs` (12 tests) : lecture des 4 types de messages, champs inconnus ignorés, 15 cas de messages refusés ; rejeu de l'ordre de pose (chaque préfixe grandit d'une pièce,
  l'ordre complet redonne le circuit du message) et 8 cas d'ordres incohérents refusés.

**Ce que j'ai pu vérifier ici (sans Unity)** : les chaînes que mes tests remplacent dans les échantillons existent bien (une seule fois) ; les morceaux de messages d'erreur attendus existent dans le code C# ; accolades et parenthèses
sont équilibrées ; la partie Python n'a pas changé de comportement (seule la docstring de `replay.py` est corrigée : l'axe `y` monte, les nœuds d'une colonne sont posés de bas en haut, l'ordre dans une colonne n'a pas d'effet sur le circuit obtenu).
**Ce que je ne pouvais pas vérifier ici** : que le C# compile et que les 34 tests passent. Téo l'a fait sur son Mac : voir « Preuve de Téo » ci-dessous.

Comportements de `JsonUtility` que je n'ai volontairement **pas** supposés : ce qu'il met dans un tableau ou un objet absent du JSON (nul ou vide : mes tests acceptent les deux, ils vérifient seulement que le message est refusé).
Un seul pari reste : un nombre écrit sans virgule (`3`) est lu comme un `float` (test `Parse_StatsWithAnIntegerReward_IsAccepted`) ; Python écrit `3.0`, donc ce test est une précaution. S'il échoue, c'est ce test qui est à revoir, pas le parseur.

| Contrôle (Python, inchangé hors docstring) | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `53 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 24 source files` |
| `pytest` | `875 passed` en environ 82 s |
| Tests C# (34 nouveaux) | `tools/run_unity_tests.sh EditMode` sur le Mac de Téo : `{'total': '99', 'passed': '99', 'failed': '0', 'skipped': '0'}` |

Les `.meta` des 5 nouveaux fichiers seront créés par l'Unity de Téo à la première ouverture ; il les commitera à part (comme en phase 3).

**Preuve de Téo (10 octobre 2026)** : une première exécution a donné `total: 65`, c'est-à-dire exactement le compte d'avant l'étape 7 (56 `[Test]` + 9 `[TestCase]`) : les 34 nouveaux tests n'avaient pas tourné, le dossier
de Téo ne contenait pas encore mes commits (le script copie `Assets/` depuis le dossier où il est lancé). Je n'ai donc rien conclu de ce résultat. Après avoir récupéré la branche : `total: 99` (65 + 34), 99 réussis, 0 échec, 0 ignoré.
Le C# compile donc, et mes paris sur `JsonUtility` (dont « `3` lu comme un `float` ») sont confirmés. Leçon à garder : toujours comparer le **total** au compte attendu, pas seulement « 0 échec ».

### Ce qui reste

- Étape 8 : `LiveConnection.cs` (connexion TCP en fil séparé, reconnexion automatique, file lue dans `Update`).
- Étape 9 : interface (bibliothèque des découvertes, statistiques, bascule direct / rediffusion, rediffusion locale).
- La phase 5 ne sera jugée terminée qu'après la vérification visuelle de Téo dans Unity.

---

## 10 octobre 2026 — Session 4 : phase 4 (IA évolutionnaire), terminée

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

### Étape 5 faite : paliers (`stages.py`, `tests/test_stages.py`, `errors.py`)

- `STAGES` : palier 1 = 1 entrée, palier 2 = 2, palier 3 = 3, une seule sortie chacun, sans boucle (décisions Q4 et Q5). Les paliers 4 et 5 sont pour la phase 6.
- `Curriculum(evolution, stalled_generations, stages)` mène une `Evolution` palier après palier : il applique les réglages du palier 1 au départ, joue `evolution.step()`, compte les
  générations d'affilée **sans nouveauté** et, à N générations calmes, passe au palier suivant (nouveaux réglages `evolution.rules`, compte remis à zéro). Le dernier palier est gardé.
- Un record n'est pas une nouveauté : il ne remet pas le compte à zéro (`GenerationReport.new_count`).
- `StageReport` donne le palier où la génération a été jouée, le rapport de génération, et `advanced_to` (le nouveau palier si la génération vient de le débloquer).
- Erreur dédiée : `InvalidStageSettingsError` (N < 1, liste de paliers vide).
- Le critère est pris à la lettre (décision de Téo) : le compte démarre dès l'entrée dans le palier, même avant la première nouveauté. Les paliers se contiennent
  (un palier plus grand permet « jusqu'à » n entrées), donc monter trop tôt élargit la recherche sans rien interdire.

**Valeur de départ de N : 400 (à valider par Téo).** Choisie par un essai chiffré (script jetable, 5 graines, 3000 générations au palier 2, calcul hors ligne du moment où chaque N aurait fait
quitter le palier). Les nouveautés arrivent par rafales séparées de longs silences (des centaines de générations), donc le critère est bruité :

| N | Génération de sortie du palier 2 | Portes à 2 entrées trouvées à la sortie (5 graines) |
| --- | --- | --- |
| 100 | 117 à 189 | 2 à 3 |
| 200 | 251 à 583 | 3 à 6 |
| **400** | 551 à 783 | 4 à 6 |
| 800 | 951 à 1861 | 4 à 8 |

Passer de 400 à 800 double le temps pour un gain visible sur 2 graines seulement. Sur 3000 générations, une seule graine sur 5 a trouvé les 8 portes ; XOR est resté à 5 NAND dans une exécution
(le minimum est 4). Conséquence : le test de la phase (étape 6) demandera de longues exécutions ou du réglage. Au palier 1, N = 400 fait attendre 400 générations (environ 4 s) après NOT,
alors qu'il n'y a plus rien à trouver : le cahier a un seul critère, je ne l'ai pas rendu propre à chaque palier.

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `39 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 18 source files` |
| `pytest` | `689 passed` (677 avant, 12 nouveaux) |
| Mutations (copie hors du projet) | 19 erreurs volontaires dans `stages.py`, 19 détectées |

Les tests de critère utilisent une évolution « scénarisée » (sous-classe de `Evolution` dont `step()` rend des rapports écrits d'avance) pour contrôler exactement quelles générations apportent
une nouveauté, un record ou rien ; deux tests tournent avec une vraie évolution (NOT puis montée aux paliers 2 et 3 avec N = 10, et reproductibilité).

### Étape 6 faite : test de la phase 4 (`tests/test_phase4.py`), poids des mutations, 100 circuits récents

**Décisions de Téo (10 octobre 2026)** :

- Critère « approche les tailles minimales » = **cahier à la lettre** : NOT en premier au palier 1 (1 NAND) ; au palier 2, les 8 découvertes à 2 entrées toutes trouvées ;
  AND = 2, OR = 3 et XOR = 4 NAND **exactement** ; les 5 autres (NAND, ORNOT, ANDNOT, NOR, XNOR) à **1 NAND de leur minimum au plus**.
- Poids des mutations : ajouter un câble ×4, ajouter une NAND ou un composant ×2, le reste ×1 (`DEFAULT_MUTATION_WEIGHTS`, paramètre `weights` de `mutate`, poids invalides refusés) ;
  `DEFAULT_RECENT_SIZE` de 20 à **100**.

**Tailles minimales exactes** (recherche exhaustive de tous les circuits de NAND à 2 entrées ; le test de la phase les recalcule lui-même, rien n'est recopié de mémoire) :
NOT 1, NAND 1, AND 2, ORNOT 2, OR 3, ANDNOT 3, NOR 4, XOR 4, XNOR 5. Elles confirment les chiffres du cahier.

**Pourquoi les poids** : avec l'ancien tirage (tout à égalité), le blocage était la *découverte* de NOR, XOR et XNOR (les portes trouvées l'étaient presque toujours à leur taille minimale).
Essais (8 graines par ligne, 3000 générations au palier 2 après NOT, scripts jetables) :

| Réglage | Les 8 portes trouvées | Les 8 à leur taille minimale |
| --- | --- | --- |
| Ancien (tout à égalité, 20 récents) | 2 sur 8 | 1 sur 8 |
| 100 récents seulement | 4 sur 8 | 3 sur 8 |
| **Favoriser les ajouts + 100 récents (retenu)** | **7 sur 8** | **5 sur 8** |
| Favoriser les ajouts, 20 récents | 7 sur 8 | 3 sur 8 |
| 300 récents, tout à égalité | 3 sur 8 | 0 sur 8 |

**Fiabilité réelle de l'IA (à ne pas surestimer)** : avec les réglages finaux et le critère ci-dessus (flux du test : palier 1 jusqu'à NOT, puis palier 2) :

- **4 graines sur 16 réussissent en 2500 générations** (graines 1, 10, 11, 12, aux générations 285, 1435, 755, 210) ;
- **6 graines sur 12 réussissent en 4000 générations** (3 sur 12 à 2500 : plus de temps aide) ;
- dans presque tous les échecs, les 8 portes sont trouvées mais **le XOR reste à 5 ou 6 NAND** au lieu de 4 : l'étape qui bloque est la *réduction* d'un circuit déjà trouvé.

Le test de la phase utilise les graines 1, 12 et 11 (fixes, reproductibles) plus un parcours complet avec `Curriculum` (N = 400, graine 1). Il prouve que l'IA **peut** y arriver, de façon reproductible,
pas qu'elle y arrive à coup sûr. Contrôle négatif fait : avec la graine 0, le critère n'est pas atteint (XOR à 6), donc le test échouerait pour cette graine.
Mon premier essai (5 graines sur 8 à « tout au minimum » en 3000 générations) était plus optimiste ; les échantillons sont petits et les déroulements diffèrent, je ne les additionne pas.

**Essai sur le nombre de mutations par enfant** (12 graines, 4000 générations, critère ci-dessus) : actuel (1 à 12, uniforme) 6 sur 12 ; petits nombres favorisés (plus petit de 2 tirages) 7 sur 12 ;
1 à 6 mutations 3 sur 12. Écart dans le bruit, **aucun changement retenu**.

**Test modifié, avec l'accord de Téo** : `test_records_are_discoveries_but_not_novelties` : seul le numéro de graine change (4 -> 3), l'assertion est identique. Avec les poids, la graine 4 ne produit plus de
record dans les 20 premières générations du palier 2 ; les graines 3 et 6 en produisent.

**Mutations (copie hors du projet)** : `mutations.py` 29 erreurs volontaires (dont 7 sur les poids), 28 détectées, 1 équivalente (celle de l'étape 2) ; `evolution.py` 25 erreurs, 24 détectées au départ.
La survivante (« le nombre de mutations vaut toujours le maximum ») était détectée avant le changement d'algorithme : un trou de **mes tests**, révélé par ce changement. Test ajouté
(`test_mutation_count_covers_min_to_max_inclusive`, qui compte les mutations réellement appliquées) : les 4 erreurs sur ce tirage sont maintenant détectées.

| Contrôle | Résultat |
| --- | --- |
| `ruff check` | `All checks passed!` |
| `ruff format --check` | `40 files already formatted` |
| `mypy` (strict, `src/`) | `Success: no issues found in 18 source files` |
| `pytest` | `701 passed` en environ 58 s (689 avant, 12 nouveaux dont 5 pour le test de la phase) |

Incident : une commande de ma part a été bloquée par une vérification de sécurité (un `rm -rf` sur un chemin construit avec des variables shell). Rien n'a été supprimé ni exécuté ; relancée avec la
forme sûre `"${VAR:?}"`.

### Environnement de cette session

Machine Linux, Python 3.13.16 (vérifié), `python/.venv` recréé avec `requirements-dev.txt` (versions identiques : pytest 9.1.1, ruff 0.17.0, mypy 2.4.0).
L'état de départ était le même que dans le journal (439 tests). Python 3.11 : toujours pas vérifié par exécution.

### Bilan de la phase 4 et ce qui reste

**Phase 4 terminée sur le plan du code et des tests** (étapes 1 à 6 faites, 701 tests, 4 contrôles verts). Réserve à retenir : la fiabilité de l'IA sur le critère strict est d'environ 25 à 50 % selon le budget
(voir ci-dessus) ; le XOR à 4 NAND est le point dur. Pistes si besoin plus tard : mieux réduire les circuits déjà trouvés, budget de générations plus grand.

Phase 5 (liaison en direct, socket Python vers Unity) : **non commencée**, à lancer sur demande de Téo.

**À valider par Téo** :

- les valeurs de départ choisies par moi : poids de la récompense (100 / 30 / 5 / 1), 50 enfants, 1 à 12 mutations, 100 récents, N = 400 ;
- mes interprétations : « retirer un nœud » ne retire que NAND et composants ; le bonus de réutilisation ne vaut que pour une nouveauté, par composant distinct, composants du circuit gardé ;
- le fait que le test de la phase 4 s'appuie sur des graines qui réussissent (et que la suite dure maintenant environ 1 minute) ;
- sa vérification visuelle dans Unity (phase 3).

**Toujours ouverts** : interprétation de la CLK (phase 6, Téo a noté dans le cahier « CLK = horloge donc un petit composant qui peut faire une horloge »).
**À faire côté cahier** : reporter dans le document en ligne les modifications 1 à 9 (voir `docs/modifications_cahier_proposees.md`), sinon une ré-exportation les efface. La copie locale n'a pas reçu les
points 7 à 9 (taille maximale d'un circuit, valeur de N, palier 3 = 68 découvertes) : proposés seulement.

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
