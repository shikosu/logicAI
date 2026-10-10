"""Ce qu'on montre à Unity pour un essai en direct (cahier, « Affichage »).

Pour l'IA évolutionnaire, l'essai en direct est un circuit proposé par l'IA, montré au
ralenti. Il faut des fils colorés par leur valeur (cahier : « câbles colorés selon leur
valeur »). Or les valeurs ne sont pas suivies à l'intérieur d'un composant (voir
``snapshot``). On montre donc le circuit **aplati** (que des NAND) et **nettoyé** (sans
ce qui n'influence aucune sortie), comme le simulateur le voit.

Un essai montré, c'est une suite de messages :

1. un message ``circuit`` : le circuit aplati, avec ses positions ;
2. puis, pour chaque combinaison d'entrées, des messages ``etat`` : les valeurs de
   chaque nœud et de chaque câble **top par top**, du top 0 jusqu'au premier top stable
   (ou jusqu'à la limite T_max + 1 pour un circuit instable).

La combinaison ``k`` donne à l'entrée ``i`` la valeur du bit ``i`` de ``k`` (même
convention que les tables de vérité). Au plus ``MAX_SHOWN_COMBINATIONS`` combinaisons
sont montrées : au-delà, l'essai durerait trop longtemps à regarder.

Ce module ne fait que construire les messages ; le rythme est décidé par
``live_director``.
"""

from collections.abc import Mapping
from typing import Any

from logicai.circuit import Circuit
from logicai.cleanup import remove_useless_nodes
from logicai.flatten import flatten
from logicai.protocol import circuit_message, state_message
from logicai.simulation import max_ticks
from logicai.snapshot import snapshot_at_tick

# Nom du circuit montré (le format d'un fichier exige un nom fait de lettres).
SHOW_NAME = "essai"
# Nombre maximal de combinaisons d'entrées montrées pour un même essai.
MAX_SHOWN_COMBINATIONS = 8


def trial_messages(
    circuit: Circuit, definitions: Mapping[str, Circuit]
) -> tuple[dict[str, Any], ...]:
    """Construit les messages d'un essai : le circuit, puis ses valeurs top par top.

    ``definitions`` donne les composants que le circuit pose. Le circuit donné n'est pas
    modifié. Un circuit invalide (composant inconnu...) lève l'erreur d'aplatissement.
    """
    flat = remove_useless_nodes(flatten(circuit, definitions))
    messages = [circuit_message(SHOW_NAME, flat)]
    for vector in _input_vectors(len(flat.inputs())):
        messages.extend(_frames(flat, vector))
    return tuple(messages)


def _input_vectors(input_count: int) -> list[tuple[int, ...]]:
    """Renvoie les combinaisons montrées (l'entrée i vaut le bit i de k)."""
    shown = min(1 << input_count, MAX_SHOWN_COMBINATIONS)
    return [tuple((k >> i) & 1 for i in range(input_count)) for k in range(shown)]


def _frames(flat: Circuit, vector: tuple[int, ...]) -> list[dict[str, Any]]:
    """Renvoie les messages ``etat`` d'une combinaison, du top 0 au 1er top stable."""
    frames: list[dict[str, Any]] = []
    for ticks in range(max_ticks(flat) + 1):
        snapshot = snapshot_at_tick(flat, vector, ticks)
        frames.append(state_message(flat, snapshot))
        if snapshot.stable:
            break
    return frames
