"""Tests du protocole de l'horloge dans la batterie de séquences.

Décision de Téo (10 octobre 2026) : la CLK est un signal de plus dans les marches (un
seul signal change à la fois, CLK comprise), elle démarre à 1, et les sorties sont lues
à chaque pas. Un circuit qui a une CLK est toujours jugé sur sa batterie.
"""

import itertools
from pathlib import Path

import pytest

from builders import add_nand, add_not, wire
from logicai.behavior import run_sequence
from logicai.circuit import Circuit, NodeKind, Pin
from logicai.errors import SimulationError
from logicai.filters import Rejection, find_behavior_rejections
from logicai.flatten import flatten
from logicai.library import Library, Outcome
from logicai.reward import RewardTracker, TrialKind
from logicai.sequential import (
    CLOCK_START,
    BatteryResult,
    SequentialSignature,
    battery_walks,
    run_battery,
    sequential_form,
    walk_vectors,
)
from logicai.simulation import Status


def _d_latch() -> Circuit:
    """Bascule D à horloge : entrée D, une CLK, 5 NAND, sortie Q (transparente à 1)."""
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    clock = circuit.add_node(NodeKind.CLK)
    _wire_d_latch(circuit, data, clock)
    return circuit


def _wire_d_latch(circuit: Circuit, data: int, enable: int) -> None:
    not_data = add_not(circuit, data)
    set_bar = add_nand(circuit, data, enable)
    reset_bar = add_nand(circuit, not_data, enable)
    q = circuit.add_node(NodeKind.NAND)
    q_bar = circuit.add_node(NodeKind.NAND)
    wire(circuit, set_bar, q, 0)
    wire(circuit, q_bar, q, 1)
    wire(circuit, reset_bar, q_bar, 0)
    wire(circuit, q, q_bar, 1)
    wire(circuit, q, circuit.add_node(NodeKind.OUTPUT))


def _d_latch_with_enable() -> Circuit:
    """Bascule D à deux entrées : D et E ; elle suit D quand CLK vaut 1 et E vaut 0.

    La validation est active à 0 : les entrées démarrent à 0, donc la bascule est
    enclenchée au départ (sinon son cœur voit S̄ = R̄ = 1 depuis l'état 0 et oscille).
    """
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    enable_bar = circuit.add_node(NodeKind.INPUT)
    clock = circuit.add_node(NodeKind.CLK)
    not_enable = add_not(circuit, enable_bar)
    gate = add_not(circuit, add_nand(circuit, clock, not_enable))  # CLK ET NON E
    _wire_d_latch(circuit, data, gate)
    return circuit


def _inverted_clock() -> Circuit:
    """Sans entrée : une CLK, un NOT, une sortie. Pas de mémoire."""
    circuit = Circuit()
    wire(
        circuit,
        add_not(circuit, circuit.add_node(NodeKind.CLK)),
        circuit.add_node(NodeKind.OUTPUT),
    )
    return circuit


def _clock_with_an_irrelevant_branch() -> Circuit:
    """NOT D, dont une branche passe par la CLK sans jamais rien changer.

    X = NAND(CLK, NON CLK) vaut toujours 1, donc NAND(D, X) = NON D.
    """
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    clock = circuit.add_node(NodeKind.CLK)
    always_one = add_nand(circuit, clock, add_not(circuit, clock))
    wire(
        circuit, add_nand(circuit, data, always_one), circuit.add_node(NodeKind.OUTPUT)
    )
    return circuit


def _clock_to_output() -> Circuit:
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    clock = circuit.add_node(NodeKind.CLK)
    wire(circuit, add_not(circuit, data), circuit.add_node(NodeKind.OUTPUT))
    wire(circuit, clock, circuit.add_node(NodeKind.OUTPUT))
    return circuit


# --- Les marches avec la CLK ---------------------------------------------------------


def test_the_clock_starts_at_one() -> None:
    # Décision de Téo : la CLK démarre à 1 (les entrées à 0).
    assert CLOCK_START == 1
    assert walk_vectors(3, (0,), clocked=True)[0] == (0, 0, 1)
    assert walk_vectors(3, (0,), clocked=False)[0] == (0, 0, 0)


