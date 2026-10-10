"""Tests du placement des nœuds : colonnes, lignes, boucles, chevauchements."""

import random
from collections.abc import Callable

import pytest

from builders import (
    add_not,
    chain_of_nots,
    not_circuit,
    pass_through,
    sr_latch,
    wire,
    xor_circuit,
)
from logicai.circuit import Circuit, Node, NodeKind, Pin
from logicai.layout import (
    COLUMN_SPACING,
    ROW_GAP,
    Position,
    box_height,
    compute_layout,
)

SEED = 20261011  # graine fixe : les circuits tirés au hasard sont reproductibles


def _x_of(circuit: Circuit) -> dict[int, int]:
    return {node_id: p.x for node_id, p in compute_layout(circuit).items()}


def _assert_no_overlap(circuit: Circuit) -> None:
    """Vérifie que deux boîtes d'une même colonne gardent ROW_GAP entre elles."""
    positions = compute_layout(circuit)
    heights = {node.node_id: box_height(node) for node in circuit.nodes()}
    by_column: dict[int, list[int]] = {}
    for node_id, position in positions.items():
        by_column.setdefault(position.x, []).append(node_id)
    for members in by_column.values():
        members.sort(key=lambda node_id: -positions[node_id].y)
        for upper, lower in zip(members, members[1:], strict=False):
            needed = (heights[upper] + heights[lower]) // 2 + ROW_GAP
            assert positions[upper].y - positions[lower].y >= needed


# --- L'exemple du cahier --------------------------------------------------------------


def test_not_circuit_is_placed_like_the_cahiers_example() -> None:
    # Règle vérifiée : cahier, « Exemple de circuit en JSON » (NOT : entrée en x = 0,
    # NAND en x = 2, sortie en x = 4, tous en y = 0).
    assert compute_layout(not_circuit()) == {
        0: Position(0, 0),
        1: Position(2, 0),
        2: Position(4, 0),
    }


# --- Colonnes -------------------------------------------------------------------------


def test_columns_follow_the_longest_path_from_the_inputs() -> None:
    # Règle vérifiée : décision du plan (x = 2 x couche, couche = plus long chemin).
    # XOR : n1 en couche 1, n2 et n3 en couche 2, n4 en couche 3, sortie en couche 4.
    assert _x_of(xor_circuit()) == {0: 0, 1: 0, 2: 2, 3: 4, 4: 4, 5: 6, 6: 8}


def test_inputs_are_first_and_outputs_are_in_the_last_column() -> None:
    # Règle vérifiée : décision du plan (entrées à gauche, sorties dans la dernière
    # colonne), y compris quand une sortie est reliée tôt dans le circuit.
    circuit = Circuit()
    a = circuit.add_node(NodeKind.INPUT)
    wire(circuit, a, circuit.add_node(NodeKind.OUTPUT))  # sortie directe
    wire(
        circuit,
        add_not(circuit, add_not(circuit, a)),
        circuit.add_node(NodeKind.OUTPUT),
    )
    x = _x_of(circuit)
    last = max(x.values())
    assert x[a] == 0
    assert [x[node_id] for node_id in circuit.outputs()] == [last, last]
    assert all(
        x[node.node_id] < last
        for node in circuit.nodes()
        if node.kind is not NodeKind.OUTPUT
    )


def test_input_wired_straight_to_an_output() -> None:
    # Règle vérifiée : décision du plan (sorties dans la dernière colonne, même sans
    # NAND).
    assert _x_of(pass_through()) == {0: 0, 1: 2}


def test_gate_without_any_incoming_wire_is_right_of_the_inputs() -> None:
    # Règle vérifiée : cahier, règle de câblage n°4 (une NAND sans câble fournit un 1
    # constant) : elle n'a pas de source, mais elle n'est pas une entrée.
    circuit = Circuit()
    wire(circuit, circuit.add_node(NodeKind.NAND), circuit.add_node(NodeKind.OUTPUT))
    assert _x_of(circuit) == {0: COLUMN_SPACING, 1: 2 * COLUMN_SPACING}


