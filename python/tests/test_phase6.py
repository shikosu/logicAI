"""Test de la phase 6 (cahier, plan de développement) : partie mémoire.

Test du cahier : « l'IA trouve un demi-additionneur, puis un circuit qui mémorise
(bascule) ». Ce fichier couvre la seconde moitié : avec les boucles permises, l'IA
trouve une bascule. La première moitié (demi-additionneur) attend la décision sur la
variante « défis » : par le parcours normal (paliers 1 à 4), l'IA ne l'a pas trouvé sur
8 graines (voir le journal).

Critère retenu : la bibliothèque reçoit un composant dont la signature est exactement
celle de la bascule SR en NAND (2 NAND, le minimum), avec une sortie (Q) ou deux
(Q, Q̄). Les graines sont figées et celles qui réussissent dans le budget : toutes ne
réussissent pas (voir le journal pour le taux de réussite).
"""

import pytest

from builders import sr_latch, wire
from logicai.circuit import Circuit, NodeKind
from logicai.evolution import Evolution
from logicai.flatten import flatten
from logicai.library import Library
from logicai.reward import TrialKind, TrialResult
from logicai.sequential import run_battery, sequential_form
from logicai.stages import Stage

# Budget de générations, large devant les 3 à 9 générations mesurées pour ces graines.
BUDGET = 300
# (nombre de sorties, graine) qui trouvent la bascule minimale comme première mémoire.
ONE_OUTPUT_SEEDS = (1, 2, 5)
TWO_OUTPUT_SEEDS = (4, 7)


def _q_only_latch() -> Circuit:
    circuit = Circuit()
    s_bar = circuit.add_node(NodeKind.INPUT)
    r_bar = circuit.add_node(NodeKind.INPUT)
    q = circuit.add_node(NodeKind.NAND)
    q_bar = circuit.add_node(NodeKind.NAND)
    wire(circuit, s_bar, q, 0)
    wire(circuit, q_bar, q, 1)
    wire(circuit, r_bar, q_bar, 0)
    wire(circuit, q, q_bar, 1)
    wire(circuit, q, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _signature_of(circuit: Circuit):  # noqa: ANN202
    battery = run_battery(circuit)
    assert battery is not None
    return sequential_form(battery, len(circuit.inputs())).signature


def _run(seed: int, outputs: int, loops: bool = True) -> tuple[Library, int | None]:
    """Joue jusqu'à la première mémoire (ou au budget) ; rend la bibliothèque.

    Le rang est le numéro de la génération qui l'a trouvée, ou ``None``.
    """
    library = Library()
    evolution = Evolution(
        library, Stage(5, 2, outputs, allow_loops=loops).rules, seed=seed
    )
    for generation in range(1, BUDGET + 1):
        evolution.step()
        if any(library.component(name).has_memory for name in library.names()):
            return library, generation
    return library, None


def _first_memory(library: Library) -> str:
    return next(n for n in library.names() if library.component(n).has_memory)


@pytest.mark.parametrize(
    ("outputs", "seed"),
    [(1, s) for s in ONE_OUTPUT_SEEDS] + [(2, s) for s in TWO_OUTPUT_SEEDS],
)
def test_ai_finds_the_sr_latch(outputs: int, seed: int) -> None:
    library, generation = _run(seed, outputs)
    assert generation is not None, "aucune mémoire trouvée dans le budget"
    name = _first_memory(library)
    expected = _q_only_latch() if outputs == 1 else sr_latch()
    assert library.component(name).signature == _signature_of(expected)
    assert library.cost(name) == 2  # le minimum pour une bascule en NAND


def test_the_found_latch_really_remembers_when_replayed_from_the_library() -> None:
    # Vérification indépendante : on rejoue la définition rangée dans la bibliothèque.
    library, _ = _run(ONE_OUTPUT_SEEDS[0], outputs=1)
    definition = library.component(_first_memory(library)).circuit
    battery = run_battery(flatten(definition, library.definitions()))
    assert battery is not None
    assert battery.memory is True


def test_without_loops_the_ai_never_finds_a_memory() -> None:
    # Contrôle négatif : sans boucle autorisée, aucun circuit ne peut mémoriser.
    for seed in ONE_OUTPUT_SEEDS:
        library, generation = _run(seed, outputs=1, loops=False)
        assert generation is None
        assert not any(library.component(n).has_memory for n in library.names())


def test_the_memory_bonus_reaches_the_ai() -> None:
    # La récompense de la première mémoire contient le bonus : nouveauté (100) +
    # mémoire (100) + 5 par composant réutilisé - k · N_NAND (réglages par défaut).
    seen: list[TrialResult] = []
    library = Library()
    evolution = Evolution(
        library,
        Stage(5, 2, 1, allow_loops=True).rules,
        seed=ONE_OUTPUT_SEEDS[0],
        on_trial=lambda _circuit, result: seen.append(result),
    )
    for _ in range(BUDGET):
        evolution.step()
        if any(r.memory and r.kind is TrialKind.NEW for r in seen):
            break
    first = next(r for r in seen if r.memory and r.kind is TrialKind.NEW)
    cost = library.cost(first.name or "")
    assert first.reward == 100.0 + 100.0 + 5.0 * len(first.reused) - 1.0 * cost


def test_same_seed_same_discovery() -> None:
    # Reproductibilité (règle de CLAUDE.md : tout tirage passe par une graine).
    first, _ = _run(ONE_OUTPUT_SEEDS[0], outputs=1)
    second, _ = _run(ONE_OUTPUT_SEEDS[0], outputs=1)
    assert first.names() == second.names()
    assert [first.cost(n) for n in first.names()] == [
        second.cost(n) for n in second.names()
    ]
