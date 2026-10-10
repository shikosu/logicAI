"""Tests des filtres anti-triche (cahier, « Les filtres anti-triche »)."""

import itertools
import random

import pytest

from builders import (
    add_nand,
    add_not,
    build_and,
    build_and_not,
    build_mux,
    build_not,
    build_xor,
    gate,
    not_circuit,
    pass_through,
    sr_latch,
    wire,
    xor_circuit,
)
from logicai.behavior import TruthTable
from logicai.circuit import Circuit, NodeKind
from logicai.errors import FlattenError
from logicai.filters import Rejection, find_rejections, rejections_of_table
from logicai.library import Library
from logicai.simulation import Status

NO_COMPONENTS: dict[str, Circuit] = {}


def _find(circuit: Circuit) -> tuple[Rejection, ...]:
    """Applique les filtres à un circuit sans composant."""
    return find_rejections(circuit, NO_COMPONENTS)


# --- Circuits utiles : acceptés ----------------------------------------------


@pytest.mark.parametrize(
    "circuit",
    [
        gate(1, build_not),
        gate(2, build_and),
        gate(2, build_xor),
        gate(2, build_and_not),
        gate(3, build_mux),
    ],
    ids=["NOT", "AND", "XOR", "ANDNOT", "MUX"],
)
def test_useful_gates_are_accepted(circuit: Circuit) -> None:
    # Règle : un circuit dont toutes les entrées servent, dont aucune sortie n'est
    # constante ni recopiée, et qui est stable, n'est refusé par aucun filtre.
    assert _find(circuit) == ()


def test_not_is_not_a_wire() -> None:
    # Règle : « une sortie recopie simplement une entrée (un fil suffirait) ».
    # Un NOT inverse son entrée : ce n'est pas un fil, donc il reste accepté.
    assert _find(not_circuit()) == ()


def test_several_useful_outputs_are_accepted() -> None:
    # Règle : les filtres valent aussi pour plusieurs sorties ; un demi-additionneur
    # (somme = XOR, retenue = AND) n'est refusé par aucun filtre.
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    wire(circuit, build_xor(circuit, [a, b]), circuit.add_node(NodeKind.OUTPUT))
    wire(circuit, build_and(circuit, [a, b]), circuit.add_node(NodeKind.OUTPUT))
    assert _find(circuit) == ()


# --- Filtre 1 : une entrée n'influence aucune sortie -------------------------


def test_unused_input_is_rejected() -> None:
    # Règle : « une de ses entrées n'influence aucune sortie ».
    # Sortie = NON A ; l'entrée B n'est reliée à rien.
    circuit = Circuit()
    a = circuit.add_node(NodeKind.INPUT)
    circuit.add_node(NodeKind.INPUT)
    wire(circuit, add_not(circuit, a), circuit.add_node(NodeKind.OUTPUT))
    assert _find(circuit) == (Rejection.UNUSED_INPUT,)


def test_wired_but_useless_input_is_rejected() -> None:
    # Règle : le filtre juge le comportement, pas le câblage. Ici B est câblée dans
    # une NAND, mais NAND(B, NON B) vaut toujours 1 : la sortie vaut A, et B ne sert à
    # rien. Le circuit recopie aussi A, donc deux motifs.
    def build(circuit: Circuit, i: list[int]) -> int:
        always_one = add_nand(circuit, i[1], add_not(circuit, i[1]))
        return add_not(circuit, add_nand(circuit, i[0], always_one))

    assert _find(gate(2, build)) == (Rejection.UNUSED_INPUT, Rejection.COPIED_INPUT)


def test_input_without_any_output_is_rejected() -> None:
    # Règle : « une de ses entrées n'influence aucune sortie » ; sans aucune sortie,
    # l'entrée n'influence évidemment rien.
    circuit = Circuit()
    circuit.add_node(NodeKind.INPUT)
    assert _find(circuit) == (Rejection.UNUSED_INPUT,)


def test_an_input_that_matters_on_one_output_only_is_accepted() -> None:
    # Règle : il suffit que l'entrée influence UNE sortie. La 1re sortie vaut NON A
    # (B n'y change rien), la 2e vaut A ET B : B n'agit que sur la 2e, et c'est assez.
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    wire(circuit, add_not(circuit, a), circuit.add_node(NodeKind.OUTPUT))
    wire(circuit, build_and(circuit, [a, b]), circuit.add_node(NodeKind.OUTPUT))
    assert _find(circuit) == ()


# --- Filtre 2 : une sortie est constante -------------------------------------


def test_output_without_wire_is_constant_zero() -> None:
    # Règle : « une de ses sorties est constante » (un puits sans câble vaut 0).
    # L'entrée A ne sert à rien non plus.
    circuit = Circuit()
    circuit.add_node(NodeKind.INPUT)
    circuit.add_node(NodeKind.OUTPUT)
    assert _find(circuit) == (Rejection.UNUSED_INPUT, Rejection.CONSTANT_OUTPUT)


