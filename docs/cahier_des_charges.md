# logicAI — Cahier des charges

> Copie locale du cahier des charges (document claude.ai), exportée le 10 octobre 2026.
> C'est la référence pour Claude Code. Si le document en ligne change, il faut ré-exporter ce fichier.
> Les deux schémas du document ont été convertis en texte (blocs « Schéma »).

Oct 10, 2026 · Téo Vidal

## Présentation

logicAI est une simulation où une IA part de la seule porte NAND et découvre seule des circuits logiques. Elle les range en composants, puis les réutilise pour construire des circuits plus complexes.

Personne ne lui fournit de table de vérité. L'IA est récompensée quand elle obtient un comportement **nouveau**, avec le moins de portes possible et qui sert ensuite à autre chose.

L'IA et la simulation tournent en **Python**. **Unity** affiche les circuits en train d'être construits. Le projet en est au cadrage : aucun code n'est encore écrit, et le projet Unity (Unity 6.3, modèle 2D URP) est vide.

## Décisions validées

Ces choix ont été validés pendant la discussion de cadrage du 10 octobre 2026.

| Sujet | Décision |
| --- | --- |
| Brique de base | NAND uniquement ; tout le reste est découvert par l'IA |
| Constructeur | L'IA seule ; elle réutilise ses propres composants |
| Objectifs | Aucune table de vérité fournie ; l'IA est récompensée pour la nouveauté |
| Câblage | Une entrée reçoit un seul câble au maximum ; une sortie alimente autant d'entrées que voulu |
| Entrée non connectée | Vaut 0, comme une entrée reliée à la masse |
| Boucles | Autorisées, pour pouvoir faire du séquentiel |
| Oscillateurs | Rejetés ; une entrée CLK fournie par la simulation les remplace |
| Méthode d'IA | D'abord un algorithme évolutionnaire, ensuite un réseau de neurones |
| Répartition | Python : simulation et IA. Unity : affichage seulement |
| Affichage | Un essai en direct au ralenti, plus la rediffusion de chaque découverte |
| Fan-out | Illimité |
| Niveau de départ | C# : tu lis le code mais tu n'en écris pas encore. Unity : tu découvres. Python : bases légères |

## Règles du monde logique

Toutes les règles de câblage tiennent en une seule idée : un câble va toujours d'une **source** vers un **puits**, et un puits n'accepte qu'un seul câble.

### Les éléments

| Élément | Broches | Rôle |
| --- | --- | --- |
| NAND | 2 puits (entrées), 1 source (sortie) | La seule porte de base |
| Composant | n puits, m sources | Circuit découvert puis encapsulé (voir « Composants et bibliothèque ») |
| Entrée du circuit | 1 source | Signal imposé par le testeur |
| Sortie du circuit | 1 puits | Signal lu par le testeur |
| CLK | 1 source | Horloge fournie par la simulation, que l'IA peut câbler |

### Les règles de câblage

1. Un câble relie toujours une source à un puits. Sortie vers sortie et entrée vers entrée sont donc impossibles.
2. Un puits reçoit 0 ou 1 câble.
3. Une source alimente un nombre illimité de puits. C'est indispensable : NOT(A) = NAND(A, A).
4. Un puits sans câble vaut 0. Une NAND sans aucun câble fournit donc un 1 constant, car NAND(0, 0) = 1.
5. Les boucles sont autorisées, y compris une sortie qui revient sur sa propre porte.

Ces règles sont vérifiées **avant** chaque action de l'IA. Une action interdite n'est jamais exécutée : l'IA ne peut donc pas produire un circuit illégal.

### La simulation par tops

Le temps avance par **tops**. À chaque top, toutes les NAND calculent leur nouvelle sortie à partir des valeurs du top précédent. Chaque NAND a donc un retard de 1 top, comme un temps de propagation réel.

Au départ, toutes les sorties valent 0. Ce point de départ fixe rend chaque test reproductible.

