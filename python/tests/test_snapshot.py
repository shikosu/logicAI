"""Tests du relevé des valeurs 0/1 d'un circuit (le contenu du message « etat »)."""

import random
from collections.abc import Callable

import pytest

from builders import (
    Builder,
    build_and,
    build_nand,
    build_or,
    build_xor,
    gate,
    not_circuit,
    random_circuit,
    sr_latch,
    wire,
    xor_circuit,
)
from logicai.behavior import truth_table
from logicai.circuit import Circuit, NodeKind, Pin
from logicai.errors import SimulationError, SnapshotError
from logicai.simulation import tick
from logicai.snapshot import (
    Snapshot,
    sequence_snapshots,
    settled_snapshot,
    snapshot_at_tick,
)

SEED = 20261012  # graine fixe : les circuits tirés au hasard sont reproductibles


def _looped_not() -> Circuit:
    """Une NAND dont les deux puits sont sur sa propre sortie, lue par une OUTPUT."""
    circuit = Circuit()
    nand_id = circuit.add_node(NodeKind.NAND)
    wire(circuit, nand_id, nand_id, 0)
    wire(circuit, nand_id, nand_id, 1)
    wire(circuit, nand_id, circuit.add_node(NodeKind.OUTPUT))
    return circuit


# --- Valeurs d'un circuit stable ------------------------------------------------------


def test_xor_values_with_a_1_and_b_0() -> None:
    # Règle vérifiée : cahier, message « etat » (les valeurs 0/1 de chaque fil). Calculé
    # à la main : tops (1,1,1,1), (1,0,1,0), (1,0,1,1), puis plus rien ne change au top
    # 4.
    # Nœuds : A, B, n1, n2, n3, n4, sortie. Câbles : A>n1, B>n1, A>n2, n1>n2, B>n3,
    # n1>n3, n2>n4, n3>n4, n4>sortie.
    snapshot = settled_snapshot(xor_circuit(), (1, 0))
    assert snapshot == Snapshot(
        top=4,
        stable=True,
        node_values=(1, 0, 1, 0, 1, 1, 1),
        wire_values=(1, 0, 1, 1, 0, 1, 0, 1, 1),
    )


@pytest.mark.parametrize(
    ("build", "function"),
    [
        pytest.param(build_nand, lambda a, b: 1 - (a & b), id="NAND"),
        pytest.param(build_and, lambda a, b: a & b, id="AND"),
        pytest.param(build_or, lambda a, b: a | b, id="OR"),
        pytest.param(build_xor, lambda a, b: a ^ b, id="XOR"),
    ],
)
def test_output_value_matches_the_gate_and_the_truth_table(
    build: Builder, function: Callable[[int, int], int]
) -> None:
    # Règle vérifiée : prompt phase 1, tableau E : la valeur du nœud de sortie relevée
    # par ``settled_snapshot`` est celle de la table de vérité, pour chaque combinaison.
    circuit = gate(2, build)
    table = truth_table(circuit).outputs[0]
    output_index = len(circuit.nodes()) - 1
    for combination in range(4):
        a, b = combination & 1, combination >> 1
        snapshot = settled_snapshot(circuit, (a, b))
        assert snapshot.stable is True
        assert snapshot.node_values[output_index] == function(a, b)
        assert snapshot.node_values[output_index] == (table >> combination) & 1


def test_unwired_output_reads_zero() -> None:
    # Règle vérifiée : prompt phase 1, section B (une OUTPUT non reliée vaut 0).
    circuit = Circuit()
    circuit.add_node(NodeKind.OUTPUT)
    assert settled_snapshot(circuit, ()) == Snapshot(1, True, (0,), ())


def test_constant_one_gate() -> None:
    # Règle vérifiée : cahier, règle de câblage n°4 (NAND sans câble : 1 constant).
    circuit = gate(0, lambda c, _: c.add_node(NodeKind.NAND))
    snapshot = settled_snapshot(circuit, ())
    assert snapshot.node_values == (1, 1)
    assert snapshot.wire_values == (1,)


# --- Tops un par un -------------------------------------------------------------------


def test_looped_not_oscillates_top_by_top() -> None:
    # Règle vérifiée : cahier, « Les trois cas détectés » (instable : les sorties
    # changent
    # encore). Départ 0, la NAND vaut 0, 1, 0, 1 aux tops 0 à 3, et n'est jamais stable.
    # Nœuds : NAND, sortie. Câbles : NAND>NAND, NAND>NAND, NAND>sortie.
    circuit = _looped_not()
    for ticks, value in enumerate((0, 1, 0, 1)):
        assert snapshot_at_tick(circuit, (), ticks) == Snapshot(
            top=ticks,
            stable=False,
            node_values=(value, value),
            wire_values=(value, value, value),
        )


def test_circuit_already_at_rest_is_stable_at_top_zero() -> None:
    # Règle vérifiée : prompt phase 1, section B (stable dès qu'un top ne change rien) :
    # NOT avec A = 1 : NAND(1, 1) = 0, l'état de départ ne bouge pas.
    snapshot = snapshot_at_tick(not_circuit(), (1,), 0)
    assert snapshot == Snapshot(0, True, (1, 0, 0), (1, 1, 0))


