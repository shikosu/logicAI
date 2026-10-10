# Modifications proposées pour le cahier des charges

> **État : les points 1 à 6 ci-dessous ont été appliqués à la copie locale `docs/cahier_des_charges.md` le 10 octobre 2026, à la demande de Téo.**
> Les points 7 à 9 sont **nouveaux et pas encore appliqués** (à confirmer par Téo).
> Il reste à reporter tout cela dans le **document en ligne** (claude.ai), sinon une ré-exportation l'effacerait.

Le cahier (`docs/cahier_des_charges.md` et ton document en ligne) est en **lecture seule pour Claude** : je ne le modifie pas. Ce fichier
liste, section par section, ce qui a changé pendant les phases 1 à 3 depuis que le cahier a été écrit. Il n'y a rien à calculer : c'est une
liste de phrases à recopier dans ton document, ou à me demander de modifier (dans ce cas dis-le-moi clairement).

Chaque point dit où il se trouve dans le cahier, ce qui y est écrit aujourd'hui, et ce qu'il faudrait écrire.

## 1. Section « La simulation par tops » (et le tableau « Les trois cas détectés »)

**Aujourd'hui :** « La simulation attend au maximum T_max tops… »

**Proposé :** « La simulation calcule au plus **T_max + 1** tops : jusqu'à T_max tops pour atteindre l'état final d'un circuit sans boucle, plus un top
qui confirme que plus rien ne change. »
Dans le tableau : *Stable* = « les sorties ne changent plus avant T_max + 1 tops » ; *Instable* = « les sorties changent encore au top T_max + 1 ».

Pourquoi : avec T_max tops seulement, un NOT (1 NAND) ne pourrait jamais être confirmé stable.

## 2. Section « Composants équivalents »

**Aujourd'hui :** « … le même composant, avec ses deux entrées inversées. Il faut décider si on les compte comme une seule découverte. Ce point reste ouvert. »

**Proposé :** « … le même composant, avec ses deux entrées **échangées**. **Décision : une seule découverte.** Deux circuits dont les entrées sont seulement
échangées (permutées) ont la même signature. Les sorties ne sont jamais permutées : leur ordre fait partie du composant. Nier une entrée ne fusionne
pas : AND et NOR restent deux découvertes. »

## 3. Section « Points à trancher »

- Cocher « Composants équivalents par inversion des entrées » : **une seule découverte**.
- Cocher « Nombre maximal d'entrées et de sorties par composant » : **15 et 15 par défaut, réglable jusqu'à aucune limite**.
- « Taille maximale d'un circuit » reste ouvert (aucune limite fixe, seulement la pénalité de taille).

## 4. Section « Les paliers » et le test de la phase 4

**Aujourd'hui :** palier 2 : « 10 » fonctions restent après les filtres ; phase 4 : « l'IA découvre seule NOT, puis les 10 fonctions à 2 entrées ».

**Proposé :** « 10 fonctions, soit **8 découvertes** (A ET NON B = NON A ET B, et A OU NON B = NON A OU B) » ; phase 4 : « … puis les **8 découvertes** à 2 entrées ».

## 5. Section « Composants et bibliothèque », étape « Nom »

**À ajouter :** les noms connus sont NOT, AND, OR, NAND, NOR, XOR, XNOR, ANDNOT (A ET NON B), ORNOT (A OU NON B), MAJ (majorité) et MUX (multiplexeur 2 vers 1).
Un composant sans nom connu s'appelle C-001, C-002… La liste est une donnée facile à étendre.

## 6. Section « Exemple de circuit en JSON »

**À préciser :**
- `x` et `y` sont **calculés par Python** (colonnes : `x = 2 × couche` ; `y` entiers, première entrée en haut). Unity ne calcule rien.
- Un composant posé dans un circuit s'écrit `{"id": 3, "type": "COMPOSANT", "x": 2, "y": 0, "ref": "XOR", "entrees": 2, "sorties": 1}`.
- Une clé facultative `etat` donne les valeurs 0/1 à un top, pour colorer les câbles :
  `"etat": {"top": 3, "stable": true, "noeuds": [0, 1, 1], "cables": [0, 0, 1]}`. Les listes suivent l'ordre de `noeuds` et de `cables` du fichier.
  C'est aussi la forme du message `etat` de la section « La liaison ».

## 7. Section « Points à trancher » : taille maximale d'un circuit (nouveau, pas appliqué)

Décision de Téo (10 octobre 2026, avant la phase 4) : **aucune limite fixe, seulement la pénalité de taille k · N_NAND.**
Proposé : cocher « Taille maximale d'un circuit » et écrire « décision validée : aucune limite fixe, seulement la pénalité de taille ».

## 8. Section « Points à trancher » : critère de changement de palier (nouveau, pas appliqué)

