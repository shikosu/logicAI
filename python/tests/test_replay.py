"""Tests de l'ordre de pose (cahier, « IA 1 » : rediffusion reconstituée)."""

import random
from collections import Counter

import pytest

from builders import (
    build_and,
    build_mux,
    build_xor,
    gate,
    not_circuit,
    random_circuit,
    sr_latch,
    wire,
    xor_circuit,
)
from logicai.behavior import truth_table
from logicai.circuit import Circuit, NodeKind
from logicai.errors import InvalidPlacementError, LibraryFormatError
from logicai.library import Library
from logicai.replay import (
    POSE_ACTION,
    WIRE_ACTION,
    circuit_from_placement,
    placement_order,
)
from logicai.serialization import circuit_to_dict


def _snapshot(circuit: Circuit) -> tuple[object, object]:
    return circuit.nodes(), circuit.wires()


def _same_circuit(left: Circuit, right: Circuit) -> bool:
    """Mêmes nœuds (mêmes identifiants) et mêmes câbles, dans n'importe quel ordre."""
    return left.nodes() == right.nodes() and set(left.wires()) == set(right.wires())


def _with_component() -> Circuit:
    """Un circuit qui pose le composant XOR de la bibliothèque."""
    library = Library()
    library.register(xor_circuit())
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    node = library.instantiate(circuit, "XOR")
    wire(circuit, a, node, 0)
    wire(circuit, b, node, 1)
    wire(circuit, node, circuit.add_node(NodeKind.OUTPUT))
    return circuit


ACYCLIC = {
    "NOT": not_circuit(),
    "AND": gate(2, build_and),
    "XOR": gate(2, build_xor),
    "MUX": gate(3, build_mux),
    "composant": _with_component(),
}
WITH_LOOPS = {"bascule SR": sr_latch()}


# --- L'exemple du cahier -----------------------------------------------------


def test_not_circuit_order_matches_the_cahier_example() -> None:
    # Règle : cahier : « les nœuds dans l'ordre des signaux, puis les câbles ». Le
    # NOT du cahier : entrée (0, 0), NAND (2, 0), sortie (4, 0), puis ses 3 câbles dans
    # l'ordre des puits : NAND broche 0, NAND broche 1, sortie.
    steps = placement_order(not_circuit())
    assert steps == (
        {"action": POSE_ACTION, "noeud": {"id": 0, "type": "ENTREE", "x": 0, "y": 0}},
        {"action": POSE_ACTION, "noeud": {"id": 1, "type": "NAND", "x": 2, "y": 0}},
        {"action": POSE_ACTION, "noeud": {"id": 2, "type": "SORTIE", "x": 4, "y": 0}},
        {"action": WIRE_ACTION, "de": [0, 0], "vers": [1, 0]},
        {"action": WIRE_ACTION, "de": [0, 0], "vers": [1, 1]},
        {"action": WIRE_ACTION, "de": [1, 0], "vers": [2, 0]},
    )


def test_empty_circuit_has_no_steps() -> None:
    # Règle : rien à poser, rien à rejouer.
    assert placement_order(Circuit()) == ()
    assert circuit_from_placement(()).nodes() == ()


# --- Propriétés de l'ordre ---------------------------------------------------


@pytest.mark.parametrize("name", [*ACYCLIC, *WITH_LOOPS])
def test_nodes_come_first_then_wires_and_each_once(name: str) -> None:
    # Règle : « les nœuds ..., puis les câbles » : toutes les poses avant tous les
    # câblages ; chaque nœud et chaque câble du circuit apparaît exactement une fois.
    circuit = {**ACYCLIC, **WITH_LOOPS}[name]
    steps = placement_order(circuit)
    actions = [step["action"] for step in steps]
    first_wire = actions.index(WIRE_ACTION)
    assert set(actions[:first_wire]) == {POSE_ACTION}
    assert set(actions[first_wire:]) == {WIRE_ACTION}
    poses = [step["noeud"]["id"] for step in steps if step["action"] == POSE_ACTION]
    assert sorted(poses) == sorted(node.node_id for node in circuit.nodes())
    wires = Counter((tuple(s["de"]), tuple(s["vers"])) for s in steps[first_wire:])
    assert wires == Counter(
        ((w.source.node_id, w.source.index), (w.sink.node_id, w.sink.index))
        for w in circuit.wires()
    )


