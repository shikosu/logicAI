"""Test de la phase 6 (cahier, plan de développement).

Test du cahier : « l'IA trouve un demi-additionneur, puis un circuit qui mémorise
(bascule) ».

- **Demi-additionneur** : par le parcours normal (paliers 1 à 4), l'IA ne l'a pas
  trouvé sur 8 graines (voir le journal) : il y a trop de paires de fonctions possibles.
  Avec la variante « défis » (décision de Téo), le système fixe la cible et l'IA la
  trouve. Ici la cible est le demi-additionneur lui-même, passé explicitement : le test
  vérifie que le mécanisme sait y arriver ; en vrai, le système choisit ses défis.
- **Bascule** : avec les boucles permises, l'IA trouve la bascule SR en NAND. Critère :
  la bibliothèque reçoit un composant dont la signature est exactement celle de la
  bascule (2 NAND, le minimum), avec une sortie (Q) ou deux (Q, Q̄).
- **Bascule à horloge** (palier avec CLK) : avec les boucles et la CLK permises, l'IA
  trouve la bascule D (suit D quand la CLK vaut 1, garde sa valeur sinon).

Les graines sont figées et celles qui réussissent dans le budget : toutes ne réussissent
pas (voir le journal pour le taux de réussite).
"""

import pytest

from builders import add_nand, add_not, sr_latch, wire
from logicai.behavior import truth_table
from logicai.challenge import Challenge
from logicai.circuit import Circuit, NodeKind
from logicai.evolution import Evolution
from logicai.flatten import flatten
from logicai.library import Library
from logicai.mutations import MutationRules
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


# --- Le demi-additionneur, avec la variante « défis » ---------------------------------

XOR, AND = 0b0110, 0b1000
HALF_ADDER = Challenge(2, (XOR, AND))  # (SOMME, RETENUE), 2 entrées, 2 sorties
# Générations d'échauffement à 3 entrées et 1 sortie : elles remplissent la bibliothèque
# (environ 1 000 composants), comme dans le parcours réel.
WARM_UP = 800
CHALLENGE_BUDGET = 150
# Graines qui réussissent, aux générations 26, 88 et 43 (mesuré) ; budget 150.
CHALLENGE_SEEDS = (3, 5, 7)
CONTROL_SEED = 3


def _half_adder_search(seed: int, with_challenge: bool) -> tuple[Library, int | None]:
    """Échauffe l'IA, puis cherche le demi-additionneur (avec ou sans défi)."""
    library = Library()
    evolution = Evolution(library, MutationRules(3, 1), seed=seed)
    for _ in range(WARM_UP):
        evolution.step()
    evolution.rules = MutationRules(2, 2)
    if with_challenge:
        evolution.challenge = HALF_ADDER
    for generation in range(1, CHALLENGE_BUDGET + 1):
        evolution.step()
        if library.has_signature(HALF_ADDER.signature):
            return library, generation
    return library, None


@pytest.mark.parametrize("seed", CHALLENGE_SEEDS)
def test_ai_finds_the_half_adder_when_it_is_the_challenge(seed: int) -> None:
    library, generation = _half_adder_search(seed, with_challenge=True)
    assert generation is not None, "demi-additionneur non trouvé dans le budget"
    # Vérification indépendante : on recalcule la table de la définition rangée.
    name = next(
        n
        for n in library.names()
        if library.component(n).signature == HALF_ADDER.signature
    )
    definition = flatten(library.component(name).circuit, library.definitions())
    assert truth_table(definition).outputs == (XOR, AND)


def test_without_the_challenge_the_half_adder_is_not_found_in_the_same_budget() -> None:
    # Contrôle négatif : même graine, même échauffement, même budget, sans défi.
    _, generation = _half_adder_search(CONTROL_SEED, with_challenge=False)
    assert generation is None


# --- La bascule à horloge ------------------------------------------------------------

# Graines qui trouvent la bascule D exacte aux générations 121, 149 et 114 (mesuré),
# avec 1 entrée et 1 sortie, boucles et CLK permises, bibliothèque vide.
D_LATCH_SEEDS = (0, 5, 6)
D_LATCH_BUDGET = 200


def _d_latch() -> Circuit:
    """Bascule D à horloge : entrée D, une CLK, 5 NAND, sortie Q."""
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    clock = circuit.add_node(NodeKind.CLK)
    not_data = add_not(circuit, data)
    set_bar = add_nand(circuit, data, clock)
    reset_bar = add_nand(circuit, not_data, clock)
    q = circuit.add_node(NodeKind.NAND)
    q_bar = circuit.add_node(NodeKind.NAND)
    wire(circuit, set_bar, q, 0)
    wire(circuit, q_bar, q, 1)
    wire(circuit, reset_bar, q_bar, 0)
    wire(circuit, q, q_bar, 1)
    wire(circuit, q, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _d_latch_search(seed: int, allow_clock: bool) -> tuple[Library, int | None]:
    """Cherche la bascule D depuis une bibliothèque vide ; rend aussi la génération."""
    library = Library()
    stage = Stage(5, 1, 1, allow_loops=True, allow_clock=allow_clock)
    evolution = Evolution(library, stage.rules, seed=seed)
    target = _signature_of(_d_latch())
    for generation in range(1, D_LATCH_BUDGET + 1):
        evolution.step()
        if library.has_signature(target):
            return library, generation
    return library, None


@pytest.mark.parametrize("seed", D_LATCH_SEEDS)
def test_ai_finds_the_clocked_d_latch(seed: int) -> None:
    library, generation = _d_latch_search(seed, allow_clock=True)
    assert generation is not None, "bascule D non trouvée dans le budget"
    name = next(
        n
        for n in library.names()
        if library.component(n).signature == _signature_of(_d_latch())
    )
    assert library.component(name).has_memory is True
    # Vérification indépendante : on rejoue la définition rangée dans la bibliothèque.
    definition = flatten(library.component(name).circuit, library.definitions())
    battery = run_battery(definition)
    assert battery is not None
    assert (battery.memory, battery.clocked) == (True, True)


def test_without_the_clock_the_ai_cannot_build_the_d_latch() -> None:
    # Contrôle négatif : sans CLK permise, aucun composant n'a de CLK.
    library, generation = _d_latch_search(D_LATCH_SEEDS[0], allow_clock=False)
    assert generation is None
    for name in library.names():
        definition = flatten(library.component(name).circuit, library.definitions())
        assert definition.clocks() == ()