def test_every_step_changes_one_signal_the_clock_included() -> None:
    # Décision de Téo : un seul signal change à la fois, la CLK aussi.
    seen_clock_change = False
    for walk in battery_walks(3):
        vectors = walk_vectors(3, walk, clocked=True)
        for before, after in itertools.pairwise(vectors):
            changed = [i for i in range(3) if before[i] != after[i]]
            assert len(changed) == 1
            seen_clock_change = seen_clock_change or changed == [2]
    assert seen_clock_change


def test_the_clock_is_one_more_signal_in_the_battery() -> None:
    # 1 entrée + la CLK = 2 signaux : 2^4 marches ; sans CLK, une seule marche.
    battery = run_battery(_d_latch())
    assert battery is not None
    assert len(battery.responses) == 2**4
    assert battery.clocked is True


# --- La bascule D ------------------------------------------------------------------


def test_the_d_latch_is_stable_and_remembers() -> None:
    battery = run_battery(_d_latch())
    assert battery is not None
    assert (battery.status, battery.memory, battery.clocked) == (
        Status.STABLE,
        True,
        True,
    )


def test_the_d_latch_response_to_one_walk_matches_the_hand_calculation() -> None:
    # Marche D↑, CLK↓, D↓, CLK↑ : départ (D=0, CLK=1) Q=0 ; transparente : Q=1 ; la CLK
    # tombe : Q garde 1 même quand D retombe ; la CLK remonte : Q recopie D = 0.
    battery = run_battery(_d_latch())
    assert battery is not None
    assert battery.responses[(0, 1, 0, 1)] == ((0,), (1,), (1,), (1,), (0,))


def test_a_clock_counts_as_part_of_the_input_for_the_memory() -> None:
    # Une porte ET(D, CLK) change de sortie quand la CLK change, sans mémoire : deux pas
    # n'ont « la même entrée » que si la CLK aussi est la même.
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    clock = circuit.add_node(NodeKind.CLK)
    wire(
        circuit,
        add_not(circuit, add_nand(circuit, data, clock)),
        circuit.add_node(NodeKind.OUTPUT),
    )
    battery = run_battery(circuit)
    assert battery is not None
    assert (battery.status, battery.memory, battery.clocked) == (
        Status.STABLE,
        False,
        True,
    )


def test_run_sequence_needs_one_clock_value_per_step() -> None:
    with pytest.raises(SimulationError, match="horloge"):
        run_sequence(_d_latch(), [(0,), (1,)], clocks=[1])


def test_run_sequence_records_the_clock_in_the_inputs() -> None:
    result = run_sequence(_d_latch(), [(0,), (1,)], clocks=[1, 0])
    assert [step.inputs for step in result.steps] == [(0, 1), (1, 0)]


# --- Un circuit à CLK est toujours jugé sur la batterie ----------------------------


def test_a_clocked_circuit_without_a_loop_still_gets_a_battery() -> None:
    battery = run_battery(_inverted_clock())
    assert battery is not None
    assert (battery.clocked, battery.memory) == (True, False)
    # Sans entrée, il n'y a qu'un signal : la CLK.
    assert len(battery.responses) == 1**4


def test_a_clocked_circuit_without_memory_gets_a_sequential_signature() -> None:
    library = Library()
    registration = library.register(_inverted_clock())
    assert (registration.outcome, registration.name) == (Outcome.NEW, "C-001")
    component = library.component("C-001")
    assert isinstance(component.signature, SequentialSignature)
    assert component.has_memory is False


def test_a_clocked_circuit_without_memory_gets_no_memory_bonus() -> None:
    result = RewardTracker(Library()).evaluate(_inverted_clock())
    assert (result.kind, result.memory) == (TrialKind.NEW, False)
    assert result.reward == 100.0 - 1.0


