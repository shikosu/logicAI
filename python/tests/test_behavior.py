"""Tests du comportement : table de vérité, séquences et détection de la mémoire."""

from collections.abc import Callable

import pytest

from logicai.behavior import (
    SequenceResult,
    TruthTable,
    full_mask,
    has_memory,
    input_patterns,
    run_sequence,
    truth_table,
)
from logicai.circuit import Circuit, NodeKind, Pin
from logicai.errors import SimulationError
from logicai.simulation import Status, settle

# Masque d'une seule combinaison d'entrées : les signaux valent 0 ou 1.
ONE_COMBINATION = 1

# Une fonction qui câble des portes à partir des entrées et renvoie l'id du nœud
# dont la valeur doit sortir du circuit.
_Builder = Callable[[Circuit, list[int]], int]


# --- Construction des circuits de test ---------------------------------------


def _wire(circuit: Circuit, source_id: int, sink_id: int, sink_index: int = 0) -> None:
    """Relie la source 0 d'un nœud au puits ``sink_index`` d'un autre."""
    circuit.connect(Pin(source_id, 0), Pin(sink_id, sink_index))


def _add_nand(circuit: Circuit, source_a: int, source_b: int) -> int:
    """Ajoute une NAND alimentée par deux sources et renvoie son identifiant."""
    nand_id = circuit.add_node(NodeKind.NAND)
    _wire(circuit, source_a, nand_id, 0)
    _wire(circuit, source_b, nand_id, 1)
    return nand_id


def _add_not(circuit: Circuit, source_id: int) -> int:
    """Ajoute un NOT : une NAND dont les deux puits ont la même source."""
    return _add_nand(circuit, source_id, source_id)