def test_nand_without_wire_is_constant_one() -> None:
    # Règle : une NAND sans aucun câble fournit un 1 constant (cahier, règle de
    # câblage 4). Sans entrée, seul le filtre « sortie constante » s'applique.
    circuit = Circuit()
    wire(circuit, circuit.add_node(NodeKind.NAND), circuit.add_node(NodeKind.OUTPUT))
    assert _find(circuit) == (Rejection.CONSTANT_OUTPUT,)


def test_one_constant_output_among_good_ones_is_rejected() -> None:
    # Règle : « une de ses sorties est constante » : une seule suffit.
    circuit = Circuit()
    a = circuit.add_node(NodeKind.INPUT)
    wire(circuit, add_not(circuit, a), circuit.add_node(NodeKind.OUTPUT))
    circuit.add_node(NodeKind.OUTPUT)
    assert _find(circuit) == (Rejection.CONSTANT_OUTPUT,)


# --- Filtre 3 : deux sorties identiques --------------------------------------


def test_duplicate_outputs_are_rejected() -> None:
    # Règle : « deux de ses sorties sont identiques ». Un XOR branché sur 2 sorties.
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    xor = build_xor(circuit, [a, b])
    wire(circuit, xor, circuit.add_node(NodeKind.OUTPUT))
    wire(circuit, xor, circuit.add_node(NodeKind.OUTPUT))
    assert _find(circuit) == (Rejection.DUPLICATE_OUTPUTS,)


def test_equivalent_outputs_built_differently_are_rejected() -> None:
    # Règle : le filtre compare les tables de vérité, pas les câbles : deux XOR
    # construits séparément ont la même table, donc sont « identiques ».
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    wire(circuit, build_xor(circuit, [a, b]), circuit.add_node(NodeKind.OUTPUT))
    wire(circuit, build_xor(circuit, [b, a]), circuit.add_node(NodeKind.OUTPUT))
    assert _find(circuit) == (Rejection.DUPLICATE_OUTPUTS,)


# --- Filtre 4 : une sortie recopie une entrée --------------------------------


def test_wire_from_input_to_output_is_rejected() -> None:
    # Règle : « une sortie recopie simplement une entrée (un fil suffirait) ».
    assert _find(pass_through()) == (Rejection.COPIED_INPUT,)


def test_one_copied_output_among_good_ones_is_rejected() -> None:
    # Règle : une seule sortie recopiée suffit à refuser le circuit, même si l'autre
    # sortie (NON A) est utile.
    circuit = Circuit()
    a = circuit.add_node(NodeKind.INPUT)
    wire(circuit, a, circuit.add_node(NodeKind.OUTPUT))
    wire(circuit, add_not(circuit, a), circuit.add_node(NodeKind.OUTPUT))
    assert _find(circuit) == (Rejection.COPIED_INPUT,)


# --- Filtre 5 : circuit instable ---------------------------------------------


def test_self_looped_nand_is_rejected_as_unstable() -> None:
    # Règle : « il est instable ». Une NAND rebouclée sur elle-même oscille. Ce
    # circuit n'a aucune entrée (il serait aussi « constant ») : seul le motif
    # « instable » est donné, car sa table n'est pas significative.
    circuit = Circuit()
    nand = circuit.add_node(NodeKind.NAND)
    wire(circuit, nand, nand, 0)
    wire(circuit, nand, nand, 1)
    wire(circuit, nand, circuit.add_node(NodeKind.OUTPUT))
    assert _find(circuit) == (Rejection.UNSTABLE,)


def test_metastable_latch_is_rejected_as_unstable() -> None:
    # Règle : « il est instable » (cahier, « Piège à connaître » : la bascule SR en
    # NAND oscille quand ses deux entrées passent à 1 ensemble).
    assert _find(sr_latch()) == (Rejection.UNSTABLE,)


def test_unstable_table_hides_other_reasons() -> None:
    # Règle : un circuit instable n'a pas de table significative, donc les autres
    # filtres ne sont pas examinés, même si les entiers ressembleraient à une constante.
    table = TruthTable(Status.UNSTABLE, (0, 0))
    assert rejections_of_table(table, 2) == (Rejection.UNSTABLE,)


# --- Composants et circuit non modifié ---------------------------------------


def _library_with_xor() -> Library:
    library = Library()
    library.register(xor_circuit())
    assert library.names() == ("XOR",)
    return library


def test_components_are_flattened_before_judging() -> None:
    # Règle : un composant est simulé en le remplaçant par ses NAND (cahier,
    # « Simulation d'un composant »). XOR(A, A) vaut toujours 0 : la sortie est
    # constante et l'entrée ne sert à rien, ce qu'on ne voit qu'après aplatissement.
    library = _library_with_xor()
    circuit = Circuit()
    a = circuit.add_node(NodeKind.INPUT)
    xor = library.instantiate(circuit, "XOR")
    wire(circuit, a, xor, 0)
    wire(circuit, a, xor, 1)
    wire(circuit, xor, circuit.add_node(NodeKind.OUTPUT))
    assert find_rejections(circuit, library.definitions()) == (
        Rejection.UNUSED_INPUT,
        Rejection.CONSTANT_OUTPUT,
    )