def test_starting_state_can_be_given() -> None:
    # Règle vérifiée : prompt phase 1, section D (l'état est conservé) : la bascule SR
    # qui vaut déjà (Q, Q̄) = (1, 0) reste ainsi avec (S̄, R̄) = (1, 1).
    snapshot = snapshot_at_tick(sr_latch(), (1, 1), 0, state=(1, 0))
    assert snapshot.stable is True
    assert snapshot.node_values == (1, 1, 1, 0, 1, 0)


def test_unstable_circuit_settles_on_its_last_computed_tick() -> None:
    # Règle vérifiée : ambiguïté 4 du plan de la phase 1 (valeurs du dernier top
    # calculé).
    snapshot = settled_snapshot(_looped_not(), ())
    assert snapshot == Snapshot(
        top=2, stable=False, node_values=(0, 0), wire_values=(0, 0, 0)
    )


# --- Séquence (bascule SR) ------------------------------------------------------------


def test_sr_latch_sequence_shows_the_memory() -> None:
    # Règle vérifiée : prompt phase 1, tableau E (bascule SR : Q = 1, 1, 0, 0, chaque
    # pas
    # stable, en 3, 1, 3, 1 tops). Nœuds : S̄, R̄, Q, Q̄, sortie Q, sortie Q̄.
    snapshots = sequence_snapshots(sr_latch(), [(0, 1), (1, 1), (1, 0), (1, 1)])
    assert [s.node_values for s in snapshots] == [
        (0, 1, 1, 0, 1, 0),
        (1, 1, 1, 0, 1, 0),
        (1, 0, 0, 1, 0, 1),
        (1, 1, 0, 1, 0, 1),
    ]
    assert [s.top for s in snapshots] == [3, 1, 3, 1]
    assert all(s.stable for s in snapshots)


def test_empty_sequence_gives_no_snapshot() -> None:
    # Règle vérifiée : prompt phase 1, section D (aucun pas, aucun relevé).
    assert sequence_snapshots(sr_latch(), []) == ()


def test_metastable_step_is_not_stable() -> None:
    # Règle vérifiée : cahier, « Piège à connaître » (métastabilité).
    (snapshot,) = sequence_snapshots(sr_latch(), [(1, 1)])
    assert snapshot.stable is False


# --- Propriétés générales -------------------------------------------------------------


def test_values_follow_the_simulation_on_random_circuits() -> None:
    # Règle vérifiée : cahier, message « etat » : sur 200 circuits au hasard (boucles
    # comprises), les valeurs des NAND sont celles de ``tick``, une sortie lit sa
    # source,
    # et un câble vaut la valeur de sa source.
    rng = random.Random(SEED)
    for _ in range(200):
        circuit = random_circuit(rng)
        vector = tuple(rng.randint(0, 1) for _ in circuit.inputs())
        ticks = rng.randint(0, 5)
        snapshot = snapshot_at_tick(circuit, vector, ticks)

        state = None
        for _ in range(ticks):
            state = tick(circuit, vector, 1, state)
        nand_values = [
            value
            for node, value in zip(circuit.nodes(), snapshot.node_values, strict=True)
            if node.kind is NodeKind.NAND
        ]
        assert nand_values == list(
            state if state is not None else (0,) * len(nand_values)
        )

        value_of = {
            n.node_id: v
            for n, v in zip(circuit.nodes(), snapshot.node_values, strict=True)
        }
        for output_id in circuit.outputs():
            source = circuit.source_of(Pin(output_id, 0))
            expected = 0 if source is None else value_of[source.node_id]
            assert value_of[output_id] == expected
        for wire_, value in zip(circuit.wires(), snapshot.wire_values, strict=True):
            assert value == value_of[wire_.source.node_id]


# --- Refus ----------------------------------------------------------------------------


def test_circuit_with_components_is_refused() -> None:
    # Règle vérifiée : décision du plan (pas de valeurs pour un circuit avec
    # composants).
    circuit = Circuit()
    circuit.add_component_node("XOR", 2, 1)
    with pytest.raises(SnapshotError):
        settled_snapshot(circuit, ())
    with pytest.raises(SnapshotError):
        snapshot_at_tick(circuit, (), 0)
    with pytest.raises(SnapshotError):
        sequence_snapshots(circuit, [()])


def test_negative_number_of_ticks_is_refused() -> None:
    # Règle vérifiée : CLAUDE.md (refus clair d'une donnée invalide).
    with pytest.raises(SnapshotError):
        snapshot_at_tick(not_circuit(), (0,), -1)


@pytest.mark.parametrize("vector", [(), (0, 0), (2,)])
def test_invalid_input_vector_is_refused_even_at_top_zero(
    vector: tuple[int, ...],
) -> None:
    # Règle vérifiée : ambiguïté 8 du plan de la phase 1 (vecteur d'entrée invalide).
    with pytest.raises(SimulationError):
        snapshot_at_tick(not_circuit(), vector, 0)
    with pytest.raises(SimulationError):
        settled_snapshot(not_circuit(), vector)
