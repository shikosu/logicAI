"""Comportement d'un circuit : table de vérité, séquences et mémoire.

Tout repose sur ``settle`` (module ``simulation``) : la table de vérité l'appelle une
seule fois avec un masque large (une combinaison par bit), les séquences l'appellent
pas à pas avec un masque d'un bit en gardant l'état d'un pas au suivant.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from logicai.circuit import Circuit
from logicai.simulation import Status, settle

# Masque d'une seule combinaison d'entrées : les signaux valent 0 ou 1.
_SINGLE_COMBINATION_MASK = 1


def _combination_count(input_count: int) -> int:
    """Renvoie le nombre de combinaisons de n entrées : 2**n (écrit ``1 << n``)."""
    return 1 << input_count


def full_mask(input_count: int) -> int:
    """Renvoie le masque de ``2**n`` bits, un par combinaison : ``(1 << 2**n) - 1``."""
    return (1 << _combination_count(input_count)) - 1


def input_patterns(input_count: int) -> tuple[int, ...]:
    """Renvoie le signal de chaque entrée pour toutes les combinaisons à la fois.

    Le bit k du signal de l'entrée i vaut le bit i de k. Avec 2 entrées :
    A = 0b1010 et B = 0b1100.

    Le signal de l'entrée i est un motif de ``2**i`` zéros puis ``2**i`` uns, répété
    sur toute la longueur. On le construit en doublant le motif (``input_count``
    décalages), au lieu d'additionner ``2**n`` bits un par un : c'est ce qui permet
    de monter à beaucoup d'entrées.
    """
    combination_count = _combination_count(input_count)
    patterns: list[int] = []
    for i in range(input_count):
        half_period = 1 << i
        pattern = ((1 << half_period) - 1) << half_period
        width = 2 * half_period
        while width < combination_count:
            pattern |= pattern << width
            width *= 2
        patterns.append(pattern)
    return tuple(patterns)


@dataclass(frozen=True)
class TruthTable:
    """Signature combinatoire : le statut et un entier par sortie.

    Le bit k de chaque entier vaut la sortie pour la combinaison k. Si le statut
    est ``UNSTABLE``, les entiers ne sont pas significatifs.
    """

    status: Status
    outputs: tuple[int, ...]


def truth_table(circuit: Circuit) -> TruthTable:
    """Renvoie la table de vérité : toutes les combinaisons, en un seul calcul.

    Le circuit est STABLE seulement si toutes les combinaisons sont stables.
    """
    input_count = len(circuit.inputs())
    result = settle(circuit, input_patterns(input_count), full_mask(input_count))
    return TruthTable(result.status, result.outputs)


@dataclass(frozen=True)
class StepResult:
    """Un pas d'une séquence : vecteur d'entrée appliqué, sorties et statut."""

    inputs: tuple[int, ...]
    outputs: tuple[int, ...]
    status: Status


@dataclass(frozen=True)
class SequenceResult:
    """Résultat d'une séquence : un résultat par pas, et le statut de l'ensemble.

    Le statut est ``UNSTABLE`` dès qu'un seul pas est instable.
    """

    status: Status
    steps: tuple[StepResult, ...]


def run_sequence(circuit: Circuit, steps: Sequence[Sequence[int]]) -> SequenceResult:
    """Applique une suite de vecteurs d'entrée, un par pas, sur une seule combinaison.

    Le départ est tout à 0 et l'état est conservé d'un pas au suivant. Chaque pas
    tourne jusqu'à la stabilité (règle de ``settle``). Tous les pas sont simulés,
    même après un pas instable : l'état repris est alors celui du dernier top calculé.
    """
    state: tuple[int, ...] | None = None
    results: list[StepResult] = []
    for vector in steps:
        settled = settle(circuit, vector, _SINGLE_COMBINATION_MASK, state)
        state = settled.state
        results.append(StepResult(tuple(vector), settled.outputs, settled.status))
    unstable = any(step.status is Status.UNSTABLE for step in results)
    status = Status.UNSTABLE if unstable else Status.STABLE
    return SequenceResult(status, tuple(results))


def has_memory(result: SequenceResult) -> bool:
    """Dit si la séquence révèle une mémoire.

    Il y a mémoire quand deux pas d'une séquence stable ont le même vecteur d'entrée
    mais des sorties différentes. Une séquence instable n'est pas examinée.
    """
    if result.status is not Status.STABLE:
        return False
    first_outputs: dict[tuple[int, ...], tuple[int, ...]] = {}
    for step in result.steps:
        known = first_outputs.setdefault(step.inputs, step.outputs)
        if known != step.outputs:
            return True
    return False