Décision de Téo (10 octobre 2026) : **N est un paramètre réglable, dont la valeur de départ est trouvée par essais pendant la phase 4**, puis validée par Téo.
Proposé : garder la case non cochée (la valeur de N n'est pas fixée) et ajouter « N : paramètre réglable, valeur trouvée par essais en phase 4 ».

## 9. Section « Les paliers » : palier 3 (nouveau, pas appliqué)

**Aujourd'hui :** palier 3 : « 218 » fonctions restent après les filtres.

**Proposé :** « 218 fonctions, soit **68 découvertes** » (même raison qu'au palier 2 : les entrées échangées donnent la même signature).
Calcul fait par un petit script indépendant du projet : 1 entrée → 1, 2 entrées → 10 fonctions et 8 découvertes, 3 entrées → 218 fonctions et 68 découvertes
(4 entrées : 64 594 fonctions et 3 904 découvertes). Cohérent avec les nombres de signatures du journal (session 2) : 80 − 12 = 68 et 3 984 − 80 = 3 904.

## 10. Section « La liaison » : forme des messages (phase 5, nouveau, pas appliqué)

Le cahier dit « chaque message est une ligne de texte JSON » et liste cinq types, sans en donner la forme. Proposé d'ajouter :

- Chaque message est un objet JSON sur une ligne (UTF-8), avec une clé `"message"` qui donne le type : `circuit`, `etat`, `decouverte`, `stats` (le type `action` viendra avec l'IA 2, phase 7).
- `circuit` : `{"message":"circuit","circuit":<format d'un fichier de circuit>}`. `etat` : `{"message":"etat","etat":{"top","stable","noeuds","cables"}}` (même forme que la clé `etat` d'un fichier).
- `decouverte` : `{"message":"decouverte","nom","genre":"nouveaute"|"record","cout","circuit","ordre_de_pose":[...]}` ; `stats` : `{"message":"stats","palier","generation","decouvertes","recompense_moyenne"}`.
- Python écoute sur 127.0.0.1 et Unity se connecte (décision de Téo, 10 octobre 2026).

## 11. Section « L'entrée CLK » et « Points à trancher » : interprétation de la CLK (phase 6, nouveau, pas appliqué)

Décision de Téo (10 octobre 2026) : la CLK est un **nœud que l'IA pose et câble comme une NAND** (une source à 1 broche, sans puits). Tous les nœuds CLK d'un circuit, y compris
ceux qui sont dans des composants, partagent la même horloge, fournie par la simulation. Ce n'est pas une broche du composant (ni entrée, ni sortie).
Proposé : cocher « Interprétation de la CLK » et y écrire cette décision. Le protocole de l'horloge est le point 13.

## 12. Section « Circuits séquentiels » : la batterie de séquences (phase 6, nouveau, pas appliqué)

Le cahier dit « une batterie fixe de séquences d'entrées » sans dire lesquelles. Décision de Téo (10 octobre 2026) : **un seul changement d'entrée à la fois**. Une séquence part
de toutes les entrées à 0 et change une seule entrée par pas, pendant 4 pas ; la batterie contient toutes les séquences possibles. La signature est la suite des sorties lues à chaque pas.
Pourquoi : si deux entrées passent à 1 en même temps, une bascule SR en NAND oscille (cahier, « Piège à connaître ») ; une batterie qui ferait ces changements simultanés rejetterait toute bascule.
Le cahier reste valable : toute oscillation dans la batterie rejette le circuit. Les filtres anti-triche s'appliquent à chaque pas de chaque séquence.

## 13. Section « L'entrée CLK » : protocole dans la batterie (phase 6, nouveau, pas appliqué)

Décision de Téo (10 octobre 2026) : la CLK est un signal de plus dans les séquences de la batterie (point 12) : un seul signal change à la fois, CLK comprise ; **elle démarre à 1** ;
les sorties sont lues **à chaque pas** (le cahier dit « juste avant chaque front montant » : ces instants font partie de ceux lus). Chaque pas laisse le circuit se stabiliser : c'est la demi-période, plus longue que T_max.
Pourquoi 1 : au départ toutes les sorties valent 0, et une bascule en NAND dont la CLK est à 0 voit S̄ = R̄ = 1 depuis l'état 0 : elle oscille et serait rejetée. Conséquence à connaître : une bascule maître-esclave (front montant) oscille
au démarrage dans tous les cas ; elle exige une entrée de remise à zéro.

## 14. Section « La variante « défis » » (phase 6, nouveau, pas appliqué)

Décisions de Téo (10 octobre 2026), après une mesure (demi-additionneur trouvé par 0 graine sur 8 sans défi, 7 sur 8 avec) : le **système** choisit la cible au hasard parmi les tables absentes de la bibliothèque et acceptées par les filtres ;
les cibles sont **petites d'abord** : 2 entrées et 2 sorties, puis un cran de plus (une entrée, puis une sortie) à chaque défi atteint, jusqu'aux limites du palier ;
la **proximité** (bits de table égaux à ceux de la cible, sorties dans l'ordre) sert uniquement à choisir les parents (la moitié viennent d'une archive des circuits les plus proches) ; la formule de récompense ne change pas.

## 15. Sections « Les paliers » et « Points à trancher » : durée du palier 4 (phase 6, nouveau, pas appliqué)

Au palier 4, chaque paire de fonctions déjà connues est une nouveauté : la plus longue série de générations sans nouveauté mesurée est de 3 à 17. Le critère « N générations sans nouveauté » ne s'y déclenche donc jamais.
Décision de Téo (10 octobre 2026) : **le palier 4 dure un nombre fixe de générations** (2 000 au départ). Un palier est quitté à la première de deux conditions : N générations sans nouveauté, ou durée atteinte.
Le palier 4 est de 4 entrées et 3 sorties au plus (valeur de départ ; le cahier ne dit pas « plusieurs »). Le palier 5 (« avec CLK ») reprend ces limites, avec les boucles et la CLK.