@pytest.mark.parametrize("name", list(ACYCLIC))
def test_signals_come_before_what_they_feed(name: str) -> None:
    # Règle : « dans l'ordre des signaux » : dans un circuit sans boucle, un nœud est
    # posé après tous ceux qui l'alimentent.
    circuit = ACYCLIC[name]
    steps = placement_order(circuit)
    rank = {
        step["noeud"]["id"]: position
        for position, step in enumerate(s for s in steps if s["action"] == POSE_ACTION)
    }
    for w in circuit.wires():
        assert rank[w.source.node_id] < rank[w.sink.node_id]


def test_wires_follow_their_sink_order() -> None:
    # Règle : les câbles sont rangés selon la pose de leur nœud d'arrivée, puis le
    # numéro de la broche. Pour un XOR, la suite des puits ne revient jamais en arrière.
    steps = placement_order(gate(2, build_xor))
    poses = [s["noeud"]["id"] for s in steps if s["action"] == POSE_ACTION]
    rank = {node_id: position for position, node_id in enumerate(poses)}
    sinks = [
        (rank[s["vers"][0]], s["vers"][1]) for s in steps if s["action"] == WIRE_ACTION
    ]
    assert sinks == sorted(sinks)


def test_wires_to_the_same_node_follow_the_pin_number() -> None:
    # Règle : sur un même nœud d'arrivée, les câbles suivent le numéro de la broche,
    # même si l'IA a câblé la broche 1 avant la broche 0.
    circuit = Circuit()
    source = circuit.add_node(NodeKind.INPUT)
    nand = circuit.add_node(NodeKind.NAND)
    wire(circuit, source, nand, 1)  # broche 1 d'abord
    wire(circuit, source, nand, 0)
    wire(circuit, nand, circuit.add_node(NodeKind.OUTPUT))
    sinks = [
        tuple(step["vers"])
        for step in placement_order(circuit)
        if step["action"] == WIRE_ACTION
    ]
    assert sinks == [(nand, 0), (nand, 1), (2, 0)]


def test_node_steps_are_the_nodes_of_the_circuit_file() -> None:
    # Règle : les nœuds sont écrits comme dans un fichier de circuit, positions x et y
    # comprises : Unity ne calcule rien (« Python calcule, Unity ne fait que du front
    # end »).
    circuit = _with_component()
    file_nodes = {n["id"]: n for n in circuit_to_dict("X", circuit)["noeuds"]}
    steps = placement_order(circuit)
    for step in steps:
        if step["action"] == POSE_ACTION:
            assert step["noeud"] == file_nodes[step["noeud"]["id"]]
    assert any(
        n.get("type") == "COMPOSANT" and n["ref"] == "XOR" for n in file_nodes.values()
    )


def test_order_is_deterministic_and_does_not_change_the_circuit() -> None:
    # Règle : même circuit, même ordre ; le circuit donné n'est pas modifié.
    circuit = gate(3, build_mux)
    before = _snapshot(circuit)
    assert placement_order(circuit) == placement_order(circuit)
    assert _snapshot(circuit) == before


# --- Rejouer l'ordre : on retrouve le circuit --------------------------------


@pytest.mark.parametrize("name", [*ACYCLIC, *WITH_LOOPS])
def test_replaying_the_order_rebuilds_the_circuit(name: str) -> None:
    # Règle (test principal) : rejouer l'ordre de pose sur un circuit vide redonne
    # exactement le circuit de départ (mêmes nœuds et identifiants, mêmes câbles).
    circuit = {**ACYCLIC, **WITH_LOOPS}[name]
    rebuilt = circuit_from_placement(placement_order(circuit))
    assert _same_circuit(rebuilt, circuit)