Un circuit est **stable** quand plus aucune sortie ne change d'un top à l'autre. La simulation attend au maximum T_max tops, avec T_max = nombre de NAND du circuit après aplatissement. Un circuit sans boucle se stabilise toujours dans ce délai, car aucun chemin ne compte plus de NAND que le circuit entier.

### L'entrée CLK

Sur ta réponse « on rajoute une entrée CLK », j'ai retenu ceci : un circuit qui oscille tout seul est rejeté, et la simulation fournit à la place un signal d'horloge carré. Corrige-moi si tu voulais dire autre chose.

- La CLK est disponible à partir de la phase séquentielle.
- Sa demi-période est toujours plus longue que T_max. Le circuit a donc le temps de se stabiliser entre deux fronts.
- Les sorties sont lues juste avant chaque front montant.

## Comportement et signature

La **signature** d'un circuit, c'est ce qu'il fait, mesuré par le testeur. Deux circuits qui ont la même signature ont le même comportement, même s'ils sont câblés différemment.

### Circuits combinatoires

La signature est la **table de vérité** complète : on teste les 2^n combinaisons des n entrées et on note les sorties une fois le circuit stable.

Pour aller vite, on utilise la **simulation bit-parallèle**. Chaque fil est un nombre entier dont le bit k vaut le signal pour la combinaison k. Une seule opération calcule alors une NAND pour toutes les combinaisons à la fois :

```
A      = 0b1010   (A pour les combinaisons 3,2,1,0)
B      = 0b1100
NAND   = ~(A & B) & 0b1111  =  0b0111
```

### Circuits séquentiels

Avec une boucle, la sortie peut dépendre du **passé**. La table de vérité ne suffit plus. Le testeur envoie donc une **batterie fixe de séquences d'entrées**, la même pour tous les circuits. La signature est la suite des sorties lues pendant ces séquences.

Chaque test part du même état : toutes les sorties à 0.

### Les trois cas détectés

| Cas | Définition | Traitement |
| --- | --- | --- |
| Stable | Les sorties ne changent plus avant T_max tops | Signature enregistrée normalement |
| Instable (oscillation) | Entrées figées, mais les sorties changent encore après T_max tops | Circuit rejeté |
| Mémoire | Pour une même entrée actuelle, la sortie diffère selon les entrées passées | Bonus « mémoire » (voir « Système de récompense ») |

### Piège à connaître

Avec un retard de 1 top par NAND, une bascule SR en NAND peut osciller quand ses deux entrées passent à 1 en même temps. C'est l'équivalent simulé de la **métastabilité**. Le testeur la classera « instable » pour cette séquence-là. C'est un comportement réel, pas un bug du simulateur.

## Système de récompense

L'IA gagne des points quand elle obtient une signature absente de la bibliothèque, ou quand elle reproduit une signature connue avec moins de NAND. Elle ne vise donc pas une table imposée : son objectif est de trouver du nouveau, simplement, et qui serve.

Schéma (converti en texte) — chemin d'un essai, 3 tests, 4 issues :

```
L'IA propose un circuit
  -> Le simulateur mesure sa signature
  -> Filtres OK ?
       non -> Rejeté, 0 point (circuit inutile ou instable)
       oui -> Signature connue ?
                non -> Nouveauté, grosse récompense (le circuit devient un composant)
                oui -> Moins de NAND ?
                         oui -> Record battu, récompense moyenne (il remplace l'ancien composant)
                         non -> Aucune récompense
Dans tous les cas -> essai suivant
```

Chaque essai suit ce chemin. Quel que soit le résultat, l'IA passe ensuite à l'essai suivant.

### La formule

```latex
R = R_{nouveauté} + R_{record} + R_{mémoire} + R_{réutilisation} - k \cdot N_{NAND} - P_{filtres}
```

