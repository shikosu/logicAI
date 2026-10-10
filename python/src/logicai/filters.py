"""Filtres anti-triche : refuser les circuits inutiles avant de les récompenser.

Sans filtres, l'IA trouve vite des moyens de gagner des points sans rien construire
d'utile (cahier, « Les filtres anti-triche »). Un circuit est refusé si :

- une de ses entrées n'influence aucune sortie ;
- une de ses sorties est constante ;
- deux de ses sorties sont identiques ;
- une sortie recopie simplement une entrée (un fil suffirait) ;
- il est instable.

Les filtres jugent le **comportement** (la table de vérité du circuit aplati), pas le
câblage : un circuit câblé de façon tordue mais équivalent à un fil est refusé aussi.
Ils ne modifient jamais le circuit. Un circuit refusé vaut 0 point (cahier, schéma du
chemin d'un essai).
"""

from collections.abc import Mapping
from enum import Enum, auto

from logicai.behavior import TruthTable, full_mask, input_patterns, truth_table
from logicai.circuit import Circuit
from logicai.flatten import flatten
from logicai.simulation import Status


class Rejection(Enum):
    """Pourquoi un circuit est refusé (un motif par filtre du cahier)."""

    UNUSED_INPUT = auto()  # une entrée n'influence aucune sortie
    CONSTANT_OUTPUT = auto()  # une sortie vaut toujours 0 ou toujours 1
    DUPLICATE_OUTPUTS = auto()  # deux sorties ont la même table de vérité
    COPIED_INPUT = auto()  # une sortie est exactement une entrée
    UNSTABLE = auto()  # le circuit oscille : pas de signature


def find_rejections(
    circuit: Circuit, definitions: Mapping[str, Circuit]
) -> tuple[Rejection, ...]:
    """Renvoie les motifs de rejet d'un circuit ; un tuple vide veut dire « accepté ».

    ``definitions`` donne les composants que le circuit pose (comme pour ``flatten``).
    Le circuit n'est pas modifié. Un circuit qu'on ne sait pas aplatir (composant
    inconnu...) lève l'erreur de ``flatten`` : ce n'est pas un circuit « inutile »,
    c'est un circuit invalide.
    """
    table = truth_table(flatten(circuit, definitions))
    return rejections_of_table(table, len(circuit.inputs()))


def rejections_of_table(table: TruthTable, input_count: int) -> tuple[Rejection, ...]:
    """Applique les filtres à une table de vérité, dans l'ordre du cahier.

    Un circuit instable n'a pas de table significative : il est refusé pour cette
    seule raison, les autres filtres ne sont pas examinés.
    """
    if table.status is not Status.STABLE:
        return (Rejection.UNSTABLE,)
    checks = (
        (Rejection.UNUSED_INPUT, _has_unused_input),
        (Rejection.CONSTANT_OUTPUT, _has_constant_output),
        (Rejection.DUPLICATE_OUTPUTS, _has_duplicate_outputs),
        (Rejection.COPIED_INPUT, _has_copied_input),
    )
    return tuple(
        reason for reason, check in checks if check(table.outputs, input_count)
    )


def _has_unused_input(outputs: tuple[int, ...], input_count: int) -> bool:
    """Dit si une entrée n'a d'effet sur aucune sortie."""
    patterns = input_patterns(input_count)
    full = full_mask(input_count)
    return any(
        not _influences_any(outputs, 1 << index, full ^ pattern)
        for index, pattern in enumerate(patterns)
    )


def _influences_any(outputs: tuple[int, ...], half_period: int, low_half: int) -> bool:
    """Dit si changer une entrée change au moins une sortie, pour au moins un cas.

    ``half_period`` vaut ``2**i`` pour l'entrée i : décaler une table de ce nombre de
    bits met en face de chaque combinaison où l'entrée i vaut 0 la même combinaison
    avec l'entrée i à 1. ``low_half`` garde seulement les combinaisons où l'entrée
    vaut 0.
    """
    return any(((out >> half_period) ^ out) & low_half for out in outputs)


def _has_constant_output(outputs: tuple[int, ...], input_count: int) -> bool:
    """Dit si une sortie vaut toujours 0 ou toujours 1."""
    full = full_mask(input_count)
    return any(out in (0, full) for out in outputs)


def _has_duplicate_outputs(outputs: tuple[int, ...], input_count: int) -> bool:
    """Dit si deux sorties ont la même table de vérité.

    ``input_count`` ne sert pas ici : tous les filtres ont la même forme pour être
    rangés dans une seule liste (voir ``rejections_of_table``).
    """
    return len(set(outputs)) < len(outputs)


def _has_copied_input(outputs: tuple[int, ...], input_count: int) -> bool:
    """Dit si une sortie est exactement une entrée (un fil suffirait)."""
    patterns = set(input_patterns(input_count))
    return any(out in patterns for out in outputs)