def test_useful_circuit_with_a_component_is_accepted() -> None:
    # Règle : un circuit qui réutilise un composant (XOR) de façon utile est accepté.
    library = _library_with_xor()
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    xor = library.instantiate(circuit, "XOR")
    wire(circuit, a, xor, 0)
    wire(circuit, b, xor, 1)
    wire(circuit, xor, circuit.add_node(NodeKind.OUTPUT))
    assert find_rejections(circuit, library.definitions()) == ()


def test_unknown_component_is_an_error_not_a_rejection() -> None:
    # Règle : un circuit invalide (composant inconnu) n'est pas « inutile » : l'erreur
    # d'aplatissement est levée telle quelle, elle n'est pas cachée dans un motif.
    circuit = Circuit()
    node = circuit.add_component_node("INCONNU", 1, 1)
    wire(circuit, node, circuit.add_node(NodeKind.OUTPUT))
    with pytest.raises(FlattenError):
        find_rejections(circuit, NO_COMPONENTS)


def test_filters_do_not_change_the_circuit() -> None:
    # Règle : un contrôle ne modifie jamais l'objet contrôlé.
    circuit = gate(2, build_xor)
    nodes, wires = circuit.nodes(), circuit.wires()
    _find(circuit)
    assert (circuit.nodes(), circuit.wires()) == (nodes, wires)


# --- Les nombres du tableau des paliers --------------------------------------


@pytest.mark.parametrize(
    ("input_count", "kept"),
    [(1, 1), (2, 10), (3, 218)],
)
def test_functions_kept_after_filters_match_the_levels_table(
    input_count: int, kept: int
) -> None:
    # Règle : cahier, « Les paliers » : parmi toutes les fonctions à 1 sortie,
    # 1 (palier 1), 10 (palier 2) et 218 (palier 3) restent après les filtres.
    function_count = 1 << (1 << input_count)
    accepted = [
        function
        for function in range(function_count)
        if not rejections_of_table(TruthTable(Status.STABLE, (function,)), input_count)
    ]
    assert len(accepted) == kept


# --- Comparaison avec un calcul indépendant, combinaison par combinaison -----


def _bit(table: int, combination: int) -> int:
    return (table >> combination) & 1


def _expected(outputs: tuple[int, ...], input_count: int) -> tuple[Rejection, ...]:
    """Les mêmes filtres, écrits le plus simplement possible (aucun code partagé)."""
    combinations = range(1 << input_count)
    inputs = range(input_count)
    rows = [tuple(_bit(out, k) for k in combinations) for out in outputs]
    unused = any(
        all(
            _bit(out, k) == _bit(out, k ^ (1 << i))
            for out in outputs
            for k in combinations
        )
        for i in inputs
    )
    constant = any(len(set(row)) == 1 for row in rows)
    duplicate = len(set(rows)) < len(rows)
    copied = any(
        all(_bit(out, k) == (k >> i) & 1 for k in combinations)
        for out in outputs
        for i in inputs
    )
    flags = (
        (Rejection.UNUSED_INPUT, unused),
        (Rejection.CONSTANT_OUTPUT, constant),
        (Rejection.DUPLICATE_OUTPUTS, duplicate),
        (Rejection.COPIED_INPUT, copied),
    )
    return tuple(reason for reason, flag in flags if flag)


@pytest.mark.parametrize(
    ("input_count", "output_count"),
    [(0, 1), (1, 1), (2, 1), (3, 1), (0, 2), (1, 2), (2, 2)],
)
def test_all_small_tables_match_the_independent_computation(
    input_count: int, output_count: int
) -> None:
    # Règle : les 4 filtres de table, sur TOUTES les tables possibles de ces tailles.
    function_count = 1 << (1 << input_count)
    for outputs in itertools.product(range(function_count), repeat=output_count):
        table = TruthTable(Status.STABLE, outputs)
        assert rejections_of_table(table, input_count) == _expected(
            outputs, input_count
        ), f"{input_count} entrée(s), tables {outputs}"


@pytest.mark.parametrize("input_count", [3, 4, 5])
def test_random_big_tables_match_the_independent_computation(
    input_count: int,
) -> None:
    # Règle : mêmes filtres sur des tables plus grandes, tirées au hasard avec une
    # graine fixe (résultat reproductible). Beaucoup de tables sont refusées pour
    # plusieurs motifs à la fois.
    rng = random.Random(input_count)
    combination_count = 1 << input_count
    for _ in range(300):
        outputs = tuple(
            rng.getrandbits(combination_count) for _ in range(rng.randint(1, 3))
        )
        table = TruthTable(Status.STABLE, outputs)
        assert rejections_of_table(table, input_count) == _expected(
            outputs, input_count
        )