| Terme | Quand il s'applique | Ordre de grandeur |
| --- | --- | --- |
| Nouveauté | Signature jamais vue | Grand |
| Record | Signature connue, mais avec moins de NAND : le nouveau circuit remplace l'ancien | Moyen |
| Mémoire | Le circuit a un comportement séquentiel (voir « Les trois cas détectés ») | Grand |
| Réutilisation | Un composant existant est utilisé dans une nouvelle découverte : le composant gagne de la valeur | Petit, cumulatif |
| Taille | Chaque NAND coûte k points | Petit |
| Filtres | Circuit inutile (liste ci-dessous) | Annule la récompense |

Les valeurs exactes seront réglées par essais, en regardant ce que l'IA produit.

### Les filtres anti-triche

Sans filtres, l'IA trouve vite des moyens de gagner des points sans rien construire d'utile. Un circuit est donc refusé si :

- une de ses entrées n'influence aucune sortie ;
- une de ses sorties est constante ;
- deux de ses sorties sont identiques ;
- une sortie recopie simplement une entrée (un fil suffirait) ;
- il est instable (voir « Les trois cas détectés »).

### Les paliers

La progression NAND → portes classiques → circuits complexes vient du nombre d'entrées autorisé. L'IA débloque un palier quand elle ne trouve plus rien de nouveau dans le précédent.

| Palier | Entrées max | Fonctions possibles (1 sortie) | Restent après les filtres | Ce que l'IA doit trouver |
| --- | --- | --- | --- | --- |
| 1 | 1 | 4 | 1 | NOT (1 NAND) |
| 2 | 2 | 16 | 10 | AND (2), OR (3), NOR (4), XOR (4), XNOR, A AND NOT B… |
| 3 | 3 | 256 | 218 | Majorité, multiplexeur 2 vers 1… |
| 4 | 4 et plusieurs sorties | 65 536 par sortie | Trop pour tout explorer | Additionneurs, comparateurs… |
| 5 | Avec CLK | — | — | Bascules, registres, compteurs |

Les nombres entre parenthèses sont les tailles minimales connues en NAND. Ils servent de repère pour juger si l'IA trouve des solutions optimales.

Le nom de chaque porte (AND, XOR…) est ajouté automatiquement par comparaison avec une liste connue, pour l'affichage uniquement. L'IA ne connaît pas ces noms.

### La variante « défis », pour plus tard

Un module choisit une table de vérité absente de la bibliothèque, et l'IA essaie de la construire. Ce n'est pas toi qui donnes la table : c'est le système qui se fixe lui-même un défi. Cette variante sera utile au palier 4, où il y a trop de fonctions possibles pour les découvrir par hasard.

## Composants et bibliothèque

Chaque découverte récompensée devient automatiquement un **composant** : une boîte noire que l'IA peut poser comme une porte. Ses entrées et sorties de circuit deviennent les broches de la boîte.

### Les étapes de l'encapsulation

1. **Nettoyage** : on retire les NAND et les câbles qui n'influencent aucune sortie.
2. **Ordre des broches** : les entrées et les sorties sont numérotées dans leur ordre de création.
3. **Coût** : on compte les NAND après aplatissement, c'est-à-dire en ouvrant tous les sous-composants. Un XOR fait de 4 NAND coûte 4, même s'il est posé comme un seul bloc.
4. **Nom** : si la signature correspond à une porte connue, elle prend son nom (AND, XOR…). Sinon, elle reçoit un numéro, par exemple C-017.
5. **Enregistrement** dans la bibliothèque, sous forme de fichier JSON.

### Simulation d'un composant

Pour simuler, on remplace chaque composant par ses NAND : on dit qu'on **aplatit** le circuit. Les retards restent ainsi exacts, ce qui compte pour le séquentiel.

Les composants sont rangés par référence. Si l'IA bat un record (même signature avec moins de NAND), on remplace la définition du composant. Tous les circuits qui l'utilisent profitent alors de la version plus petite.

