# Modifications proposées pour le cahier des charges

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
