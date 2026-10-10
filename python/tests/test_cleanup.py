"""Tests du nettoyage : retirer ce qui n'influence aucune sortie."""

import pytest

from builders import (
    add_nand,
    add_not,
    build_not,
    build_xor,
    gate,
    sr_latch,
    wire,
    xor_circuit,
)
from logicai.behavior import run_sequence, truth_table
from logicai.circuit import Circuit, Node, NodeKind, Wire
from logicai.cleanup import remove_useless_nodes


def _snapshot(circuit: Circuit) -> tuple[tuple[Node, ...], tuple[Wire, ...]]:
    """Photographie les nœuds et les câbles."""
    return circuit.nodes(), circuit.wires()


def _xor_with_junk() -> tuple[Circuit, tuple[Node, ...]]:
    """Un XOR complet, plus des NAND posées après coup qui ne mènent à aucune sortie.

    Renvoie le circuit et les nœuds du XOR seul, pour comparer après nettoyage.
    """
    circuit = xor_circuit()
    clean_nodes = circuit.nodes()
    input_a, input_b = circuit.inputs()
    junk_1 = add_nand(circuit, input_a, input_b)
    add_not(circuit, junk_1)  # une 2e NAND inutile, alimentée par la 1re
    return circuit, clean_nodes


# --- Ce qui est retiré ---------------------------------------------------------


def test_nand_that_reaches_no_output_is_removed_with_its_wires() -> None:
    # Règle vérifiée : cahier, « Nettoyage » (on retire les NAND et les câbles qui
    # n'influencent aucune sortie), y compris une chaîne de deux NAND inutiles.
    circuit, clean_nodes = _xor_with_junk()
    assert circuit.nand_count() == 6

    cleaned = remove_useless_nodes(circuit)

    assert cleaned.nodes() == clean_nodes
    assert cleaned.nand_count() == 4
    assert len(cleaned.wires()) == len(xor_circuit().wires())


def test_dead_loop_is_removed() -> None:
    # Règle vérifiée : cahier, « Nettoyage ». Une NAND rebouclée sur elle-même qui ne
    # mène à aucune sortie n'influence rien : elle est retirée.
    circuit = xor_circuit()
    dead = circuit.add_node(NodeKind.NAND)
    wire(circuit, dead, dead, 0)
    wire(circuit, dead, dead, 1)
    assert remove_useless_nodes(circuit).nand_count() == 4


def test_dead_branch_of_a_live_gate_is_removed_but_the_gate_stays() -> None:
    # Règle vérifiée : cahier, « Nettoyage ». Une NAND utile qui alimente aussi une
    # branche morte reste branchée sur sa sortie ; seule la branche morte part.
    circuit = gate(1, build_not)
    live_not = circuit.nodes()[1].node_id  # nœuds : entrée, NOT, sortie
    dead = add_not(circuit, live_not)
    cleaned = remove_useless_nodes(circuit)
    assert dead not in {node.node_id for node in cleaned.nodes()}
    assert cleaned.nodes() == tuple(n for n in circuit.nodes() if n.node_id != dead)
    assert truth_table(cleaned) == truth_table(circuit)


def test_useless_component_is_removed_and_useful_one_is_kept() -> None:
    # Règle vérifiée : décision du plan (le nettoyage retire aussi les composants qui
    # n'influencent aucune sortie).
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    useful = circuit.add_component_node("NOT", 1, 1)
    useless = circuit.add_component_node("NOT", 1, 1)
    wire(circuit, input_a, useful)
    wire(circuit, input_a, useless)
    wire(circuit, useful, circuit.add_node(NodeKind.OUTPUT))
    cleaned = remove_useless_nodes(circuit)
    assert [n.node_id for n in cleaned.nodes() if n.kind is NodeKind.COMPONENT] == [
        useful
    ]


def test_circuit_without_output_loses_all_its_gates() -> None:
    # Règle vérifiée : cahier, « Nettoyage » (rien n'influence une sortie qui
    # n'existe pas).
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    add_not(circuit, input_a)
    cleaned = remove_useless_nodes(circuit)
    assert [n.kind for n in cleaned.nodes()] == [NodeKind.INPUT]


# --- Ce qui est gardé ----------------------------------------------------------


def test_circuit_with_nothing_useless_is_unchanged() -> None:
    # Règle vérifiée : cahier, « Nettoyage » (on ne retire que ce qui est inutile).
    for circuit in (xor_circuit(), sr_latch()):
        assert _snapshot(remove_useless_nodes(circuit)) == _snapshot(circuit)