def test_the_d_latch_earns_the_memory_bonus() -> None:
    result = RewardTracker(Library()).evaluate(_d_latch())
    assert (result.kind, result.memory) == (TrialKind.NEW, True)
    assert result.reward == 100.0 + 100.0 - 1.0 * 5


# --- La signature avec la CLK ------------------------------------------------------


def test_swapped_inputs_keep_the_same_signature_with_a_clock() -> None:
    # La CLK n'est pas une entrée : elle garde sa place quand on échange D et E.
    plain = _d_latch_with_enable()
    swapped = plain.with_inputs_reordered((1, 0))
    first = run_battery(plain)
    second = run_battery(swapped)
    assert first is not None
    assert second is not None
    assert sequential_form(first, 2).signature == sequential_form(second, 2).signature


def test_a_clocked_signature_differs_from_the_same_circuit_without_its_clock() -> None:
    clocked = run_battery(_d_latch())
    assert clocked is not None
    assert len(next(iter(clocked.responses))) == 4


# --- Les filtres avec la CLK -------------------------------------------------------


def test_the_d_latch_passes_the_filters() -> None:
    assert find_behavior_rejections(_d_latch(), {}) == ()
    assert find_behavior_rejections(_d_latch_with_enable(), {}) == ()


def test_a_clock_that_changes_nothing_is_rejected_as_an_unused_input() -> None:
    # Sinon, accrocher une CLK inutile à n'importe quel circuit le ferait passer pour
    # nouveau (sa signature a un signal de plus).
    assert find_behavior_rejections(_clock_with_an_irrelevant_branch(), {}) == (
        Rejection.UNUSED_INPUT,
    )


def test_an_output_that_copies_the_clock_is_rejected() -> None:
    assert find_behavior_rejections(_clock_to_output(), {}) == (Rejection.COPIED_INPUT,)


def test_a_clocked_circuit_that_oscillates_is_rejected() -> None:
    # Cahier : une oscillation rejette le circuit. Ici : la CLK à 0 d'une bascule D
    # n'est pas atteinte au départ, mais une NAND bouclée sur elle-même oscille.
    circuit = _d_latch()
    nand = circuit.add_node(NodeKind.NAND)
    circuit.connect(Pin(nand, 0), Pin(nand, 0))
    circuit.connect(Pin(nand, 0), Pin(nand, 1))
    circuit.connect(Pin(nand, 0), Pin(circuit.add_node(NodeKind.OUTPUT), 0))
    assert find_behavior_rejections(circuit, {}) == (Rejection.UNSTABLE,)


# --- La bibliothèque ---------------------------------------------------------------


def test_the_library_keeps_the_d_latch_as_a_clocked_component() -> None:
    library = Library()
    registration = library.register(_d_latch())
    assert (registration.outcome, registration.name) == (Outcome.NEW, "C-001")
    assert library.component("C-001").has_memory is True
    assert library.cost("C-001") == 5


def test_a_circuit_that_places_the_d_latch_component_keeps_its_clock() -> None:
    # Cahier, « Simulation d'un composant » : on aplatit. La CLK du composant reste une
    # CLK dans le circuit aplati, sans broche en plus.
    library = Library()
    library.register(_d_latch())
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    box = library.instantiate(circuit, "C-001")
    wire(circuit, data, box)
    wire(circuit, box, circuit.add_node(NodeKind.OUTPUT))
    assert (len(circuit.inputs()), circuit.node(box).sink_count) == (1, 1)
    flat = flatten(circuit, library.definitions())
    assert len(flat.clocks()) == 1
    battery = run_battery(flat)
    assert battery is not None
    assert sequential_form(battery, 1).signature == library.component("C-001").signature


def test_a_clocked_component_survives_saving_and_loading(tmp_path: Path) -> None:
    library = Library()
    library.register(_d_latch())
    library.save(tmp_path)
    loaded = Library.load(tmp_path)
    assert loaded.component("C-001").signature == library.component("C-001").signature


def test_an_empty_battery_result_is_not_significant() -> None:
    unstable = BatteryResult(Status.UNSTABLE, False, {}, True)
    assert unstable.responses == {}
