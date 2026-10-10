"""Tests de la CLK dans les mutations et les paliers.

Décision de Téo (10 octobre 2026) : la CLK est un nœud que l'IA pose et câble comme
une NAND. Ce n'est pas une huitième mutation (la liste du cahier reste de sept) : quand
le palier la permet (``allow_clock``), « ajouter une entrée » pose parfois la CLK à la
place.
"""

import random
from collections import Counter

import pytest

from logicai.circuit import Circuit, NodeKind
from logicai.library import Library
from logicai.mutations import Mutation, MutationRules, apply_mutation
from logicai.stages import Stage

NO_CLOCK = MutationRules(max_inputs=2, max_outputs=1)
WITH_CLOCK = MutationRules(max_inputs=2, max_outputs=1, allow_clock=True)
SEEDS = range(200)


def _add_input(circuit: Circuit, rules: MutationRules, seed: int) -> Circuit | None:
    return apply_mutation(
        Mutation.ADD_INPUT, circuit, random.Random(seed), rules, Library()
    )


def _kinds(circuit: Circuit) -> list[NodeKind]:
    return [node.kind for node in circuit.nodes()]


def test_without_the_setting_an_input_is_always_an_input() -> None:
    # Palier sans CLK : « ajouter une entrée » ne pose jamais de CLK.
    for seed in SEEDS:
        child = _add_input(Circuit(), NO_CLOCK, seed)
        assert child is not None
        assert _kinds(child) == [NodeKind.INPUT]


def test_without_the_setting_no_random_number_is_drawn() -> None:
    # Les déroulements d'avant restent exactement les mêmes (tests à graine fixe).
    rng = random.Random(5)
    apply_mutation(Mutation.ADD_INPUT, Circuit(), rng, NO_CLOCK, Library())
    assert rng.random() == random.Random(5).random()


def test_with_the_setting_an_input_or_a_clock_is_placed() -> None:
    placed = Counter()
    for seed in SEEDS:
        child = _add_input(Circuit(), WITH_CLOCK, seed)
        assert child is not None
        placed[_kinds(child)[0]] += 1
    assert set(placed) == {NodeKind.INPUT, NodeKind.CLK}
    # Une chance sur deux chacun, à 200 tirages près.
    assert all(60 < count < 140 for count in placed.values())


def test_there_is_at_most_one_clock() -> None:
    # Toutes les CLK d'un circuit sont la même horloge : une seule suffit.
    only_clock = MutationRules(max_inputs=0, max_outputs=1, allow_clock=True)
    first = _add_input(Circuit(), only_clock, 0)
    assert first is not None
    assert _kinds(first) == [NodeKind.CLK]
    assert _add_input(first, only_clock, 0) is None


def test_the_clock_is_placed_even_when_the_inputs_are_full() -> None:
    circuit = Circuit()
    circuit.add_node(NodeKind.INPUT)
    circuit.add_node(NodeKind.INPUT)
    child = _add_input(circuit, WITH_CLOCK, 0)
    assert child is not None
    assert _kinds(child).count(NodeKind.CLK) == 1
    assert _add_input(child, WITH_CLOCK, 0) is None  # entrées pleines, CLK déjà là


def test_an_input_is_placed_when_the_clock_is_already_there() -> None:
    circuit = Circuit()
    circuit.add_node(NodeKind.CLK)
    for seed in SEEDS:
        child = _add_input(circuit, WITH_CLOCK, seed)
        assert child is not None
        assert _kinds(child) == [NodeKind.CLK, NodeKind.INPUT]


def test_the_parent_is_not_changed() -> None:
    parent = Circuit()
    before = (parent.nodes(), parent.wires())
    _add_input(parent, WITH_CLOCK, 1)
    assert (parent.nodes(), parent.wires()) == before


def test_a_clock_can_be_removed_like_any_gate() -> None:
    # « Retirer un nœud » : l'IA peut défaire sa CLK.
    circuit = Circuit()
    circuit.add_node(NodeKind.CLK)
    child = apply_mutation(
        Mutation.REMOVE_NODE, circuit, random.Random(0), WITH_CLOCK, Library()
    )
    assert child is not None
    assert child.clocks() == ()


def test_a_wire_can_start_from_the_clock() -> None:
    # La CLK se câble comme n'importe quelle source.
    circuit = Circuit()
    circuit.add_node(NodeKind.CLK)
    circuit.add_node(NodeKind.NAND)
    starts = set()
    for seed in SEEDS:
        child = apply_mutation(
            Mutation.ADD_WIRE, circuit, random.Random(seed), WITH_CLOCK, Library()
        )
        assert child is not None
        starts.update(kind for kind in _kinds_of_sources(child))
    assert NodeKind.CLK in starts


def _kinds_of_sources(circuit: Circuit) -> list[NodeKind]:
    return [circuit.node(wire.source.node_id).kind for wire in circuit.wires()]


def test_a_stage_passes_its_clock_setting_to_the_mutations() -> None:
    stage = Stage(5, 2, 1, allow_loops=True, allow_clock=True)
    assert stage.rules == MutationRules(2, 1, allow_loops=True, allow_clock=True)
    assert Stage(1, 1, 1).rules.allow_clock is False


def test_the_clock_setting_is_off_by_default() -> None:
    assert MutationRules(1, 1).allow_clock is False


@pytest.mark.parametrize("kind", list(Mutation))
def test_the_seven_mutations_of_the_cahier_are_still_the_only_ones(
    kind: Mutation,
) -> None:
    # La CLK n'a pas ajouté de mutation : il y en a toujours sept.
    assert len(Mutation) == 7
    assert kind in Mutation
