"""Tests des circuits à mémoire : batterie, signature, filtres, bibliothèque.

Cahier, « Circuits séquentiels » : une batterie fixe de séquences d'entrées, la même
pour tous les circuits ; la signature est la suite des sorties lues pendant ces
séquences. Décision de Téo (10 octobre 2026) : un seul changement d'entrée à la fois,
chaque marche part de toutes les entrées à 0 et change une entrée par pas (4 pas).
"""

import itertools
from pathlib import Path

import pytest

from builders import add_nand, add_not, not_circuit, sr_latch, wire, xor_circuit
from logicai.circuit import Circuit, NodeKind, Pin
from logicai.errors import SignatureError, SimulationError, UnstableCircuitError
from logicai.filters import (
    Rejection,
    find_behavior_rejections,
    find_rejections,
    sequential_rejections,
)
from logicai.flatten import flatten
from logicai.library import Library, Outcome
from logicai.sequential import (
    BATTERY_LENGTH,
    BatteryResult,
    SequentialForm,
    SequentialSignature,
    battery_walks,
    has_loop,
    run_battery,
    sequential_form,
    walk_vectors,
)
from logicai.signature import Signature
from logicai.simulation import Status

# Réponse de la bascule SR à la marche « S̄, R̄, S̄, S̄ », calculée à la main d'après le
# cahier : entrées (0,0) puis (1,0), (1,1), (0,1), (1,1) ; sorties (Q, Q̄) à chaque pas.
LATCH_WALK = (0, 1, 0, 0)
LATCH_WALK_OUTPUTS = ((1, 1), (0, 1), (0, 1), (1, 0), (1, 0))


# --- Circuits de test --------------------------------------------------------------


def _latch_core() -> tuple[Circuit, int, int, int, int]:
    """Bascule SR sans sorties : le circuit, S̄, R̄, la NAND Q et la NAND Q̄."""
    circuit = Circuit()
    s_bar = circuit.add_node(NodeKind.INPUT)
    r_bar = circuit.add_node(NodeKind.INPUT)
    q = circuit.add_node(NodeKind.NAND)
    q_bar = circuit.add_node(NodeKind.NAND)
    wire(circuit, s_bar, q, 0)
    wire(circuit, q_bar, q, 1)
    wire(circuit, r_bar, q_bar, 0)
    wire(circuit, q, q_bar, 1)
    return circuit, s_bar, r_bar, q, q_bar