# --- Boucles --------------------------------------------------------------------------


def test_gate_looped_on_itself_still_has_a_column() -> None:
    # Règle vérifiée : cahier, règle de câblage n°5 (boucle d'une NAND sur elle-même).
    circuit = Circuit()
    nand_id = circuit.add_node(NodeKind.NAND)
    wire(circuit, nand_id, nand_id, 0)
    wire(circuit, nand_id, nand_id, 1)
    wire(circuit, nand_id, circuit.add_node(NodeKind.OUTPUT))
    assert _x_of(circuit) == {0: 2, 1: 4}


def test_feedback_wire_is_ignored_to_find_the_columns() -> None:
    # Règle vérifiée : décision du plan (les boucles ne comptent pas pour les couches).
    # Bascule SR : le câble de Q̄ vers Q revient en arrière, donc Q est en couche 1,
    # Q̄ en couche 2 et les deux sorties en couche 3.
    assert _x_of(sr_latch()) == {0: 0, 1: 0, 2: 2, 3: 4, 4: 6, 5: 6}


# --- Lignes ---------------------------------------------------------------------------


def test_first_input_is_at_the_top() -> None:
    # Règle vérifiée : décision du plan (première entrée en haut ; y vers le haut).
    layout = compute_layout(xor_circuit())
    assert layout[0].y > layout[1].y


def test_rows_follow_the_height_of_their_sources_to_avoid_crossings() -> None:
    # Règle vérifiée : décision du plan (ordre des lignes selon la hauteur moyenne des
    # sources). La 1re sortie lit le NOT du bas, la 2e celui du haut : la 2e est
    # au-dessus.
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    not_a, not_b = add_not(circuit, a), add_not(circuit, b)
    first_output = circuit.add_node(NodeKind.OUTPUT)
    second_output = circuit.add_node(NodeKind.OUTPUT)
    wire(circuit, not_b, first_output)
    wire(circuit, not_a, second_output)
    layout = compute_layout(circuit)
    assert layout[not_a].y > layout[not_b].y
    assert layout[second_output].y > layout[first_output].y


def test_a_column_is_centered_on_zero() -> None:
    # Règle vérifiée : décision du plan (colonnes centrées sur y = 0 ; centres entiers).
    layout = compute_layout(xor_circuit())
    assert (layout[3].y, layout[4].y) == (2, -2)  # n2 et n3, dans la couche 2


# --- Hauteur des boîtes ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("make_node", "expected"),
    [
        pytest.param(lambda: Node.fixed(0, NodeKind.NAND), 2, id="NAND"),
        pytest.param(lambda: Node.fixed(0, NodeKind.INPUT), 2, id="entree"),
        pytest.param(
            lambda: Node(0, NodeKind.COMPONENT, 0, 0, "X"), 2, id="composant-0-0"
        ),
        pytest.param(
            lambda: Node(0, NodeKind.COMPONENT, 3, 1, "X"), 4, id="composant-3-1"
        ),
        pytest.param(
            lambda: Node(0, NodeKind.COMPONENT, 1, 5, "X"), 6, id="composant-1-5"
        ),
        pytest.param(
            lambda: Node(0, NodeKind.COMPONENT, 4, 4, "X"), 4, id="composant-4-4"
        ),
    ],
)
def test_box_height_is_the_pin_count_rounded_up_to_an_even_number(
    make_node: Callable[[], Node], expected: int
) -> None:
    # Règle vérifiée : décision du plan (une boîte fait max(2, broches) unités, au
    # pair).
    assert box_height(make_node()) == expected


