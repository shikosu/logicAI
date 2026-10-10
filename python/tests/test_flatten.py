"""Tests de l'aplatissement : composants ouverts en NAND, retards et coût."""

from collections.abc import Callable, Mapping

import pytest

from builders import (
    add_nand,
    add_not,
    and_circuit,
    build_or,
    chain_of_nots,
    gate,
    not_circuit,
    pass_through,
    sr_latch,
    wire,
    xor_circuit,
)
from logicai.behavior import TruthTable, run_sequence, truth_table
from logicai.circuit import Circuit, NodeKind, Pin
from logicai.errors import (
    ComponentCycleError,
    ComponentNestingError,
    ComponentPinMismatchError,
    SimulationError,
    UnknownComponentError,
    WireLoopError,
)
from logicai.flatten import flat_nand_count, flatten
from logicai.simulation import SettleResult, Status, settle

# Masque d'une seule combinaison d'entrées : les signaux valent 0 ou 1.
ONE_COMBINATION = 1

Definitions = Mapping[str, Circuit]


# --- Construction ----------------------------------------------------------------


def _place(circuit: Circuit, definitions: Definitions, ref: str) -> int:
    """Pose un composant dont le nombre de broches vient de sa définition."""
    definition = definitions[ref]
    return circuit.add_component_node(
        ref, len(definition.inputs()), len(definition.outputs())
    )


def _apply(circuit: Circuit, definitions: Definitions, ref: str, *sources: int) -> int:
    """Pose un composant et relie la source 0 de chaque ``sources`` à ses puits."""
    component_id = _place(circuit, definitions, ref)
    for sink_index, source_id in enumerate(sources):
        wire(circuit, source_id, component_id, sink_index)
    return component_id


