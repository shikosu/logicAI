"""Tests des nœuds composants, de la copie et du rechargement d'un circuit."""

from collections.abc import Callable

import pytest

from builders import add_nand, wire
from logicai.circuit import Circuit, Node, NodeKind, Pin, Wire
from logicai.errors import (
    InvalidNodeError,
    SinkAlreadyConnectedError,
    UnknownNodeError,
    UnknownPinError,
    WrongPinKindError,
)


def _snapshot(circuit: Circuit) -> tuple[tuple[Node, ...], tuple[Wire, ...]]:
    """Photographie les nœuds et les câbles, pour prouver que rien n'a changé."""
    return circuit.nodes(), circuit.wires()


# --- Pose d'un composant -------------------------------------------------------


def test_component_node_keeps_its_name_and_pin_counts() -> None:
    # Règle vérifiée : cahier, « Les éléments » (un composant a n puits et m sources).
    circuit = Circuit()
    node = circuit.node(circuit.add_component_node("XOR", 2, 1))
    assert node.kind is NodeKind.COMPONENT
    assert node.component_ref == "XOR"
    assert (node.sink_count, node.source_count) == (2, 1)


def test_component_ids_share_the_counter_of_other_nodes() -> None:
    # Règle vérifiée : prompt phase 1, section A (identifiant unique, jamais réutilisé).
    circuit = Circuit()
    nand_id = circuit.add_node(NodeKind.NAND)
    component_id = circuit.add_component_node("NOT", 1, 1)
    circuit.remove_node(component_id)
    next_id = circuit.add_node(NodeKind.NAND)
    assert len({nand_id, component_id, next_id}) == 3


def test_add_node_refuses_a_component() -> None:
    # Règle vérifiée : cahier, « Composants et bibliothèque » (un composant est posé
    # par référence : il faut son nom et ses broches).
    circuit = Circuit()
    with pytest.raises(InvalidNodeError):
        circuit.add_node(NodeKind.COMPONENT)
    assert circuit.nodes() == ()


@pytest.mark.parametrize(
    ("ref", "sinks", "sources"),
    [("", 2, 1), ("XOR", -1, 1), ("XOR", 2, -1)],
    ids=["nom-vide", "puits-negatif", "source-negative"],
)
def test_invalid_component_is_refused_and_changes_nothing(
    ref: str, sinks: int, sources: int
) -> None:
    # Règle vérifiée : CLAUDE.md (une opération refusée laisse l'objet inchangé).
    circuit = Circuit()
    with pytest.raises(InvalidNodeError):
        circuit.add_component_node(ref, sinks, sources)
    assert circuit.nodes() == ()
    assert circuit.add_node(NodeKind.NAND) == 0  # aucun identifiant n'a été consommé


@pytest.mark.parametrize(
    "build_node",
    [
        pytest.param(lambda: Node(0, NodeKind.NAND, 3, 1), id="nand-3-puits"),
        pytest.param(lambda: Node(0, NodeKind.INPUT, 0, 1, "XOR"), id="input-avec-nom"),
        pytest.param(
            lambda: Node(0, NodeKind.COMPONENT, 1, 1), id="composant-sans-nom"
        ),
        pytest.param(lambda: Node(-1, NodeKind.NAND, 2, 1), id="identifiant-negatif"),
    ],
)
def test_inconsistent_node_cannot_exist(build_node: Callable[[], Node]) -> None:
    # Règle vérifiée : prompt phase 1, section A (nombre de broches de chaque type).
    with pytest.raises(InvalidNodeError):
        build_node()


# --- Câblage d'un composant ----------------------------------------------------


def test_component_pins_follow_the_wiring_rules() -> None:
    # Règle vérifiée : cahier, règles de câblage n°1 et n°2 appliquées aux broches
    # d'un composant (2 puits, 1 source).
    circuit = Circuit()
    input_id = circuit.add_node(NodeKind.INPUT)
    component_id = circuit.add_component_node("AND", 2, 1)
    output_id = circuit.add_node(NodeKind.OUTPUT)
    circuit.connect(Pin(input_id, 0), Pin(component_id, 1))  # puits 1 du composant
    circuit.connect(Pin(component_id, 0), Pin(output_id, 0))  # source 0 du composant
    assert len(circuit.wires()) == 2

    before = _snapshot(circuit)
    with pytest.raises(WrongPinKindError):  # l'index 1 n'existe que comme puits
        circuit.connect(Pin(component_id, 1), Pin(output_id, 0))
    with pytest.raises(UnknownPinError):  # l'index 2 n'existe nulle part
        circuit.connect(Pin(input_id, 0), Pin(component_id, 2))
    assert _snapshot(circuit) == before