def test_tall_components_keep_their_neighbours_away() -> None:
    # Règle vérifiée : décision du plan (une boîte plus haute ne chevauche pas sa
    # voisine).
    circuit = Circuit()
    inputs = [circuit.add_node(NodeKind.INPUT) for _ in range(3)]
    tall = circuit.add_component_node("GROS", 5, 1)
    for index, source in enumerate(inputs):
        wire(circuit, source, tall, index)
    small = add_not(circuit, inputs[0])
    wire(circuit, tall, circuit.add_node(NodeKind.OUTPUT))
    wire(circuit, small, circuit.add_node(NodeKind.OUTPUT))
    _assert_no_overlap(circuit)
    assert compute_layout(circuit)[tall].x == compute_layout(circuit)[small].x


# --- Propriétés générales -------------------------------------------------------------


def _random_circuit(rng: random.Random) -> Circuit:
    """Un circuit au hasard, avec des boucles, des fan-out et des câbles manquants."""
    circuit = Circuit()
    inputs = [circuit.add_node(NodeKind.INPUT) for _ in range(rng.randint(0, 4))]
    nands = [circuit.add_node(NodeKind.NAND) for _ in range(rng.randint(0, 12))]
    outputs = [circuit.add_node(NodeKind.OUTPUT) for _ in range(rng.randint(0, 4))]
    sources = inputs + nands
    if not sources:
        return circuit
    for nand_id in nands:
        for sink_index in (0, 1):
            if rng.random() < 0.85:
                circuit.connect(Pin(rng.choice(sources), 0), Pin(nand_id, sink_index))
    for output_id in outputs:
        if rng.random() < 0.9:
            circuit.connect(Pin(rng.choice(sources), 0), Pin(output_id, 0))
    return circuit


def test_random_circuits_are_placed_without_overlap() -> None:
    # Règle vérifiée : décision du plan, sur 300 circuits au hasard (graine fixe), avec
    # boucles : tous les nœuds sont placés, jamais deux au même endroit, jamais de
    # chevauchement dans une colonne, entrées à gauche, sorties dans la dernière
    # colonne.
    rng = random.Random(SEED)
    for _ in range(300):
        circuit = _random_circuit(rng)
        layout = compute_layout(circuit)
        assert list(layout) == [node.node_id for node in circuit.nodes()]
        assert len({(p.x, p.y) for p in layout.values()}) == len(layout)
        _assert_no_overlap(circuit)
        for node in circuit.nodes():
            position = layout[node.node_id]
            assert position.x % COLUMN_SPACING == 0
            if node.kind is NodeKind.INPUT:
                assert position.x == 0
        outputs_x = {layout[node_id].x for node_id in circuit.outputs()}
        others_x = [
            layout[n.node_id].x
            for n in circuit.nodes()
            if n.kind is not NodeKind.OUTPUT
        ]
        assert len(outputs_x) <= 1
        for output_x in outputs_x:
            assert all(x < output_x for x in others_x)


def test_layout_is_deterministic() -> None:
    # Règle vérifiée : décision du plan (résultat déterministe : mêmes fichiers à
    # chaque exécution).
    circuit = _random_circuit(random.Random(SEED + 1))
    assert compute_layout(circuit) == compute_layout(circuit.copy())


def test_empty_circuit_and_lone_input() -> None:
    # Règle vérifiée : prompt phase 1, section A (un circuit peut être vide).
    assert compute_layout(Circuit()) == {}
    lone = Circuit()
    lone.add_node(NodeKind.INPUT)
    assert compute_layout(lone) == {0: Position(0, 0)}


def test_very_long_chain_does_not_overflow_the_stack() -> None:
    # Règle vérifiée : cahier, « Taille maximale » (aucune limite fixe de taille) : le
    # placement n'est pas récursif. 3000 NOT en chaîne : sortie en couche 3001.
    length = 3000
    layout = compute_layout(chain_of_nots(length))
    output_id = max(layout)
    assert layout[output_id].x == COLUMN_SPACING * (length + 1)


def test_wide_column_does_not_overflow() -> None:
    # Règle vérifiée : cahier, « Taille maximale » : une colonne de 200 portes.
    circuit = Circuit()
    source = circuit.add_node(NodeKind.INPUT)
    for _ in range(200):
        add_not(circuit, source)
    _assert_no_overlap(circuit)