def test_replay_keeps_the_behavior() -> None:
    # Règle : le circuit rejoué se comporte pareil (même table de vérité).
    for circuit in (not_circuit(), gate(2, build_xor), gate(3, build_mux)):
        rebuilt = circuit_from_placement(placement_order(circuit))
        assert truth_table(rebuilt) == truth_table(circuit)


@pytest.mark.parametrize("seed", range(40))
def test_random_circuits_are_rebuilt(seed: int) -> None:
    # Règle : même propriété sur des circuits au hasard (avec boucles, fan-out, câbles
    # manquants), générés avec une graine fixe.
    circuit = random_circuit(random.Random(seed))
    rebuilt = circuit_from_placement(placement_order(circuit))
    assert _same_circuit(rebuilt, circuit)


def test_every_prefix_is_a_legal_circuit_that_grows_by_one_piece() -> None:
    # Règle : la rediffusion montre le circuit pièce par pièce : après k étapes on a
    # un circuit légal, avec une pièce de plus à chaque étape (Unity le redessine).
    circuit = gate(2, build_xor)
    steps = placement_order(circuit)
    previous = 0
    for count in range(len(steps) + 1):
        partial = circuit_from_placement(steps, count)
        pieces = len(partial.nodes()) + len(partial.wires())
        assert pieces == count
        assert pieces >= previous
        previous = pieces
    assert _same_circuit(circuit_from_placement(steps, len(steps)), circuit)


def test_count_larger_than_the_order_means_everything() -> None:
    # Règle : un nombre d'étapes trop grand rejoue tout, sans erreur.
    steps = placement_order(not_circuit())
    assert _same_circuit(circuit_from_placement(steps, 999), not_circuit())


# --- Ordres incohérents refusés ----------------------------------------------


def test_wire_before_its_node_is_refused() -> None:
    # Règle : « les nœuds ..., puis les câbles » : un câble avant la pose de l'un de ses
    # nœuds est refusé (erreur dédiée).
    steps = placement_order(not_circuit())
    swapped = [steps[0], steps[3], steps[1]]  # câble 0 -> 1 avant la pose du nœud 1
    with pytest.raises(InvalidPlacementError, match="pas encore posé"):
        circuit_from_placement(swapped)


@pytest.mark.parametrize(
    "bad",
    [
        {"action": "retirer"},
        {"action": POSE_ACTION},
        {"action": POSE_ACTION, "noeud": {"id": True, "type": "NAND"}},
        {"action": WIRE_ACTION, "de": [0], "vers": [1, 0]},
        {"action": WIRE_ACTION, "de": [0, 0]},
        {},
    ],
    ids=[
        "action inconnue",
        "nœud absent",
        "id booléen",
        "broche courte",
        "vers absent",
        "vide",
    ],
)
def test_malformed_steps_are_refused(bad: dict[str, object]) -> None:
    # Règle : erreurs dédiées avec un message qui dit ce qui est refusé.
    poses = placement_order(not_circuit())[:3]  # les 3 nœuds sont posés
    steps = [*poses, bad]
    with pytest.raises(InvalidPlacementError):
        circuit_from_placement(steps)


def test_negative_count_is_refused() -> None:
    # Règle : un nombre d'étapes négatif n'a pas de sens.
    with pytest.raises(InvalidPlacementError):
        circuit_from_placement(placement_order(not_circuit()), -1)


def test_circuit_rules_still_apply_when_replaying() -> None:
    # Règles de câblage 2 : un puits reçoit au plus un câble. Un câble posé deux fois
    # est refusé par les règles du circuit (erreur du format de fichier).
    steps = list(placement_order(not_circuit()))
    steps.append(steps[-1])
    with pytest.raises(LibraryFormatError, match="un seul câble"):
        circuit_from_placement(steps)


def test_a_node_posed_twice_is_refused() -> None:
    # Règle : un identifiant de nœud est unique.
    steps = list(placement_order(not_circuit()))
    with pytest.raises(LibraryFormatError):
        circuit_from_placement([steps[0], steps[0]])