### Composants équivalents

« A AND NOT B » et « NOT A AND B » sont le même composant, avec ses deux entrées inversées. Il faut décider si on les compte comme une seule découverte. Ce point reste ouvert (voir « Risques, limites et points encore ouverts »).

## Les deux IA

On construit d'abord une IA évolutionnaire, qui marchera à coup sûr, puis un réseau de neurones, plus ambitieux. Les deux utilisent exactement la même récompense et le même simulateur. On pourra donc les comparer.

|  | IA 1 : évolution | IA 2 : réseau de neurones |
| --- | --- | --- |
| Ce qui s'améliore | Les circuits | Le constructeur lui-même |
| Principe | Une population de circuits ; on garde les meilleurs, on les modifie au hasard, on recommence | Un agent choisit une action à la fois (poser, câbler, retirer) et apprend quelles actions rapportent |
| Outils Python | Python pur + NumPy | PyTorch, Gymnasium, Stable-Baselines3 |
| Difficulté | Moyenne | Élevée, résultat non garanti |
| Construction visible | Rediffusion reconstituée de chaque découverte | Vraie construction pas à pas, en direct |

### IA 1 : l'algorithme évolutionnaire

Un circuit est décrit par sa liste de nœuds et de câbles : c'est son « génome ». Les **mutations** possibles sont :

- ajouter une NAND ou un composant de la bibliothèque ;
- ajouter un câble valide, ou en retirer un ;
- retirer un nœud ;
- ajouter une entrée ou une sortie de circuit.

Pistes connues à étudier : **Novelty Search** (recherche de nouveauté) et **MAP-Elites**, qui garde le meilleur circuit pour chaque comportement.

L'évolution ne construit pas pas à pas : elle modifie des circuits existants. Pour la rediffusion, on reconstitue un ordre de pose : les nœuds dans l'ordre des signaux, puis les câbles.

### IA 2 : le réseau de neurones

L'environnement suit le format **Gymnasium**, le standard Python pour l'apprentissage par renforcement. L'algorithme envisagé est **PPO avec masquage d'actions** (MaskablePPO, dans sb3-contrib). Le masquage empêche l'agent de choisir une action interdite par les règles de câblage.

La vraie difficulté : un circuit a une taille variable, alors qu'un réseau de neurones simple attend une entrée de taille fixe. Pour commencer, on donne à l'agent une grille d'emplacements de taille fixe. Plus tard, on pourra passer à un réseau de neurones pour graphes.

## Architecture Python / Unity

Python fait tout le travail : simulation, IA, bibliothèque. Unity ne fait que dessiner. L'IA doit tester des millions de circuits, ce qui est impossible à la vitesse d'une animation. L'entraînement tourne donc à pleine vitesse, et seul un essai à la fois est envoyé à Unity, au ralenti.

Schéma (converti en texte) — architecture, Python à gauche, Unity à droite :

```
PYTHON : simulation et IA                          UNITY : affichage seulement
  IA (évolution, puis réseau de neurones)  --- messages JSON, socket TCP --->  Connexion (reçoit les messages)
    | circuit à tester (IA -> Simulateur)                                         | actions, états (Connexion -> Dessin)
    | signature (Simulateur -> IA)                                                v
  Simulateur logique (règles de câblage, tops, signatures)                     Dessin (portes, câbles colorés 0/1)
    | nouvelle découverte (Simulateur -> Bibliothèque)                         Interface (direct, rediffusions, stats)
    v                                                                            ^ stats (Connexion -> Interface)
  Bibliothèque (composants découverts, en JSON)
    réutilisation (Bibliothèque -> IA)
```

Seuls les essais choisis pour l'affichage passent par le socket. L'entraînement n'attend jamais Unity.

### La liaison

Python et Unity tournent sur le même ordinateur et communiquent par un **socket TCP local** (adresse 127.0.0.1). Chaque message est une ligne de texte JSON.

