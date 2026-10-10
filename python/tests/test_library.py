"""Tests de la bibliothèque : enregistrer, nommer, remplacer, limites."""

import itertools

import pytest

from builders import (
    add_nand,
    add_not,
    bloated,
    build_and,
    build_and_not,
    build_mux,
    build_mux_rotated,
    build_mux_with_roles,
    build_not,
    build_not_and,
    build_xor,
    gate,
    not_circuit,
    wire,
    xor_circuit,
)
from logicai.behavior import TruthTable, truth_table
from logicai.circuit import Circuit, NodeKind
from logicai.errors import (
    ComponentTooLargeError,
    InvalidLimitsError,
    NoOutputError,
    UnknownComponentError,
    UnknownComponentNameError,
    UnstableCircuitError,
)
from logicai.flatten import flatten
from logicai.library import (
    DEFAULT_MAX_INPUTS,
    DEFAULT_MAX_OUTPUTS,
    Library,
    LibraryLimits,
    Outcome,
    Registration,
)
from logicai.simulation import Status


def _stored_table(library: Library, name: str) -> TruthTable:
    """Table de vérité d'un composant, dans l'ordre de ses broches."""
    circuit = library.component(name).circuit
    return truth_table(flatten(circuit, library.definitions()))


def _looped_not() -> Circuit:
    """Une NAND rebouclée sur elle-même, lue par une sortie : instable."""
    circuit = Circuit()
    nand_id = circuit.add_node(NodeKind.NAND)
    wire(circuit, nand_id, nand_id, 0)
    wire(circuit, nand_id, nand_id, 1)
    wire(circuit, nand_id, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _constant_one() -> Circuit:
    """Une NAND sans câble, lue par une sortie : constante 1, sans nom connu."""
    return gate(0, lambda circuit, _: circuit.add_node(NodeKind.NAND))


def _or3() -> Circuit:
    """OU à trois entrées : sans nom connu."""

    def build(circuit: Circuit, i: list[int]) -> int:
        a_or_b = add_nand(circuit, add_not(circuit, i[0]), add_not(circuit, i[1]))
        return add_nand(circuit, add_not(circuit, a_or_b), add_not(circuit, i[2]))

    return gate(3, build)


def _half_adder(carry_first: bool = False) -> Circuit:
    """Demi-additionneur : somme (XOR) et retenue (AND), en 5 NAND."""
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    n1 = add_nand(circuit, a, b)
    n2 = add_nand(circuit, a, n1)
    n3 = add_nand(circuit, b, n1)
    total = add_nand(circuit, n2, n3)
    carry = add_not(circuit, n1)
    first, second = (carry, total) if carry_first else (total, carry)
    wire(circuit, first, circuit.add_node(NodeKind.OUTPUT))
    wire(circuit, second, circuit.add_node(NodeKind.OUTPUT))
    return circuit


# --- Nommer ---------------------------------------------------------------------------


def test_known_gate_gets_its_name() -> None:
    # Règle vérifiée : cahier, « Nom » (si la signature correspond à une porte connue,
    # elle prend son nom).
    library = Library()
    assert library.register(not_circuit()) == Registration(Outcome.NEW, "NOT")
    assert library.register(gate(2, build_and)) == Registration(Outcome.NEW, "AND")
    assert library.names() == ("NOT", "AND")


def test_unknown_functions_are_numbered() -> None:
    # Règle vérifiée : cahier, « Nom » (sinon elle reçoit un numéro, par exemple C-017).
    library = Library()
    assert library.register(_constant_one()).name == "C-001"
    assert library.register(_or3()).name == "C-002"
    assert library.names() == ("C-001", "C-002")


def test_known_circuit_does_not_consume_a_number() -> None:
    # Règle vérifiée : cahier, « Nom » (les numéros identifient les découvertes).
    library = Library()
    library.register(_constant_one())
    assert library.register(_constant_one()).outcome is Outcome.KNOWN
    assert library.register(_or3()).name == "C-002"


# --- Nouveauté, record, déjà connu ----------------------------------------------------


def test_circuit_with_a_known_signature_and_no_fewer_nands_changes_nothing() -> None:
    # Règle vérifiée : cahier, « Système de récompense » (signature connue, pas moins de
    # NAND : aucune récompense, donc rien ne change), pour plus de NAND puis autant.
    library = Library()
    library.register(gate(2, build_and))
    before = library.component("AND").circuit

    assert library.register(gate(2, bloated(build_and))) == Registration(
        Outcome.KNOWN, "AND"
    )
    assert library.register(gate(2, build_and)) == Registration(Outcome.KNOWN, "AND")
    assert library.component("AND").circuit is before
    assert library.cost("AND") == 2


def test_fewer_nands_replaces_the_definition() -> None:
    # Règle vérifiée : cahier, « Composants et bibliothèque » (si l'IA bat un record,
    # même signature avec moins de NAND, on remplace la définition du composant).
    library = Library()
    assert library.register(gate(2, bloated(build_xor))).outcome is Outcome.NEW
    assert library.cost("XOR") == 6

    assert library.register(xor_circuit()) == Registration(Outcome.RECORD, "XOR")
    assert library.cost("XOR") == 4
    assert library.component("XOR").circuit.nand_count() == 4
    assert library.names() == ("XOR",)


def test_record_keeps_the_position_in_the_library() -> None:
    # Règle vérifiée : cahier, « Composants et bibliothèque » (le composant reste le
    # même, seule sa définition change).
    library = Library()
    library.register(gate(2, bloated(build_xor)))
    library.register(not_circuit())
    library.register(xor_circuit())
    assert library.names() == ("XOR", "NOT")


def test_circuits_using_a_component_profit_from_its_record() -> None:
    # Règle vérifiée : cahier, « Simulation d'un composant » (tous les circuits qui
    # utilisent le composant profitent de la version plus petite).
    library = Library()
    library.register(gate(2, bloated(build_xor)))  # un XOR de 6 NAND
    top = Circuit()
    a, b = top.add_node(NodeKind.INPUT), top.add_node(NodeKind.INPUT)
    xor_id = library.instantiate(top, "XOR")
    wire(top, a, xor_id, 0)
    wire(top, b, xor_id, 1)
    wire(top, add_not(top, xor_id), top.add_node(NodeKind.OUTPUT))  # NON(XOR) = XNOR

    assert library.register(top) == Registration(Outcome.NEW, "XNOR")
    assert library.cost("XNOR") == 7
    library.register(xor_circuit())
    assert library.cost("XNOR") == 5


def test_a_circuit_made_of_the_component_itself_is_not_a_record() -> None:
    # Règle vérifiée : cahier, « Système de récompense » : un circuit qui ne fait que
    # reposer le composant a le même coût, donc ne bat pas le record (et ne crée pas de
    # composant qui se contient lui-même).
    library = Library()
    library.register(gate(1, bloated(build_not)))  # un NOT de 3 NAND, nommé NOT
    top = Circuit()
    wire(top, top.add_node(NodeKind.INPUT), library.instantiate(top, "NOT"))
    wire(top, top.nodes()[1].node_id, top.add_node(NodeKind.OUTPUT))
    assert library.register(top) == Registration(Outcome.KNOWN, "NOT")


def test_xor_made_of_not_and_and_components_is_registered_then_improved() -> None:
    # Règle vérifiée : cahier, plan de développement, phase 2 (un XOR construit avec
    # des composants NOT et AND a la même signature que sa version aplatie), puis
    # record avec la version à 4 NAND.
    library = Library()
    library.register(not_circuit())
    library.register(gate(2, build_and))

    def nand(circuit: Circuit, x: int, y: int) -> int:
        and_id = library.instantiate(circuit, "AND")
        wire(circuit, x, and_id, 0)
        wire(circuit, y, and_id, 1)
        not_id = library.instantiate(circuit, "NOT")
        wire(circuit, and_id, not_id)
        return not_id

    top = Circuit()
    a, b = top.add_node(NodeKind.INPUT), top.add_node(NodeKind.INPUT)
    n1 = nand(top, a, b)
    n2 = nand(top, a, n1)
    n3 = nand(top, b, n1)
    wire(top, nand(top, n2, n3), top.add_node(NodeKind.OUTPUT))

    assert library.register(top) == Registration(Outcome.NEW, "XOR")
    assert library.cost("XOR") == 12
    assert _stored_table(library, "XOR") == TruthTable(Status.STABLE, (0b0110,))

    assert library.register(xor_circuit()) == Registration(Outcome.RECORD, "XOR")
    assert library.cost("XOR") == 4


def test_cost_of_a_user_follows_a_replaced_component() -> None:
    # Règle vérifiée : cahier, « Simulation d'un composant » (composants rangés par
    # référence) : le coût d'un composant qui en utilise un autre baisse avec lui.
    library = Library()
    library.register(gate(1, bloated(build_not)))  # NOT de 3 NAND
    top = Circuit()
    first = library.instantiate(top, "NOT")
    wire(top, top.add_node(NodeKind.INPUT), first)
    second = library.instantiate(top, "NOT")
    wire(top, first, second)
    wire(top, second, top.add_node(NodeKind.OUTPUT))
    library.register(top)  # deux NOT de suite : identité, 6 NAND
    assert library.cost("C-001") == 6

    assert library.register(not_circuit()).outcome is Outcome.RECORD
    assert library.cost("C-001") == 2


# --- Entrées permutées = une seule découverte -----------------------------------------


def test_inputs_swapped_is_the_same_discovery() -> None:
    # Règle vérifiée : cahier, « Composants équivalents » et réponse de Téo
    # (« A ET NON B » et « NON A ET B » sont un seul composant).
    library = Library()
    assert library.register(gate(2, build_and_not)).name == "ANDNOT"
    assert library.register(gate(2, build_not_and)) == Registration(
        Outcome.KNOWN, "ANDNOT"
    )
    assert library.names() == ("ANDNOT",)


def test_record_with_swapped_inputs_keeps_the_pin_order_of_the_component() -> None:
    # Règle vérifiée : décision du plan (ordre des broches de la première découverte).
    # Première découverte : NON A ET B (table 0b0100), en version gonflée. Le record
    # est A ET NON B (table brute 0b0010) : il doit être réordonné pour garder 0b0100.
    library = Library()
    library.register(gate(2, bloated(build_not_and)))
    assert _stored_table(library, "ANDNOT") == TruthTable(Status.STABLE, (0b0100,))

    assert library.register(gate(2, build_and_not)) == Registration(
        Outcome.RECORD, "ANDNOT"
    )
    assert library.cost("ANDNOT") == 3
    assert _stored_table(library, "ANDNOT") == TruthTable(Status.STABLE, (0b0100,))


def test_a_swapped_record_does_not_change_the_circuits_using_the_component() -> None:
    # Règle vérifiée : cahier, « Composants et bibliothèque » (les circuits qui
    # utilisent le composant ne changent pas de comportement quand il est amélioré).
    library = Library()
    library.register(gate(2, bloated(build_not_and)))
    top = Circuit()
    x, y = top.add_node(NodeKind.INPUT), top.add_node(NodeKind.INPUT)
    component_id = library.instantiate(top, "ANDNOT")
    wire(top, x, component_id, 0)
    wire(top, y, component_id, 1)
    wire(top, component_id, top.add_node(NodeKind.OUTPUT))
    before = truth_table(flatten(top, library.definitions()))

    library.register(gate(2, build_and_not))

    assert truth_table(flatten(top, library.definitions())) == before
    assert before == TruthTable(Status.STABLE, (0b0100,))


def test_record_with_rotated_inputs_on_three_inputs() -> None:
    # Règle vérifiée : décision du plan (ordre des broches conservé), sur un
    # multiplexeur où les trois entrées jouent des rôles différents.
    library = Library()
    library.register(gate(3, bloated(build_mux)))
    expected = TruthTable(Status.STABLE, (0b11100100,))
    assert library.names() == ("MUX",)
    assert _stored_table(library, "MUX") == expected

    assert library.register(gate(3, build_mux_rotated)) == Registration(
        Outcome.RECORD, "MUX"
    )
    assert library.cost("MUX") == 4
    assert _stored_table(library, "MUX") == expected  # même ordre de broches


_MUX_ROLES = list(itertools.permutations(range(3)))


@pytest.mark.parametrize("second_roles", _MUX_ROLES)
@pytest.mark.parametrize("first_roles", _MUX_ROLES)
def test_record_keeps_the_pin_order_whatever_the_input_arrangements(
    first_roles: tuple[int, int, int], second_roles: tuple[int, int, int]
) -> None:
    # Règle vérifiée : décision du plan (ordre des broches de la première découverte).
    # Les 6 x 6 arrangements d'entrées du multiplexeur, dont ceux où la correspondance
    # entre les deux ordres est un cycle de 3 entrées (un simple échange ne suffit pas).
    first = build_mux_with_roles(first_roles)
    library = Library()
    library.register(gate(3, bloated(first)))
    expected = truth_table(
        gate(3, first)
    )  # table brute : l'ordre des broches d'origine
    assert _stored_table(library, "MUX") == expected

    second = library.register(gate(3, build_mux_with_roles(second_roles)))

    assert second == Registration(Outcome.RECORD, "MUX")
    assert _stored_table(library, "MUX") == expected


# --- Plusieurs sorties ----------------------------------------------------------------


def test_half_adder_is_registered_and_not_duplicated() -> None:
    # Règle vérifiée : cahier, « Les paliers » (palier 4 : plusieurs sorties) ; l'ordre
    # des sorties fait partie du composant (décision de Téo).
    library = Library()
    assert library.register(_half_adder()) == Registration(Outcome.NEW, "C-001")
    assert library.register(_half_adder()) == Registration(Outcome.KNOWN, "C-001")
    assert library.register(_half_adder(carry_first=True)).name == "C-002"
    assert library.cost("C-001") == 5


# --- Nettoyage et indépendance --------------------------------------------------------


def test_registration_cleans_the_circuit() -> None:
    # Règle vérifiée : cahier, « Nettoyage » (étape 1 de l'encapsulation) : le coût et
    # la définition ne comptent pas ce qui n'influence aucune sortie.
    circuit = xor_circuit()
    add_not(circuit, circuit.inputs()[0])  # une NAND inutile
    library = Library()
    library.register(circuit)
    assert library.cost("XOR") == 4
    assert library.component("XOR").circuit.nand_count() == 4


def test_registered_component_does_not_depend_on_the_original_circuit() -> None:
    # Règle vérifiée : CLAUDE.md (pas d'état partagé caché).
    circuit = xor_circuit()
    library = Library()
    library.register(circuit)
    circuit.add_node(NodeKind.NAND)
    circuit.remove_node(circuit.inputs()[0])
    assert library.cost("XOR") == 4
    assert _stored_table(library, "XOR") == TruthTable(Status.STABLE, (0b0110,))


# --- Lire la bibliothèque -------------------------------------------------------------


def test_instantiate_places_a_component_with_its_pins() -> None:
    # Règle vérifiée : cahier, « Composants et bibliothèque » (les entrées et sorties
    # du circuit deviennent les broches de la boîte).
    library = Library()
    library.register(xor_circuit())
    circuit = Circuit()
    node = circuit.node(library.instantiate(circuit, "XOR"))
    assert node.kind is NodeKind.COMPONENT
    assert node.component_ref == "XOR"
    assert (node.sink_count, node.source_count) == (2, 1)


def test_unknown_component_name_is_refused() -> None:
    # Règle vérifiée : cahier, « Les composants sont rangés par référence ».
    library = Library()
    with pytest.raises(UnknownComponentNameError):
        library.component("GHOST")
    with pytest.raises(UnknownComponentNameError):
        library.instantiate(Circuit(), "GHOST")
    with pytest.raises(UnknownComponentNameError):
        library.cost("GHOST")


# --- Circuits refusés -----------------------------------------------------------------


def test_unstable_circuit_is_refused() -> None:
    # Règle vérifiée : cahier, « Les trois cas détectés » (instable : circuit rejeté).
    library = Library()
    with pytest.raises(UnstableCircuitError):
        library.register(_looped_not())
    assert library.names() == ()


def test_circuit_without_output_is_refused() -> None:
    # Règle vérifiée : décision du plan (un circuit sans sortie est refusé).
    circuit = Circuit()
    add_not(circuit, circuit.add_node(NodeKind.INPUT))
    library = Library()
    with pytest.raises(NoOutputError):
        library.register(circuit)
    assert library.names() == ()


def test_unknown_component_reference_is_refused() -> None:
    # Règle vérifiée : cahier, « Les composants sont rangés par référence ».
    circuit = Circuit()
    wire(
        circuit,
        circuit.add_component_node("GHOST", 0, 1),
        circuit.add_node(NodeKind.OUTPUT),
    )
    library = Library()
    library.register(not_circuit())
    with pytest.raises(UnknownComponentError):
        library.register(circuit)
    assert library.names() == ("NOT",)


# --- Limites d'entrées et de sorties --------------------------------------------------


def _many_inputs(input_count: int) -> Circuit:
    """Beaucoup d'entrées, dont deux seulement servent (NAND des deux premières)."""
    return gate(input_count, lambda c, i: add_nand(c, i[0], i[1]))


def _many_outputs(output_count: int) -> Circuit:
    """Une entrée recopiée sur ``output_count`` sorties."""
    circuit = Circuit()
    input_id = circuit.add_node(NodeKind.INPUT)
    for _ in range(output_count):
        wire(circuit, input_id, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def test_default_limits_are_fifteen_and_fifteen() -> None:
    # Règle vérifiée : réponse de Téo (15 entrées et 15 sorties pour l'instant).
    assert (DEFAULT_MAX_INPUTS, DEFAULT_MAX_OUTPUTS) == (15, 15)
    assert Library().limits == LibraryLimits(max_inputs=15, max_outputs=15)


def test_fifteen_inputs_and_fifteen_outputs_are_accepted() -> None:
    # Règle vérifiée : réponse de Téo (la limite par défaut est 15 : elle est incluse).
    library = Library()
    assert library.register(_many_inputs(15)).outcome is Outcome.NEW
    assert library.register(_many_outputs(15)).outcome is Outcome.NEW


def test_sixteen_inputs_or_outputs_are_refused_by_default() -> None:
    # Règle vérifiée : réponse de Téo (15 maximum par défaut). Le refus est rapide :
    # il a lieu avant tout calcul de table de vérité.
    library = Library()
    with pytest.raises(ComponentTooLargeError):
        library.register(_many_inputs(16))
    with pytest.raises(ComponentTooLargeError):
        library.register(_many_outputs(16))
    assert library.names() == ()


def test_limits_can_be_lifted() -> None:
    # Règle vérifiée : réponse de Téo (« quand on veut, aucune limite »).
    library = Library(LibraryLimits.unlimited())
    assert library.register(_many_inputs(16)).outcome is Outcome.NEW
    assert library.register(_many_outputs(16)).outcome is Outcome.NEW
    assert LibraryLimits.unlimited() == LibraryLimits(max_inputs=None, max_outputs=None)


def test_limits_can_be_chosen() -> None:
    # Règle vérifiée : réponse de Téo (limites réglables).
    library = Library(LibraryLimits(max_inputs=2, max_outputs=1))
    assert library.register(gate(2, build_and)).outcome is Outcome.NEW
    with pytest.raises(ComponentTooLargeError):
        library.register(_many_inputs(3))
    with pytest.raises(ComponentTooLargeError):
        library.register(_many_outputs(2))
    assert Library(LibraryLimits(max_inputs=None)).limits.max_outputs == 15


@pytest.mark.parametrize(
    ("max_inputs", "max_outputs"), [(0, 15), (15, 0), (-3, None), (None, -1)]
)
def test_invalid_limits_are_refused(
    max_inputs: int | None, max_outputs: int | None
) -> None:
    # Règle vérifiée : CLAUDE.md (erreurs dédiées avec un message clair).
    with pytest.raises(InvalidLimitsError):
        LibraryLimits(max_inputs=max_inputs, max_outputs=max_outputs)