def _add_outputs(circuit: Circuit, *sources: int) -> Circuit:
    """Ajoute une sortie par source donnée, dans l'ordre."""
    for source in sources:
        wire(circuit, source, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _latch_q_only() -> Circuit:
    circuit, _, _, q, _ = _latch_core()
    return _add_outputs(circuit, q)


def _latch_with_swapped_outputs() -> Circuit:
    circuit, _, _, q, q_bar = _latch_core()
    return _add_outputs(circuit, q_bar, q)


def _latch_then_nand() -> Circuit:
    """Sorties (Q, NAND(S̄, R̄)) : une mémoire, puis une porte symétrique en S̄ et R̄."""
    circuit, s_bar, r_bar, q, _ = _latch_core()
    return _add_outputs(circuit, q, add_nand(circuit, s_bar, r_bar))


def _nand_then_latch() -> Circuit:
    """Les mêmes sorties que ``_latch_then_nand``, dans l'ordre inverse."""
    circuit, s_bar, r_bar, q, _ = _latch_core()
    return _add_outputs(circuit, add_nand(circuit, s_bar, r_bar), q)


def _bloated_latch() -> Circuit:
    """Bascule SR dont la sortie Q passe par deux NOT inutiles (4 NAND au lieu de 2)."""
    circuit, _, _, q, q_bar = _latch_core()
    slow_q = add_not(circuit, add_not(circuit, q))
    return _add_outputs(circuit, slow_q, q_bar)


def _gated_latch() -> Circuit:
    """Bascule SR dont le reset est bloqué quand une 3e entrée T vaut 1.

    R̄' = R̄ OU T. T n'agit sur aucune sortie tout de suite : seulement plus tard, quand
    on demande un reset (R̄ = 0) alors que T vaut 1.
    """
    circuit = Circuit()
    s_bar = circuit.add_node(NodeKind.INPUT)
    r_bar = circuit.add_node(NodeKind.INPUT)
    block = circuit.add_node(NodeKind.INPUT)
    r_bar_gated = add_nand(circuit, add_not(circuit, r_bar), add_not(circuit, block))
    q = circuit.add_node(NodeKind.NAND)
    q_bar = circuit.add_node(NodeKind.NAND)
    wire(circuit, s_bar, q, 0)
    wire(circuit, q_bar, q, 1)
    wire(circuit, r_bar_gated, q_bar, 0)
    wire(circuit, q, q_bar, 1)
    return _add_outputs(circuit, q, q_bar)


def _not_with_an_irrelevant_loop() -> Circuit:
    """Un NOT dont la NAND est aussi dans une boucle qui ne change rien (stable)."""
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    not_data = circuit.add_node(NodeKind.NAND)
    constant_one = circuit.add_node(NodeKind.NAND)  # NAND(x, 0) = 1 quoi que vaille x
    wire(circuit, data, not_data, 0)
    wire(circuit, constant_one, not_data, 1)
    wire(circuit, not_data, constant_one, 0)
    return _add_outputs(circuit, not_data)


def _oscillator_with_an_input() -> Circuit:
    """Une entrée inutile et une NAND qui se lit elle-même : elle oscille."""
    circuit = Circuit()
    circuit.add_node(NodeKind.INPUT)
    nand = circuit.add_node(NodeKind.NAND)
    wire(circuit, nand, nand, 0)
    wire(circuit, nand, nand, 1)
    return _add_outputs(circuit, nand)


# --- La batterie -------------------------------------------------------------------


def test_battery_has_every_walk_of_single_changes() -> None:
    # Choix de Téo : toutes les marches de 4 changements, une entrée par pas.
    walks = battery_walks(2)
    assert len(walks) == 2**BATTERY_LENGTH
    assert len(set(walks)) == len(walks)
    assert all(len(walk) == BATTERY_LENGTH for walk in walks)
    assert len(battery_walks(3)) == 3**BATTERY_LENGTH
    assert len(battery_walks(1)) == 1


def test_battery_is_empty_without_inputs_and_refuses_a_zero_length() -> None:
    assert battery_walks(0) == ()
    with pytest.raises(SimulationError, match="longueur"):
        battery_walks(2, length=0)


def test_every_walk_starts_at_zero_and_changes_one_input_per_step() -> None:
    # Choix de Téo : jamais deux entrées qui changent en même temps (métastabilité).
    for walk in battery_walks(3):
        vectors = walk_vectors(3, walk)
        assert vectors[0] == (0, 0, 0)
        for before, after in itertools.pairwise(vectors):
            assert sum(a != b for a, b in zip(before, after, strict=True)) == 1


def test_a_circuit_without_loop_has_no_battery() -> None:
    # Pas de boucle, pas de mémoire possible : la batterie est inutile.
    assert run_battery(xor_circuit()) is None
    assert run_battery(not_circuit()) is None


def test_a_circuit_without_input_has_no_battery() -> None:
    circuit = Circuit()
    nand = circuit.add_node(NodeKind.NAND)
    wire(circuit, nand, nand, 0)
    assert run_battery(_add_outputs(circuit, nand)) is None


@pytest.mark.parametrize(
    ("circuit", "expected"),
    [
        (xor_circuit(), False),
        (sr_latch(), True),
        (_oscillator_with_an_input(), True),
        (_not_with_an_irrelevant_loop(), True),
        (Circuit(), False),
    ],
)
def test_has_loop(circuit: Circuit, expected: bool) -> None:
    # Cahier, règle 5 : les boucles sont autorisées (y compris sur sa propre porte).
    assert has_loop(circuit) is expected


def test_two_wires_from_one_source_are_not_a_loop() -> None:
    # Un NOT (NAND dont les deux puits ont la même source) n'est pas une boucle.
    assert has_loop(not_circuit()) is False


def test_sr_latch_remembers_on_the_battery() -> None:
    # Cahier, « Mémoire » : même entrée actuelle, sortie différente selon le passé.
    battery = run_battery(sr_latch())
    assert battery is not None
    assert battery.status is Status.STABLE
    assert battery.memory is True
    assert len(battery.responses) == 2**BATTERY_LENGTH


def test_sr_latch_response_to_one_walk_matches_the_hand_calculation() -> None:
    battery = run_battery(sr_latch())
    assert battery is not None
    assert battery.responses[LATCH_WALK] == LATCH_WALK_OUTPUTS


def test_a_battery_of_three_changes_cannot_show_the_latch_memory() -> None:
    # (1,1) doit être atteint deux fois après un set puis un reset : 4 changements.
    short = run_battery(sr_latch(), length=BATTERY_LENGTH - 1)
    assert short is not None
    assert short.status is Status.STABLE
    assert short.memory is False


def test_a_looped_nand_is_unstable_on_the_battery() -> None:
    # Cahier, « Les trois cas détectés » : une oscillation rejette le circuit.
    battery = run_battery(_oscillator_with_an_input())
    assert battery == BatteryResult(Status.UNSTABLE, False, {})


def test_a_stable_loop_without_memory_is_not_a_memory() -> None:
    battery = run_battery(_not_with_an_irrelevant_loop())
    assert battery is not None
    assert (battery.status, battery.memory) == (Status.STABLE, False)


# --- La signature séquentielle ------------------------------------------------------


def _form_of(circuit: Circuit) -> SequentialForm:
    battery = run_battery(circuit)
    assert battery is not None
    return sequential_form(battery, len(circuit.inputs()))


def test_swapped_inputs_give_the_same_signature() -> None:
    # Cahier, « Composants équivalents » : entrées échangées = une seule découverte.
    plain = _form_of(sr_latch())
    swapped = _form_of(sr_latch().with_inputs_reordered((1, 0)))
    assert plain.signature == swapped.signature
    assert plain.exact and swapped.exact


def test_the_order_of_the_outputs_is_part_of_the_signature() -> None:
    # Cahier : « les sorties ne sont jamais permutées : leur ordre fait partie du
    # composant ».
    assert (
        _form_of(_latch_then_nand()).signature != _form_of(_nand_then_latch()).signature
    )


def test_swapping_the_outputs_of_a_latch_is_swapping_its_inputs() -> None:
    # La bascule SR est symétrique : échanger S̄ et R̄ échange Q et Q̄. Une bascule aux
    # sorties échangées est donc la même découverte (seules les entrées sont permutées).
    assert (
        _form_of(sr_latch()).signature
        == _form_of(_latch_with_swapped_outputs()).signature
    )


def test_a_different_behavior_gives_another_signature() -> None:
    assert _form_of(sr_latch()).signature != _form_of(_latch_q_only()).signature


def test_input_order_reorders_a_circuit_to_the_canonical_pins() -> None:
    # ``input_order`` a le même sens que pour les tables : réordonner le circuit avec
    # lui donne une copie dont la forme canonique garde l'ordre naturel.
    swapped = sr_latch().with_inputs_reordered((1, 0))
    form = _form_of(swapped)
    reordered = swapped.with_inputs_reordered(form.input_order)
    assert _form_of(reordered).input_order == (0, 1)
    assert _form_of(reordered).signature == form.signature


@pytest.mark.parametrize("cycle", [(1, 2, 0), (2, 0, 1)])
def test_three_inputs_rotated_give_the_same_signature_and_a_usable_order(
    cycle: tuple[int, int, int],
) -> None:
    # Une rotation de 3 entrées n'est pas son propre inverse (contrairement à un simple
    # échange) : ce test distingue l'ordre de l'ordre inverse. ``input_order`` redonne
    # l'ordre canonique quand on l'applique au circuit.
    plain = _form_of(_gated_latch())
    rotated = _gated_latch().with_inputs_reordered(cycle)
    form = _form_of(rotated)
    assert form.signature == plain.signature
    assert _form_of(rotated.with_inputs_reordered(form.input_order)).input_order == (
        0,
        1,
        2,
    )


@pytest.mark.parametrize(("inputs", "exact"), [(5, True), (6, False)])
def test_all_orders_are_tried_up_to_five_inputs(inputs: int, exact: bool) -> None:
    walks = {(0,): ((0,), (1,))}
    form = sequential_form(BatteryResult(Status.STABLE, True, walks), inputs)
    assert form.exact is exact


def test_a_stable_battery_without_any_response_has_no_signature() -> None:
    with pytest.raises(SignatureError):
        sequential_form(BatteryResult(Status.STABLE, False, {}), 2)


def test_signature_records_the_pin_counts() -> None:
    signature = _form_of(sr_latch()).signature
    assert (signature.input_count, signature.output_count) == (2, 2)
    assert len(signature.responses) == 2**BATTERY_LENGTH


def test_too_many_inputs_keep_the_original_order_and_say_so() -> None:
    # Comme pour les tables : au-delà de MAX_CANONICAL_INPUTS, pas de fusion garantie.
    walks = {(0,): ((0,), (1,))}
    inputs = 6
    form = sequential_form(BatteryResult(Status.STABLE, True, walks), inputs)
    assert form.exact is False
    assert form.input_order == tuple(range(inputs))
    assert isinstance(form.signature, SequentialSignature)


def test_an_unstable_battery_has_no_signature() -> None:
    unstable = run_battery(_oscillator_with_an_input())
    assert unstable is not None
    with pytest.raises(SignatureError):
        sequential_form(unstable, 1)


# --- Les filtres sur la batterie ----------------------------------------------------


def test_the_latch_passes_the_filters() -> None:
    assert find_behavior_rejections(sr_latch(), {}) == ()
    assert find_behavior_rejections(_latch_q_only(), {}) == ()


def test_the_old_filter_still_calls_the_latch_unstable() -> None:
    # Les filtres de la table de vérité n'ont pas changé : seule la nouvelle fonction
    # juge un circuit sur sa batterie.
    assert find_rejections(sr_latch(), {}) == (Rejection.UNSTABLE,)


def test_an_oscillating_circuit_is_rejected_as_unstable() -> None:
    # Cahier, filtre « il est instable ».
    assert find_behavior_rejections(_oscillator_with_an_input(), {}) == (
        Rejection.UNSTABLE,
    )


def test_an_unused_input_of_a_memory_circuit_is_rejected() -> None:
    # Cahier, filtre « une de ses entrées n'influence aucune sortie ».
    circuit, _, _, q, q_bar = _latch_core()
    circuit.add_node(NodeKind.INPUT)
    _add_outputs(circuit, q, q_bar)
    assert find_behavior_rejections(circuit, {}) == (Rejection.UNUSED_INPUT,)


def test_an_input_that_only_acts_later_is_not_unused() -> None:
    # T ne change aucune sortie au moment où il change : il bloque seulement un reset
    # demandé plus tard. Le filtre compare chaque pas à la marche sans ses changements.
    assert find_behavior_rejections(_gated_latch(), {}) == ()


@pytest.mark.parametrize("copied", ["S", "R"])
def test_an_output_that_copies_an_input_is_rejected(copied: str) -> None:
    # Cahier, filtre « une sortie recopie simplement une entrée » : n'importe laquelle.
    circuit, s_bar, r_bar, q, q_bar = _latch_core()
    _add_outputs(circuit, q, q_bar, s_bar if copied == "S" else r_bar)
    assert find_behavior_rejections(circuit, {}) == (Rejection.COPIED_INPUT,)


def test_two_identical_outputs_of_a_memory_circuit_are_rejected() -> None:
    # Cahier, filtre « deux de ses sorties sont identiques ».
    circuit, _, _, q, _ = _latch_core()
    _add_outputs(circuit, q, q)
    assert find_behavior_rejections(circuit, {}) == (Rejection.DUPLICATE_OUTPUTS,)


def test_a_constant_output_of_a_memory_circuit_is_rejected() -> None:
    # Cahier, filtre « une de ses sorties est constante ».
    circuit, _, _, q, _ = _latch_core()
    always_one = circuit.add_node(NodeKind.NAND)  # sans câble : NAND(0, 0) = 1
    _add_outputs(circuit, q, always_one)
    assert find_behavior_rejections(circuit, {}) == (Rejection.CONSTANT_OUTPUT,)


def test_sequential_filters_work_on_a_response_without_outputs() -> None:
    assert sequential_rejections({}, 0) == ()


def test_circuits_without_memory_are_judged_by_their_truth_table() -> None:
    # Sans boucle, ou avec une boucle qui ne change rien : le résultat est celui de
    # ``find_rejections`` (cahier : un circuit combinatoire a une table de vérité).
    for circuit in (xor_circuit(), not_circuit(), _not_with_an_irrelevant_loop()):
        assert find_behavior_rejections(circuit, {}) == find_rejections(circuit, {})


# --- La bibliothèque ----------------------------------------------------------------


def test_the_library_accepts_a_latch_as_a_sequential_component() -> None:
    # Cahier, « Composants et bibliothèque » : une découverte devient un composant.
    library = Library()
    registration = library.register(sr_latch())
    assert registration.outcome is Outcome.NEW
    assert registration.name == "C-001"  # pas de nom connu pour une bascule
    assert isinstance(library.component("C-001").signature, SequentialSignature)
    assert library.cost("C-001") == 2


def test_an_equivalent_latch_with_swapped_inputs_is_not_a_new_discovery() -> None:
    # Cahier, « Composants équivalents ».
    library = Library()
    library.register(sr_latch())
    again = library.register(sr_latch().with_inputs_reordered((1, 0)))
    assert (again.outcome, again.name) == (Outcome.KNOWN, "C-001")


def test_the_same_outputs_in_another_order_are_a_new_discovery() -> None:
    # Cahier : l'ordre des sorties fait partie du composant.
    library = Library()
    library.register(_latch_then_nand())
    other = library.register(_nand_then_latch())
    assert (other.outcome, other.name) == (Outcome.NEW, "C-002")


def test_a_latch_with_swapped_outputs_is_not_a_new_discovery() -> None:
    # Voir ``test_swapping_the_outputs_of_a_latch_is_swapping_its_inputs``.
    library = Library()
    library.register(sr_latch())
    again = library.register(_latch_with_swapped_outputs())
    assert (again.outcome, again.name) == (Outcome.KNOWN, "C-001")


def test_a_smaller_latch_replaces_the_bloated_one() -> None:
    # Cahier, « Système de récompense » : même signature avec moins de NAND = record.
    library = Library()
    assert library.register(_bloated_latch()).outcome is Outcome.NEW
    assert library.cost("C-001") == 4
    record = library.register(sr_latch())
    assert (record.outcome, record.name) == (Outcome.RECORD, "C-001")
    assert library.cost("C-001") == 2


def test_a_record_keeps_the_pin_order_of_the_stored_component() -> None:
    # Cahier : les circuits qui utilisent le composant ne changent pas de comportement.
    # On enregistre d'abord une version aux entrées échangées, puis la plus petite.
    library = Library()
    bloated_swapped = _bloated_latch().with_inputs_reordered((1, 0))
    library.register(bloated_swapped)
    library.register(sr_latch())
    stored = run_battery(flatten(library.component("C-001").circuit, {}))
    expected = run_battery(bloated_swapped)
    assert stored is not None
    assert expected is not None
    assert stored.responses == expected.responses


def test_an_oscillating_circuit_is_refused_by_the_library() -> None:
    # Le refus vient de la batterie (le message le dit), pas de la table de vérité.
    library = Library()
    with pytest.raises(UnstableCircuitError, match="batterie"):
        library.register(_oscillator_with_an_input())
    assert library.names() == ()


def test_a_loop_without_memory_stays_a_combinational_component() -> None:
    # Une boucle ne suffit pas à faire une mémoire : ce circuit est un NOT.
    library = Library()
    registration = library.register(_not_with_an_irrelevant_loop())
    assert (registration.outcome, registration.name) == (Outcome.NEW, "NOT")
    assert isinstance(library.component("NOT").signature, Signature)


def test_a_sequential_component_survives_saving_and_loading(tmp_path: Path) -> None:
    library = Library()
    library.register(sr_latch())
    library.save(tmp_path)
    loaded = Library.load(tmp_path)
    assert loaded.names() == library.names()
    assert loaded.component("C-001").signature == library.component("C-001").signature


def test_a_circuit_that_places_the_latch_component_has_the_same_signature() -> None:
    # Cahier, « Simulation d'un composant » : on remplace le composant par ses NAND.
    library = Library()
    library.register(sr_latch())
    circuit = Circuit()
    s_bar = circuit.add_node(NodeKind.INPUT)
    r_bar = circuit.add_node(NodeKind.INPUT)
    box = library.instantiate(circuit, "C-001")
    wire(circuit, s_bar, box, 0)
    wire(circuit, r_bar, box, 1)
    for output in range(2):
        circuit.connect(Pin(box, output), Pin(circuit.add_node(NodeKind.OUTPUT), 0))
    flat = flatten(circuit, library.definitions())
    assert find_behavior_rejections(circuit, library.definitions()) == ()
    battery = run_battery(flat)
    assert battery is not None
    assert sequential_form(battery, 2).signature == library.component("C-001").signature
