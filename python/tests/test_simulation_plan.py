"""Tests du plan précompilé : préparer un circuit une fois, jouer beaucoup de tops.

``compile_circuit`` prépare un circuit aplati ; ``settle``, ``tick`` et ``run_sequence``
l'acceptent (argument ``plan``) pour ne pas le refaire à chaque appel. Le résultat ne
doit jamais changer.
"""

import pytest

from builders import add_nand, add_not, sr_latch, wire, xor_circuit
from logicai.behavior import run_sequence
from logicai.circuit import Circuit, NodeKind
from logicai.errors import SimulationError
from logicai.simulation import compile_circuit, settle, tick

ONE_COMBINATION = 1


def _with_a_component() -> Circuit:
    """Un circuit qui pose un composant, sans rien câbler sur ses sorties."""
    circuit = Circuit()
    circuit.add_node(NodeKind.INPUT)
    circuit.add_component_node("XOR", 2, 1)
    circuit.add_node(NodeKind.OUTPUT)
    return circuit


def _clocked() -> Circuit:
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    clock = circuit.add_node(NodeKind.CLK)
    wire(
        circuit,
        add_nand(circuit, add_not(circuit, data), clock),
        circuit.add_node(NodeKind.OUTPUT),
    )
    return circuit


def test_a_circuit_with_a_component_cannot_be_prepared() -> None:
    # Cahier, « Simulation d'un composant » : on remplace chaque composant par ses NAND
    # (on aplatit) avant de simuler.
    with pytest.raises(SimulationError, match="composant"):
        compile_circuit(_with_a_component())


def test_a_circuit_with_a_component_cannot_be_simulated() -> None:
    with pytest.raises(SimulationError, match="composant"):
        settle(_with_a_component(), [0], ONE_COMBINATION)
    with pytest.raises(SimulationError, match="composant"):
        tick(_with_a_component(), [0], ONE_COMBINATION)


@pytest.mark.parametrize("circuit", [sr_latch(), xor_circuit()], ids=["SR", "XOR"])
def test_a_given_plan_does_not_change_the_result(circuit: Circuit) -> None:
    plan = compile_circuit(circuit)
    inputs = [1] * len(circuit.inputs())
    assert settle(circuit, inputs, ONE_COMBINATION, plan=plan) == settle(
        circuit, inputs, ONE_COMBINATION
    )
    assert tick(circuit, inputs, ONE_COMBINATION, plan=plan) == tick(
        circuit, inputs, ONE_COMBINATION
    )


def test_a_given_plan_works_with_a_state_a_clock_and_a_wide_mask() -> None:
    circuit = _clocked()
    plan = compile_circuit(circuit)
    state = settle(circuit, [0b10], 0b11, clock=0b01).state
    assert settle(circuit, [0b01], 0b11, state, 0b10, plan) == settle(
        circuit, [0b01], 0b11, state, 0b10
    )


def test_a_sequence_gives_the_same_result_with_or_without_a_plan() -> None:
    circuit = sr_latch()
    steps = [(0, 1), (1, 1), (1, 0), (1, 1)]
    assert run_sequence(circuit, steps, plan=compile_circuit(circuit)) == run_sequence(
        circuit, steps
    )


def test_a_plan_is_a_snapshot_of_the_circuit() -> None:
    # Le plan ne suit pas les changements du circuit : il faut le refaire (voir la
    # docstring de ``Plan``). Ici, un câble ajouté après coup n'est pas vu.
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    nand = circuit.add_node(NodeKind.NAND)
    output = circuit.add_node(NodeKind.OUTPUT)
    wire(circuit, nand, output)
    plan = compile_circuit(circuit)
    wire(circuit, data, nand, 0)
    wire(circuit, data, nand, 1)
    old = settle(circuit, [1], ONE_COMBINATION, plan=plan).outputs
    fresh = settle(circuit, [1], ONE_COMBINATION).outputs
    assert old == (1,)  # NAND(0, 0) : les câbles ajoutés après le plan sont ignorés
    assert fresh == (0,)  # NAND(1, 1)