def _xor_with(nand: Callable[[Circuit, int, int], int]) -> Circuit:
    """XOR de la spec (4 portes), où chaque porte est construite par ``nand``."""
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    input_b = circuit.add_node(NodeKind.INPUT)
    n1 = nand(circuit, input_a, input_b)
    n2 = nand(circuit, input_a, n1)
    n3 = nand(circuit, input_b, n1)
    wire(circuit, nand(circuit, n2, n3), circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _basic_definitions() -> dict[str, Circuit]:
    return {"NOT": not_circuit(), "AND": and_circuit()}


def _snapshot(circuit: Circuit) -> tuple[object, object]:
    return circuit.nodes(), circuit.wires()


def _kinds(circuit: Circuit) -> set[NodeKind]:
    return {node.kind for node in circuit.nodes()}


# --- Le test de la phase 2 du cahier -------------------------------------------


def test_xor_made_of_not_and_and_components_matches_its_flat_version() -> None:
    # Règle vérifiée : cahier, plan de développement, phase 2 (un XOR construit avec
    # des composants NOT et AND donne la même signature que sa version aplatie).
    definitions = _basic_definitions()

    def nand(circuit: Circuit, x: int, y: int) -> int:
        return _apply(
            circuit, definitions, "NOT", _apply(circuit, definitions, "AND", x, y)
        )

    flat = flatten(_xor_with(nand), definitions)
    assert truth_table(flat) == TruthTable(Status.STABLE, (0b0110,))
    assert truth_table(flat) == truth_table(xor_circuit())
    assert _kinds(flat) <= {NodeKind.INPUT, NodeKind.OUTPUT, NodeKind.NAND}
    assert flat.nand_count() == 12  # 4 portes x (AND = 2 NAND + NOT = 1 NAND)


def test_nested_components_are_opened_all_the_way() -> None:
    # Règle vérifiée : cahier, « Simulation d'un composant » (on remplace chaque
    # composant par ses NAND) ; un composant peut en contenir d'autres.
    definitions = _basic_definitions()
    nand2 = Circuit()
    x, y = nand2.add_node(NodeKind.INPUT), nand2.add_node(NodeKind.INPUT)
    and_id = _apply(nand2, definitions, "AND", x, y)
    wire(
        nand2,
        _apply(nand2, definitions, "NOT", and_id),
        nand2.add_node(NodeKind.OUTPUT),
    )
    definitions = {**definitions, "NAND2": nand2}
    definitions = {
        **definitions,
        "XORC": _xor_with(lambda c, a, b: _apply(c, definitions, "NAND2", a, b)),
    }

    top = Circuit()
    a, b = top.add_node(NodeKind.INPUT), top.add_node(NodeKind.INPUT)
    wire(top, _apply(top, definitions, "XORC", a, b), top.add_node(NodeKind.OUTPUT))

    flat = flatten(top, definitions)
    assert truth_table(flat) == TruthTable(Status.STABLE, (0b0110,))
    assert flat.nand_count() == 12


# --- Le coût -------------------------------------------------------------------


def test_cost_counts_nands_after_flattening() -> None:
    # Règle vérifiée : cahier, « Coût » (un XOR de 4 NAND coûte 4, même posé comme
    # un seul bloc).
    definitions = {"XOR": xor_circuit()}
    top = Circuit()
    a, b = top.add_node(NodeKind.INPUT), top.add_node(NodeKind.INPUT)
    wire(top, _apply(top, definitions, "XOR", a, b), top.add_node(NodeKind.OUTPUT))
    assert top.nand_count() == 0
    assert flat_nand_count(top, definitions) == 4


def test_cost_of_a_circuit_without_component_is_its_nand_count() -> None:
    # Règle vérifiée : cahier, « Coût » (on compte les NAND).
    assert flat_nand_count(xor_circuit(), {}) == 4


def test_cost_follows_a_replaced_definition() -> None:
    # Règle vérifiée : cahier, « Simulation d'un composant » (si on remplace la
    # définition d'un composant, tous les circuits qui l'utilisent profitent de la
    # version plus petite).
    top = Circuit()
    a = top.add_node(NodeKind.INPUT)
    wire(
        top, _apply(top, {"F": chain_of_nots(3)}, "F", a), top.add_node(NodeKind.OUTPUT)
    )
    assert flat_nand_count(top, {"F": chain_of_nots(3)}) == 3
    assert flat_nand_count(top, {"F": chain_of_nots(1)}) == 1


# --- Les retards restent exacts ------------------------------------------------


def test_component_keeps_the_delays_of_its_nands() -> None:
    # Règle vérifiée : cahier, « Simulation d'un composant » (on aplatit pour que les
    # retards restent exacts). Une chaîne de 3 NOT en composant se stabilise comme
    # la chaîne posée à plat (4 tops, mêmes états).
    definitions = {"CHAIN3": chain_of_nots(3)}
    top = Circuit()
    a = top.add_node(NodeKind.INPUT)
    wire(top, _apply(top, definitions, "CHAIN3", a), top.add_node(NodeKind.OUTPUT))
    expected = settle(chain_of_nots(3), (0,), ONE_COMBINATION)
    assert expected == SettleResult(Status.STABLE, (1, 0, 1), (1,), 4)
    assert settle(flatten(top, definitions), (0,), ONE_COMBINATION) == expected


@pytest.mark.parametrize(
    "sequence",
    [
        [(0, 1), (1, 1), (1, 0), (1, 1)],  # mémoire : Q = 1, 1, 0, 0
        [(1, 1)],  # métastabilité
        [(1, 1), (0, 1), (1, 1)],  # un pas instable au milieu
    ],
    ids=["memoire", "metastabilite", "pas-instable"],
)
def test_latch_component_behaves_like_the_flat_latch(
    sequence: list[tuple[int, int]],
) -> None:
    # Règle vérifiée : cahier, « Simulation d'un composant » (retards exacts, ce qui
    # compte pour le séquentiel) ; deux sorties d'un composant.
    definitions = {"SR": sr_latch()}
    top = Circuit()
    s_bar, r_bar = top.add_node(NodeKind.INPUT), top.add_node(NodeKind.INPUT)
    latch_id = _apply(top, definitions, "SR", s_bar, r_bar)
    q_out, q_bar_out = top.add_node(NodeKind.OUTPUT), top.add_node(NodeKind.OUTPUT)
    top.connect(Pin(latch_id, 0), Pin(q_out, 0))
    top.connect(Pin(latch_id, 1), Pin(q_bar_out, 0))

    assert run_sequence(flatten(top, definitions), sequence) == run_sequence(
        sr_latch(), sequence
    )


# --- Frontières du composant ---------------------------------------------------


def test_unwired_component_sink_reads_zero_inside() -> None:
    # Règle vérifiée : cahier, règle de câblage n°4 (un puits sans câble vaut 0),
    # appliquée au puits d'un composant : AND(A, 0) = 0.
    definitions = _basic_definitions()
    top = Circuit()
    a = top.add_node(NodeKind.INPUT)
    and_id = _place(top, definitions, "AND")
    wire(top, a, and_id, 0)  # le puits 1 reste libre
    wire(top, and_id, top.add_node(NodeKind.OUTPUT))
    assert truth_table(flatten(top, definitions)) == TruthTable(Status.STABLE, (0b00,))


def test_unwired_component_with_no_input_at_all() -> None:
    # Règle vérifiée : cahier, règle de câblage n°4 : NOT(0) = 1.
    definitions = _basic_definitions()
    top = Circuit()
    wire(top, _place(top, definitions, "NOT"), top.add_node(NodeKind.OUTPUT))
    assert truth_table(flatten(top, definitions)) == TruthTable(Status.STABLE, (0b1,))


def test_unwired_output_inside_a_component_reads_zero_outside() -> None:
    # Règle vérifiée : prompt phase 1, section B (une OUTPUT non reliée vaut 0),
    # vue de l'extérieur : le NOT qui la lit donne 1.
    dead_output = Circuit()
    dead_output.add_node(NodeKind.INPUT)
    dead_output.add_node(NodeKind.OUTPUT)
    definitions = {"DEAD": dead_output, "NOT": not_circuit()}
    top = Circuit()
    a = top.add_node(NodeKind.INPUT)
    dead_id = _apply(top, definitions, "DEAD", a)
    wire(top, _apply(top, definitions, "NOT", dead_id), top.add_node(NodeKind.OUTPUT))
    assert truth_table(flatten(top, definitions)) == TruthTable(Status.STABLE, (0b11,))


def test_pass_through_component_adds_no_delay() -> None:
    # Règle vérifiée : prompt phase 1, section B (une OUTPUT lit sa source sans
    # retard) : un composant qui recopie son entrée est un simple fil.
    definitions = {"WIRE": pass_through()}
    top = Circuit()
    a = top.add_node(NodeKind.INPUT)
    wire(top, _apply(top, definitions, "WIRE", a), top.add_node(NodeKind.OUTPUT))
    flat = flatten(top, definitions)
    assert flat.nand_count() == 0
    assert settle(flat, (1,), ONE_COMBINATION) == SettleResult(
        Status.STABLE, (), (1,), 1
    )


def test_inputs_and_outputs_keep_their_creation_order() -> None:
    # Règle vérifiée : cahier, « Ordre des broches » (entrées et sorties numérotées
    # dans leur ordre de création). Sortie 1 = NOT A (composant), sortie 2 = B.
    definitions = _basic_definitions()
    top = Circuit()
    a, b = top.add_node(NodeKind.INPUT), top.add_node(NodeKind.INPUT)
    wire(top, _apply(top, definitions, "NOT", a), top.add_node(NodeKind.OUTPUT))
    wire(top, b, top.add_node(NodeKind.OUTPUT))
    assert truth_table(flatten(top, definitions)) == TruthTable(
        Status.STABLE, (0b0101, 0b1100)
    )


def test_wire_loop_without_nand_is_refused() -> None:
    # Règle vérifiée : décision du plan (boucle de fils sans NAND : valeur non
    # définie, donc refusée). Un fil rebouclé sur lui-même, directement ou en cercle.
    definitions = {"WIRE": pass_through()}
    alone = Circuit()
    wire_id = _place(alone, definitions, "WIRE")
    wire(alone, wire_id, wire_id)
    wire(alone, wire_id, alone.add_node(NodeKind.OUTPUT))
    with pytest.raises(WireLoopError):
        flatten(alone, definitions)

    ring = Circuit()
    first, second = _place(ring, definitions, "WIRE"), _place(ring, definitions, "WIRE")
    wire(ring, first, second)
    wire(ring, second, first)
    wire(ring, first, ring.add_node(NodeKind.OUTPUT))
    with pytest.raises(WireLoopError):
        flatten(ring, definitions)


def test_loop_through_a_nand_is_fine() -> None:
    # Règle vérifiée : cahier, règle de câblage n°5 (les boucles sont autorisées) :
    # une boucle qui passe par un composant ET une NAND a une valeur définie.
    definitions = {"WIRE": pass_through()}
    top = Circuit()
    nand_id = top.add_node(NodeKind.NAND)
    wire_id = _apply(top, definitions, "WIRE", nand_id)
    wire(top, wire_id, nand_id, 0)
    wire(top, wire_id, nand_id, 1)
    wire(top, nand_id, top.add_node(NodeKind.OUTPUT))
    flat = flatten(top, definitions)
    assert flat.nand_count() == 1
    assert truth_table(flat).status is Status.UNSTABLE  # un NOT rebouclé oscille


# --- Définitions invalides -----------------------------------------------------


def test_unknown_component_is_refused() -> None:
    # Règle vérifiée : cahier, « Les composants sont rangés par référence » (une
    # référence sans définition est une erreur).
    top = Circuit()
    top.add_component_node("MYSTERE", 1, 1)
    with pytest.raises(UnknownComponentError):
        flatten(top, {})


def test_wrong_pin_count_is_refused() -> None:
    # Règle vérifiée : cahier, « Ordre des broches » (le nœud doit avoir autant de
    # broches que la définition a d'entrées et de sorties).
    top = Circuit()
    top.add_component_node("NOT", 2, 1)
    with pytest.raises(ComponentPinMismatchError):
        flatten(top, {"NOT": not_circuit()})


def test_component_containing_itself_is_refused() -> None:
    # Règle vérifiée : cahier, « Simulation d'un composant » (aplatir doit se terminer :
    # un composant ne peut pas se contenir lui-même, ni par un autre composant).
    selfish = Circuit()
    selfish.add_node(NodeKind.INPUT)
    selfish.add_node(NodeKind.OUTPUT)
    selfish.add_component_node("A", 1, 1)
    top = Circuit()
    top.add_component_node("A", 1, 1)
    with pytest.raises(ComponentCycleError):
        flatten(top, {"A": selfish})

    circle_a, circle_b = Circuit(), Circuit()
    circle_a.add_component_node("B", 0, 0)
    circle_b.add_component_node("A", 0, 0)
    start = Circuit()
    start.add_component_node("A", 0, 0)
    with pytest.raises(ComponentCycleError):
        flatten(start, {"A": circle_a, "B": circle_b})


# --- Propriétés générales ------------------------------------------------------


def test_circuit_without_component_keeps_its_behavior() -> None:
    # Règle vérifiée : cahier, « Simulation d'un composant » (aplatir ne change pas
    # un circuit qui n'a pas de composant).
    for circuit in (xor_circuit(), gate(2, build_or), sr_latch()):
        flat = flatten(circuit, {})
        assert flat.nand_count() == circuit.nand_count()
        assert len(flat.inputs()) == len(circuit.inputs())
        assert truth_table(flat) == truth_table(circuit)


def test_flatten_does_not_modify_its_arguments() -> None:
    # Règle vérifiée : CLAUDE.md (pas d'état caché : une opération n'abîme pas
    # les données qu'on lui donne).
    definitions = _basic_definitions()
    top = Circuit()
    a = top.add_node(NodeKind.INPUT)
    wire(top, _apply(top, definitions, "NOT", a), top.add_node(NodeKind.OUTPUT))
    before = (_snapshot(top), {name: _snapshot(c) for name, c in definitions.items()})
    flatten(top, definitions)
    assert (_snapshot(top), {n: _snapshot(c) for n, c in definitions.items()}) == before


def test_deeply_nested_components() -> None:
    # Règle vérifiée : cahier, « Composants et bibliothèque » (l'IA réutilise ses
    # propres composants, donc l'imbrication peut devenir profonde). Chaque niveau
    # ajoute un NOT : 151 NOT en tout, donc un NOT.
    depth = 150
    definitions: dict[str, Circuit] = {"L0": not_circuit()}
    for level in range(1, depth + 1):
        circuit = Circuit()
        inner = _apply(
            circuit, definitions, f"L{level - 1}", circuit.add_node(NodeKind.INPUT)
        )
        wire(circuit, add_not(circuit, inner), circuit.add_node(NodeKind.OUTPUT))
        definitions[f"L{level}"] = circuit

    top = Circuit()
    a = top.add_node(NodeKind.INPUT)
    wire(top, _apply(top, definitions, f"L{depth}", a), top.add_node(NodeKind.OUTPUT))
    flat = flatten(top, definitions)
    assert flat.nand_count() == depth + 1
    assert truth_table(flat) == TruthTable(Status.STABLE, (0b01,))


def test_nesting_too_deep_is_refused_cleanly() -> None:
    # Règle vérifiée : CLAUDE.md (un refus dédié et clair plutôt qu'un plantage). Python
    # n'a pas assez de pile pour 2000 niveaux : l'aplatissement doit le dire.
    depth = 2000
    definitions: dict[str, Circuit] = {"L0": not_circuit()}
    for level in range(1, depth + 1):
        circuit = Circuit()
        inner = _apply(
            circuit, definitions, f"L{level - 1}", circuit.add_node(NodeKind.INPUT)
        )
        wire(circuit, inner, circuit.add_node(NodeKind.OUTPUT))
        definitions[f"L{level}"] = circuit

    top = Circuit()
    a = top.add_node(NodeKind.INPUT)
    wire(top, _apply(top, definitions, f"L{depth}", a), top.add_node(NodeKind.OUTPUT))
    with pytest.raises(ComponentNestingError):
        flatten(top, definitions)


def test_fan_out_of_a_component_output() -> None:
    # Règle vérifiée : cahier, règle de câblage n°3 (une source alimente autant de
    # puits que voulu), appliquée à la sortie d'un composant : (NOT A) NAND (NOT A).
    definitions = _basic_definitions()
    top = Circuit()
    a = top.add_node(NodeKind.INPUT)
    not_id = _apply(top, definitions, "NOT", a)
    wire(top, add_nand(top, not_id, not_id), top.add_node(NodeKind.OUTPUT))
    assert truth_table(flatten(top, definitions)) == TruthTable(Status.STABLE, (0b10,))


# --- La simulation exige un circuit aplati -------------------------------------


def test_simulation_refuses_a_circuit_that_still_has_components() -> None:
    # Règle vérifiée : cahier, « Simulation d'un composant » (pour simuler, on
    # aplatit) ;
    # le moteur refuse plutôt que d'ignorer un composant en silence.
    definitions = _basic_definitions()
    top = Circuit()
    a = top.add_node(NodeKind.INPUT)
    wire(top, _apply(top, definitions, "NOT", a), top.add_node(NodeKind.OUTPUT))
    with pytest.raises(SimulationError):
        settle(top, (0,), ONE_COMBINATION)
    with pytest.raises(SimulationError):
        truth_table(top)

    # Même un composant que personne ne lit n'est pas ignoré en silence.
    unread = Circuit()
    unread.add_component_node("NOT", 1, 1)
    with pytest.raises(SimulationError):
        settle(unread, (), ONE_COMBINATION)
    assert truth_table(flatten(top, definitions)) == TruthTable(Status.STABLE, (0b01,))