def test_live_loop_is_kept() -> None:
    # Règle vérifiée : cahier, règle de câblage n°5 (les boucles sont autorisées) :
    # une boucle qui alimente une sortie influence cette sortie, donc elle reste.
    circuit = Circuit()
    nand_id = circuit.add_node(NodeKind.NAND)
    wire(circuit, nand_id, nand_id, 0)
    wire(circuit, nand_id, nand_id, 1)
    wire(circuit, nand_id, circuit.add_node(NodeKind.OUTPUT))
    assert _snapshot(remove_useless_nodes(circuit)) == _snapshot(circuit)


def test_inputs_and_outputs_are_never_removed() -> None:
    # Règle vérifiée : cahier, « Ordre des broches » (les entrées et sorties sont les
    # broches du composant) : une entrée inutilisée et une sortie libre restent.
    circuit = Circuit()
    circuit.add_node(NodeKind.INPUT)
    circuit.add_node(NodeKind.INPUT)
    circuit.add_node(NodeKind.OUTPUT)
    assert _snapshot(remove_useless_nodes(circuit)) == _snapshot(circuit)


def test_kept_nodes_keep_their_identifiers_and_order() -> None:
    # Règle vérifiée : cahier, « Ordre des broches » (numérotées dans leur ordre de
    # création) et prompt phase 1, section A (identifiants stables).
    circuit, _ = _xor_with_junk()
    cleaned = remove_useless_nodes(circuit)
    assert cleaned.inputs() == circuit.inputs()
    assert cleaned.outputs() == circuit.outputs()
    for node in cleaned.nodes():
        assert circuit.node(node.node_id) == node


# --- Le comportement ne change pas ---------------------------------------------


def test_cleaning_does_not_change_the_truth_table() -> None:
    # Règle vérifiée : cahier, « Nettoyage » (ce qui est retiré n'influence aucune
    # sortie, donc la signature reste la même).
    circuit, _ = _xor_with_junk()
    assert truth_table(remove_useless_nodes(circuit)) == truth_table(circuit)
    assert truth_table(remove_useless_nodes(circuit)) == truth_table(gate(2, build_xor))


@pytest.mark.parametrize(
    "sequence",
    [[(0, 1), (1, 1), (1, 0), (1, 1)], [(1, 1)]],
    ids=["memoire", "metastabilite"],
)
def test_cleaning_does_not_change_a_sequence(sequence: list[tuple[int, int]]) -> None:
    # Règle vérifiée : cahier, « Nettoyage » : la mémoire d'une bascule est conservée.
    circuit = sr_latch()
    input_s, _ = circuit.inputs()
    add_not(circuit, input_s)  # une NAND inutile
    assert run_sequence(remove_useless_nodes(circuit), sequence) == run_sequence(
        sr_latch(), sequence
    )


def test_original_circuit_is_not_modified() -> None:
    # Règle vérifiée : CLAUDE.md (une opération n'abîme pas les données données).
    circuit, _ = _xor_with_junk()
    before = _snapshot(circuit)
    remove_useless_nodes(circuit)
    assert _snapshot(circuit) == before


# --- Grande taille -------------------------------------------------------------


def test_very_long_chains_do_not_overflow_the_stack() -> None:
    # Règle vérifiée : cahier, « Taille maximale » (aucune limite fixe de taille) :
    # le nettoyage doit supporter de très longues chaînes, vivantes ou mortes.
    length = 3000
    circuit = Circuit()
    source = circuit.add_node(NodeKind.INPUT)
    dead_source = source
    for _ in range(length):
        source = add_not(circuit, source)
    wire(circuit, source, circuit.add_node(NodeKind.OUTPUT))
    for _ in range(length):
        dead_source = add_not(circuit, dead_source)
    assert circuit.nand_count() == 2 * length

    assert remove_useless_nodes(circuit).nand_count() == length


def test_removing_a_dead_consumer_keeps_the_other_wires_of_the_same_source() -> None:
    # Règle vérifiée : cahier, règle de câblage n°3 (fan-out illimité) : retirer un
    # consommateur inutile ne touche pas les autres câbles de la même source.
    circuit = gate(1, build_not)
    add_not(circuit, circuit.inputs()[0])  # un consommateur mort de la même entrée
    assert remove_useless_nodes(circuit).wires() == gate(1, build_not).wires()