def _gate(input_count: int, build: _Builder) -> Circuit:
    """Crée les entrées, laisse ``build`` câbler les portes, puis ajoute la sortie."""
    circuit = Circuit()
    inputs = [circuit.add_node(NodeKind.INPUT) for _ in range(input_count)]
    result_id = build(circuit, inputs)
    _wire(circuit, result_id, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _build_not(circuit: Circuit, i: list[int]) -> int:
    return _add_not(circuit, i[0])


def _build_nand(circuit: Circuit, i: list[int]) -> int:
    return _add_nand(circuit, i[0], i[1])


def _build_and(circuit: Circuit, i: list[int]) -> int:
    return _add_not(circuit, _add_nand(circuit, i[0], i[1]))


def _build_or(circuit: Circuit, i: list[int]) -> int:
    return _add_nand(circuit, _add_not(circuit, i[0]), _add_not(circuit, i[1]))


def _build_xor(circuit: Circuit, i: list[int]) -> int:
    n1 = _add_nand(circuit, i[0], i[1])
    n2 = _add_nand(circuit, i[0], n1)
    n3 = _add_nand(circuit, i[1], n1)
    return _add_nand(circuit, n2, n3)


def _build_constant_one(circuit: Circuit, i: list[int]) -> int:
    return circuit.add_node(NodeKind.NAND)  # une NAND sans aucun câble


def _looped_not() -> Circuit:
    """Une NAND dont les deux puits sont sur sa propre sortie, lue par une OUTPUT."""
    circuit = Circuit()
    nand_id = circuit.add_node(NodeKind.NAND)
    _wire(circuit, nand_id, nand_id, 0)
    _wire(circuit, nand_id, nand_id, 1)
    _wire(circuit, nand_id, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _one_combination_oscillates() -> Circuit:
    """NAND(A, sa propre sortie) : stable si A = 0 (vaut 1), oscille si A = 1."""
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    nand_id = circuit.add_node(NodeKind.NAND)
    _wire(circuit, input_a, nand_id, 0)
    _wire(circuit, nand_id, nand_id, 1)
    _wire(circuit, nand_id, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _sr_latch() -> Circuit:
    """Bascule SR en NAND : Q = NAND(S̄, Q̄) et Q̄ = NAND(R̄, Q).

    Entrées dans l'ordre (S̄, R̄) ; sorties dans l'ordre (Q, Q̄).
    """
    circuit = Circuit()
    s_bar = circuit.add_node(NodeKind.INPUT)
    r_bar = circuit.add_node(NodeKind.INPUT)
    nand_q = circuit.add_node(NodeKind.NAND)
    nand_q_bar = circuit.add_node(NodeKind.NAND)
    _wire(circuit, s_bar, nand_q, 0)
    _wire(circuit, nand_q_bar, nand_q, 1)
    _wire(circuit, r_bar, nand_q_bar, 0)
    _wire(circuit, nand_q, nand_q_bar, 1)
    _wire(circuit, nand_q, circuit.add_node(NodeKind.OUTPUT))
    _wire(circuit, nand_q_bar, circuit.add_node(NodeKind.OUTPUT))
    return circuit


# --- Masque et motifs d'entrée -----------------------------------------------


@pytest.mark.parametrize(
    ("input_count", "expected"),
    [(0, 0b1), (1, 0b11), (2, 0b1111), (3, 0xFF)],
)
def test_full_mask_has_one_bit_per_combination(input_count: int, expected: int) -> None:
    # Règle vérifiée : prompt phase 1, section C (masque = (1 << 2**n) - 1).
    assert full_mask(input_count) == expected


@pytest.mark.parametrize(
    ("input_count", "expected"),
    [
        (0, ()),
        (1, (0b10,)),
        (2, (0b1010, 0b1100)),  # A et B de l'exemple du cahier
        (3, (0b10101010, 0b11001100, 0b11110000)),
    ],
)
def test_input_patterns_bit_k_is_bit_i_of_k(
    input_count: int, expected: tuple[int, ...]
) -> None:
    # Règle vérifiée : prompt phase 1, section C (l'entrée i vaut le bit i de k).
    assert input_patterns(input_count) == expected


# --- Tableau E : tables de vérité --------------------------------------------


@pytest.mark.parametrize(
    ("build", "input_count", "nand_count", "expected"),
    [
        pytest.param(_build_not, 1, 1, 0b01, id="NOT"),
        pytest.param(_build_nand, 2, 1, 0b0111, id="NAND"),
        pytest.param(_build_and, 2, 2, 0b1000, id="AND"),
        pytest.param(_build_or, 2, 3, 0b1110, id="OR"),
        pytest.param(_build_xor, 2, 4, 0b0110, id="XOR"),
        pytest.param(_build_constant_one, 0, 1, 0b1, id="constante-1"),
    ],
)
def test_truth_tables_of_the_reference_circuits(
    build: _Builder, input_count: int, nand_count: int, expected: int
) -> None:
    # Règle vérifiée : prompt phase 1, tableau E (valeurs attendues, toutes stables).
    circuit = _gate(input_count, build)
    assert circuit.nand_count() == nand_count
    assert truth_table(circuit) == TruthTable(Status.STABLE, (expected,))


def test_unwired_output_is_zero() -> None:
    # Règle vérifiée : prompt phase 1, tableau E (sortie non reliée : 0).
    circuit = Circuit()
    circuit.add_node(NodeKind.OUTPUT)
    result = truth_table(circuit)
    assert result.status is Status.STABLE
    assert result.outputs == (0,)


def test_looped_not_truth_table_is_unstable() -> None:
    # Règle vérifiée : prompt phase 1, tableau E (NOT rebouclé : UNSTABLE).
    assert truth_table(_looped_not()).status is Status.UNSTABLE


def test_one_oscillating_combination_makes_the_circuit_unstable() -> None:
    # Règle vérifiée : prompt phase 1, section C (STABLE seulement si toutes les
    # combinaisons sont stables). Ici A = 0 est stable et A = 1 oscille.
    assert truth_table(_one_combination_oscillates()).status is Status.UNSTABLE


def test_outputs_come_in_creation_order() -> None:
    # Règle vérifiée : prompt phase 1, section D (un entier par sortie, dans l'ordre
    # de création). Sortie 1 = A, sortie 2 = NOT A.
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    _wire(circuit, input_a, circuit.add_node(NodeKind.OUTPUT))
    _wire(circuit, _add_not(circuit, input_a), circuit.add_node(NodeKind.OUTPUT))
    result = truth_table(circuit)
    assert result.status is Status.STABLE
    assert result.outputs == (0b10, 0b01)


@pytest.mark.parametrize(
    "circuit",
    [
        pytest.param(_gate(2, _build_xor), id="XOR"),
        pytest.param(_gate(2, _build_or), id="OR"),
        pytest.param(_sr_latch(), id="bascule-SR"),
        pytest.param(_one_combination_oscillates(), id="une-combinaison-oscille"),
    ],
)
def test_bit_parallel_matches_one_combination_at_a_time(circuit: Circuit) -> None:
    # Règle vérifiée : prompt phase 1, section C (le bit-parallèle donne, pour
    # chaque combinaison, ce que donne la simulation d'une seule combinaison).
    input_count = len(circuit.inputs())
    table = truth_table(circuit)
    all_stable = True
    for k in range(2**input_count):
        vector = tuple((k >> i) & 1 for i in range(input_count))
        single = settle(circuit, vector, ONE_COMBINATION)
        if single.status is Status.UNSTABLE:
            all_stable = False
            continue
        for output_index, value in enumerate(single.outputs):
            assert (table.outputs[output_index] >> k) & 1 == value
    assert (table.status is Status.STABLE) == all_stable


# --- Tableau E : séquences et mémoire ----------------------------------------

_SR_SEQUENCE = [(0, 1), (1, 1), (1, 0), (1, 1)]


def test_sr_latch_sequence_remembers() -> None:
    # Règle vérifiée : prompt phase 1, tableau E (bascule SR : Q = 1, 1, 0, 0 ;
    # chaque pas stable ; mémoire détectée).
    result = run_sequence(_sr_latch(), _SR_SEQUENCE)
    assert result.status is Status.STABLE
    assert [step.status for step in result.steps] == [Status.STABLE] * 4
    assert [step.outputs[0] for step in result.steps] == [1, 1, 0, 0]
    assert has_memory(result) is True


def test_sequence_result_lists_inputs_outputs_and_status_per_step() -> None:
    # Règle vérifiée : prompt phase 1, section D (pour chaque pas, les sorties et
    # le statut). Sorties (Q, Q̄) calculées à la main : (1,0), (1,0), (0,1), (0,1).
    result = run_sequence(_sr_latch(), _SR_SEQUENCE)
    assert [step.inputs for step in result.steps] == _SR_SEQUENCE
    assert [step.outputs for step in result.steps] == [(1, 0), (1, 0), (0, 1), (0, 1)]


def test_metastability_sequence_is_unstable() -> None:
    # Règle vérifiée : prompt phase 1, tableau E (métastabilité : (S̄, R̄) = (1, 1)
    # dès le premier pas, depuis l'état tout à 0 : UNSTABLE).
    result = run_sequence(_sr_latch(), [(1, 1)])
    assert result.status is Status.UNSTABLE
    assert [step.status for step in result.steps] == [Status.UNSTABLE]
    assert has_memory(result) is False


def test_one_unstable_step_makes_the_whole_sequence_unstable() -> None:
    # Règle vérifiée : prompt phase 1, section D (si un pas est instable, la
    # séquence entière est instable) ; ambiguïté 5 du plan : tous les pas sont
    # simulés. Pas 1 instable, puis (0, 1) se stabilise en 2 tops (calcul à la main).
    result = run_sequence(_sr_latch(), [(1, 1), (0, 1)])
    assert result.status is Status.UNSTABLE
    assert [step.status for step in result.steps] == [Status.UNSTABLE, Status.STABLE]
    assert result.steps[1].outputs == (1, 0)


def test_memory_is_not_looked_for_in_an_unstable_sequence() -> None:
    # Règle vérifiée : prompt phase 1, section D (mémoire : « deux pas d'une
    # séquence stable ») ; ambiguïté 6 du plan. Les pas 1 et 3 ont le même vecteur
    # (1, 1) et des sorties différentes, mais la séquence est instable.
    result = run_sequence(_sr_latch(), [(1, 1), (0, 1), (1, 1)])
    assert result.status is Status.UNSTABLE
    assert result.steps[0].outputs != result.steps[2].outputs
    assert has_memory(result) is False


def test_combinational_circuit_has_no_memory() -> None:
    # Règle vérifiée : cahier, « Les trois cas détectés » (mémoire : la sortie diffère
    # pour une même entrée). Un XOR répond toujours pareil à une même entrée.
    sequence = [(0, 0), (1, 1), (0, 0), (1, 0), (1, 1)]
    result = run_sequence(_gate(2, _build_xor), sequence)
    assert result.status is Status.STABLE
    assert [step.outputs for step in result.steps] == [(0,), (0,), (0,), (1,), (0,)]
    assert has_memory(result) is False


def test_empty_sequence_is_stable_without_memory() -> None:
    # Règle vérifiée : prompt phase 1, section D (aucun pas, donc aucun pas instable).
    result = run_sequence(_sr_latch(), [])
    assert result == SequenceResult(Status.STABLE, ())
    assert has_memory(result) is False


@pytest.mark.parametrize("vector", [(), (0,), (0, 0, 0), (0, 2), (-1, 0)])
def test_invalid_input_vector_is_refused(vector: tuple[int, ...]) -> None:
    # Règle vérifiée : ambiguïté 8 du plan (vecteur de mauvaise longueur, ou valeur
    # autre que 0 ou 1).
    with pytest.raises(SimulationError):
        run_sequence(_sr_latch(), [vector])