| Message (Python → Unity) | Contenu | Usage |
| --- | --- | --- |
| circuit | Le circuit complet | Afficher d'un coup |
| action | Une seule action : poser, câbler, retirer | Construction en direct |
| etat | Les valeurs 0/1 de chaque fil à un top donné | Colorer les câbles |
| decouverte | Nouveau composant + son ordre de pose | Rediffusion, mise à jour de la bibliothèque |
| stats | Palier, nombre de découvertes, récompense moyenne | Panneau d'information |

### Exemple de circuit en JSON

Un NOT fait d'une seule NAND, dont les deux entrées sont alimentées par A :

```json
{
  "nom": "NOT",
  "noeuds": [
    {"id": 0, "type": "ENTREE", "x": 0, "y": 0},
    {"id": 1, "type": "NAND",   "x": 2, "y": 0},
    {"id": 2, "type": "SORTIE", "x": 4, "y": 0}
  ],
  "cables": [
    {"de": [0, 0], "vers": [1, 0]},
    {"de": [0, 0], "vers": [1, 1]},
    {"de": [1, 0], "vers": [2, 0]}
  ]
}
```

`[1, 0]` se lit « nœud 1, broche 0 ». Pour « de », c'est une broche source ; pour « vers », une broche puits.

### Côté Unity (C#)

Trois scripts suffisent au départ :

1. **Connexion** : reçoit les messages dans un fil d'exécution séparé et les met dans une file d'attente. Unity n'autorise la modification de la scène que depuis son fil principal.
2. **Dessin** : crée les sprites des portes et les lignes des câbles, et colore chaque câble selon sa valeur (0 ou 1).
3. **Interface** : affiche la bibliothèque, les statistiques, et propose de basculer entre le direct et les rediffusions.

## Matériel

Recommandation : tout faire sur le **PC Windows équipé de la RTX 4060**, là où se trouve déjà le projet Unity. Python et Unity communiquent alors en local, sans réseau entre deux machines.

| Critère | PC + RTX 4060 | Mac M5, 24 Go |
| --- | --- | --- |
| Projet Unity | Déjà dessus | À copier |
| Phases 1 à 6 (simulation, évolution) | Travail du processeur ; la carte graphique ne sert pas | Idem |
| Phase 7 (réseau de neurones) | CUDA, le support PyTorch le plus répandu | Backend MPS de PyTorch, qui fonctionne aussi |
| Liaison avec Unity | Locale | Locale si Unity tourne aussi sur le Mac |

Pour ce projet, la carte graphique comptera peu. Les réseaux de neurones seront petits, et c'est surtout la vitesse du simulateur qui limitera l'apprentissage. Le Mac reste une solution de secours valable.

## Plan de développement

Le projet avance en 7 phases. Chacune se termine par un test précis : on ne passe à la suivante que si le test réussit. Le simulateur vient en premier, car tout le reste repose sur lui.

1. **Simulateur logique (Python)** : NAND, broches, câbles, règles de câblage, simulation par tops, détection stable / instable / mémoire.
   - Test : des circuits écrits à la main (NOT, AND, OR, XOR, bascule SR) donnent leur table attendue. Une NAND rebouclée sur elle-même est détectée instable. Un câble illégal est refusé.
2. **Bibliothèque et encapsulation** : nettoyage, coût, nommage automatique, aplatissement, sauvegarde en JSON.
   - Test : un XOR construit avec des composants NOT et AND donne la même signature que sa version aplatie.
3. **Affichage Unity statique** : Unity lit un fichier JSON et dessine le circuit.
   - Test : les circuits de la phase 1 s'affichent correctement, câbles colorés selon leur valeur.
4. **IA évolutionnaire, paliers 1 à 3** : mutations, récompense, filtres, changement de palier.
   - Test : l'IA découvre seule NOT, puis les 10 fonctions à 2 entrées, et approche les tailles minimales (AND = 2, OR = 3, XOR = 4 NAND).