def test_removing_a_component_removes_its_wires() -> None:
    # Règle vérifiée : prompt phase 1, section A (supprimer un nœud supprime
    # aussi ses câbles).
    circuit = Circuit()
    input_id = circuit.add_node(NodeKind.INPUT)
    component_id = circuit.add_component_node("NOT", 1, 1)
    output_id = circuit.add_node(NodeKind.OUTPUT)
    circuit.connect(Pin(input_id, 0), Pin(component_id, 0))
    circuit.connect(Pin(component_id, 0), Pin(output_id, 0))
    circuit.remove_node(component_id)
    assert circuit.wires() == ()


def test_components_do_not_count_as_inputs_outputs_or_nands() -> None:
    # Règle vérifiée : prompt phase 1, section B (T_max = nombre de NAND directs ;
    # l'aplatissement compte les NAND des composants).
    circuit = Circuit()
    circuit.add_component_node("XOR", 2, 1)
    assert circuit.inputs() == ()
    assert circuit.outputs() == ()
    assert circuit.nand_count() == 0


# --- Copie et rechargement -----------------------------------------------------


def _small_circuit() -> Circuit:
    """Un circuit avec un trou dans les identifiants et un composant."""
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    removed = circuit.add_node(NodeKind.NAND)
    nand_id = add_nand(circuit, input_a, input_a)
    component_id = circuit.add_component_node("NOT", 1, 1)
    wire(circuit, nand_id, component_id)
    wire(circuit, component_id, circuit.add_node(NodeKind.OUTPUT))
    circuit.remove_node(removed)
    return circuit


def test_copy_is_equal_then_independent() -> None:
    # Règle vérifiée : CLAUDE.md (pas d'état partagé caché) ; copie utilisée par le
    # nettoyage pour ne pas modifier le circuit d'origine.
    original = _small_circuit()
    clone = original.copy()
    assert _snapshot(clone) == _snapshot(original)

    before = _snapshot(original)
    clone.remove_node(clone.inputs()[0])
    clone.add_node(NodeKind.NAND)
    assert _snapshot(original) == before

    snapshot_clone = _snapshot(clone)
    original.add_node(NodeKind.NAND)
    assert _snapshot(clone) == snapshot_clone


def test_copy_continues_the_id_counter() -> None:
    # Règle vérifiée : prompt phase 1, section A (identifiant jamais réutilisé).
    original = _small_circuit()
    clone = original.copy()
    assert clone.add_node(NodeKind.NAND) == original.add_node(NodeKind.NAND)


def test_from_parts_rebuilds_the_same_circuit() -> None:
    # Règle vérifiée : cahier, « Enregistrement ... sous forme de fichier JSON »
    # (recharger sans changer les identifiants).
    original = _small_circuit()
    rebuilt = Circuit.from_parts(original.nodes(), original.wires())
    assert _snapshot(rebuilt) == _snapshot(original)
    new_id = rebuilt.add_node(NodeKind.NAND)
    assert new_id > max(node.node_id for node in original.nodes())


def test_from_parts_of_nothing_is_an_empty_circuit() -> None:
    # Règle vérifiée : prompt phase 1, section A (un circuit peut être vide).
    empty = Circuit.from_parts([], [])
    assert empty.nodes() == ()
    assert empty.add_node(NodeKind.NAND) == 0


@pytest.mark.parametrize("ids", [(1, 1), (2, 1)], ids=["en-double", "decroissants"])
def test_from_parts_refuses_ids_that_do_not_increase(ids: tuple[int, int]) -> None:
    # Règle vérifiée : prompt phase 1, section A (l'ordre des entrées et sorties est
    # leur ordre de création : les identifiants doivent croître).
    nodes = [Node(ids[0], NodeKind.NAND, 2, 1), Node(ids[1], NodeKind.NAND, 2, 1)]
    with pytest.raises(InvalidNodeError):
        Circuit.from_parts(nodes, [])


def test_from_parts_applies_the_wiring_rules() -> None:
    # Règle vérifiée : cahier, règles de câblage (un câble illégal est refusé,
    # même quand il vient d'un fichier).
    nodes = [Node(0, NodeKind.INPUT, 0, 1), Node(1, NodeKind.NAND, 2, 1)]
    unknown_node = Wire(Pin(0, 0), Pin(7, 0))
    two_wires_on_one_sink = [Wire(Pin(0, 0), Pin(1, 0)), Wire(Pin(1, 0), Pin(1, 0))]
    with pytest.raises(UnknownNodeError):
        Circuit.from_parts(nodes, [unknown_node])
    with pytest.raises(SinkAlreadyConnectedError):
        Circuit.from_parts(nodes, two_wires_on_one_sink)
