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

Un circuit à mémoire n'a pas de table de vérité significative : ``find_rejections`` le
classe « instable » (sa table, jouée depuis l'état 0, oscille).
``find_behavior_rejections`` juge un circuit sur sa batterie de séquences (module
``sequential``) quand il en a une et, sinon, comme avant. Les cinq filtres y gardent le
même sens, appliqué à chaque pas de chaque séquence :

- une entrée est **inutile** si retirer tous ses changements d'une marche ne modifie
  jamais les sorties (les sorties au pas t valent celles de la marche sans ces
  changements) ;
- une sortie est **constante** si elle ne prend qu'une valeur, à tous les pas ;
- deux sorties sont **identiques** si elles valent pareil à tous les pas ;
- une sortie **recopie une entrée** si elle vaut cette entrée à tous les pas.
"""

from collections.abc import Mapping
from enum import Enum, auto

from logicai.behavior import TruthTable, full_mask, input_patterns, truth_table
from logicai.circuit import Circuit
from logicai.flatten import flatten
from logicai.sequential import Outputs, Responses, Walk, run_battery, walk_vectors
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


def find_behavior_rejections(
    circuit: Circuit, definitions: Mapping[str, Circuit]
) -> tuple[Rejection, ...]:
    """Comme ``find_rejections``, mais un circuit à mémoire est jugé sur sa batterie.

    Un circuit sans boucle, ou dont la batterie ne révèle aucune mémoire, est jugé sur
    sa table de vérité : le résultat est celui de ``find_rejections``. Une marche qui
    oscille donne ``UNSTABLE``. Un circuit à mémoire stable est jugé par les cinq
    filtres appliqués à chaque pas de chaque marche.
    """
    flat = flatten(circuit, definitions)
    input_count = len(circuit.inputs())
    battery = run_battery(flat)
    if battery is None or (battery.status is Status.STABLE and not battery.memory):
        return rejections_of_table(truth_table(flat), input_count)
    if battery.status is Status.UNSTABLE:
        return (Rejection.UNSTABLE,)
    return sequential_rejections(battery.responses, input_count)


def sequential_rejections(
    responses: Responses, input_count: int
) -> tuple[Rejection, ...]:
    """Applique les filtres à la réponse d'un circuit stable à la batterie."""
    observations = _observations(responses, input_count)
    output_count = len(observations[0][1]) if observations else 0
    checks = (
        (
            Rejection.UNUSED_INPUT,
            _sequential_unused_input(responses, input_count),
        ),
        (
            Rejection.CONSTANT_OUTPUT,
            _sequential_constant_output(observations, output_count),
        ),
        (
            Rejection.DUPLICATE_OUTPUTS,
            _sequential_duplicate_outputs(observations, output_count),
        ),
        (
            Rejection.COPIED_INPUT,
            _sequential_copied_input(observations, input_count, output_count),
        ),
    )
    return tuple(reason for reason, found in checks if found)


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


# --- Circuits à mémoire : les filtres sur la batterie --------------------------------

_Observation = tuple[tuple[int, ...], Outputs]


def _observations(responses: Responses, input_count: int) -> list[_Observation]:
    """Renvoie, pour chaque pas de chaque marche, le vecteur d'entrée et les sorties."""
    return [
        (vector, outputs)
        for walk, steps in responses.items()
        for vector, outputs in zip(walk_vectors(input_count, walk), steps, strict=True)
    ]


def _sequential_unused_input(responses: Responses, input_count: int) -> bool:
    """Dit si une entrée n'a d'effet sur aucune sortie, à aucun pas d'aucune marche."""
    prefixes = _prefix_outputs(responses)
    return any(
        not _influences(responses, prefixes, index) for index in range(input_count)
    )


def _prefix_outputs(responses: Responses) -> dict[Walk, tuple[Outputs, ...]]:
    """Donne la réponse de chaque début de marche (au plus L changements d'entrée)."""
    prefixes: dict[Walk, tuple[Outputs, ...]] = {}
    for walk, steps in responses.items():
        for length in range(len(walk) + 1):
            prefixes[walk[:length]] = steps[: length + 1]
    return prefixes


def _influences(
    responses: Responses, prefixes: dict[Walk, tuple[Outputs, ...]], index: int
) -> bool:
    """Dit si les changements de l'entrée ``index`` modifient les sorties quelque part.

    Au pas t d'une marche, on compare les sorties à celles que donne la même marche
    privée de tous ses changements de cette entrée jusqu'au pas t.
    """
    for walk, steps in responses.items():
        for step, outputs in enumerate(steps):
            without = tuple(i for i in walk[:step] if i != index)
            if prefixes[without][-1] != outputs:
                return True
    return False


def _sequential_constant_output(
    observations: list[_Observation], output_count: int
) -> bool:
    """Dit si une sortie ne prend qu'une seule valeur, à tous les pas."""
    return any(
        len({outputs[k] for _, outputs in observations}) == 1
        for k in range(output_count)
    )


def _sequential_duplicate_outputs(
    observations: list[_Observation], output_count: int
) -> bool:
    """Dit si deux sorties valent pareil à tous les pas."""
    return any(
        all(outputs[k] == outputs[other] for _, outputs in observations)
        for k in range(output_count)
        for other in range(k + 1, output_count)
    )


def _sequential_copied_input(
    observations: list[_Observation], input_count: int, output_count: int
) -> bool:
    """Dit si une sortie vaut une entrée à tous les pas (un fil suffirait)."""
    return any(
        all(outputs[k] == vector[i] for vector, outputs in observations)
        for k in range(output_count)
        for i in range(input_count)
    )