5. **Liaison en direct** : socket Python → Unity, essai en direct au ralenti, rediffusion des découvertes.
   - Test : on regarde l'IA construire pendant que l'entraînement continue à pleine vitesse.
6. **Paliers 4 et 5** : plusieurs sorties, variante « défis », entrée CLK, bonus mémoire.
   - Test : l'IA trouve un demi-additionneur, puis un circuit qui mémorise (bascule).
7. **Réseau de neurones** : environnement Gymnasium, MaskablePPO.
   - Test : l'agent redécouvre les portes du palier 2 plus vite qu'un constructeur qui joue au hasard.

## Risques, limites et points encore ouverts

Le principal risque concerne le palier 4 et le réseau de neurones : rien ne garantit qu'ils aboutissent. Les phases 1 à 5 forment déjà, à elles seules, un projet complet qui fonctionne.

### Risques

| Risque | Conséquence | Parade |
| --- | --- | --- |
| Explosion combinatoire dès 4 entrées | Trop de fonctions pour tout découvrir | Variante « défis », bonus de réutilisation |
| Récompense mal réglée | L'IA « triche » : circuits énormes ou inutiles | Filtres, pénalité de taille, observation des résultats |
| Python trop lent | Apprentissage très long | Simulation bit-parallèle, NumPy ; accélérer plus tard si besoin |
| Le réseau de neurones n'apprend pas | Phase 7 sans résultat | L'IA évolutionnaire reste fonctionnelle |
| « Choisir ce qui est intéressant » est un sujet de recherche ouvert | Les découvertes peuvent manquer d'intérêt | La formule de récompense en est une approximation mesurable |

### Points à trancher

- [ ] Composants équivalents par inversion des entrées (A AND NOT B et NOT A AND B) : une seule découverte ou deux ? Ma recommandation : une seule.
- [ ] Taille maximale d'un circuit : j'ai compris « illimité » pour le fan-out. Pour la taille, je propose aucune limite fixe, seulement la pénalité de taille. À confirmer.
- [ ] Interprétation de la CLK (section « L'entrée CLK ») : à confirmer. ( CLK = horloge donc un petit composant qui peux faire une horloge))
- [ ] Réglage des poids de la formule de récompense : par essais, à partir de la phase 4.
- [ ] Critère de changement de palier : par exemple, aucune nouveauté pendant N générations. N reste à fixer.
- [ ] Nombre maximal d'entrées et de sorties par composant.

## Glossaire

| Terme | Sens dans ce projet |
| --- | --- |
| Aplatir | Remplacer chaque composant par les NAND qui le composent |
| Apprentissage par renforcement | Un agent essaie des actions, reçoit des récompenses et apprend lesquelles rapportent |
| Bit-parallèle | Simuler toutes les combinaisons d'entrées en même temps, une par bit d'un entier |
| Combinatoire | Circuit dont la sortie dépend uniquement des entrées actuelles |
| Encapsuler | Transformer un circuit en boîte noire réutilisable |
| Fan-out | Nombre d'entrées alimentées par une même sortie |
| Masquage d'actions | Interdire à l'agent de choisir une action illégale |
| Métastabilité | Une bascule qui hésite entre 0 et 1 ; dans la simulation, elle oscille |
| PPO | Algorithme d'apprentissage par renforcement très répandu |
| Puits | Broche qui reçoit un signal : entrée de porte ou sortie de circuit |
| Séquentiel | Circuit dont la sortie dépend aussi des entrées passées (mémoire) |
| Signature | Le comportement mesuré d'un circuit : table de vérité, ou suite de sorties |
| Socket | Canal de communication entre deux programmes, ici Python et Unity |
| Source | Broche qui fournit un signal : sortie de porte, entrée de circuit ou CLK |
| Top | Un pas de temps de la simulation ; chaque NAND met 1 top à réagir |
