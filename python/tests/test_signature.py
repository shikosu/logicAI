"""Tests de la signature canonique : entrées permutées = même signature."""

import itertools
import math
import random
from collections.abc import Callable
from functools import reduce

import pytest

from logicai.behavior import TruthTable, input_patterns
from logicai.errors import SignatureError
from logicai.signature import (
    MAX_ARRANGEMENTS,
    Signature,
    canonical_form,
    known_name,
    permute_inputs,
)
from logicai.simulation import Status

SEED = 20261010  # graine fixe : les tirages au hasard sont reproductibles


# --- Aides : définitions lentes mais évidentes, pour vérifier le vrai code ------------


def _stable(*outputs: int) -> TruthTable:
    return TruthTable(Status.STABLE, tuple(outputs))


def _signature(input_count: int, *outputs: int) -> Signature:
    return canonical_form(_stable(*outputs), input_count).signature


def _reference_permute(table: int, input_count: int, order: tuple[int, ...]) -> int:
    """Définition bit à bit : l'entrée j du résultat est l'entrée order[j] d'origine."""
    result = 0
    for new_k in range(2**input_count):
        old_k = sum(((new_k >> j) & 1) << order[j] for j in range(input_count))
        result |= ((table >> old_k) & 1) << new_k
    return result


def _burnside_class_count(input_count: int) -> int:
    """Compte les fonctions à n entrées, à permutation près (lemme de Burnside).

    Calcul indépendant du code testé : on compte les cycles de chaque permutation sur
    les 2**n combinaisons d'entrées.
    """
    total = 0
    for perm in itertools.permutations(range(input_count)):
        image = [
            sum(((k >> j) & 1) << perm[j] for j in range(input_count))
            for k in range(2**input_count)
        ]
        seen = [False] * len(image)
        cycles = 0
        for start in range(len(image)):
            if not seen[start]:
                cycles += 1
                k = start
                while not seen[k]:
                    seen[k] = True
                    k = image[k]
        total += 2**cycles
    return total // math.factorial(input_count)


def _parity_table(input_count: int) -> int:
    return reduce(lambda a, b: a ^ b, input_patterns(input_count), 0)


def _majority_table(input_count: int) -> int:
    bits = "".join(
        "1" if k.bit_count() > input_count // 2 else "0"
        for k in reversed(range(2**input_count))
    )
    return int(bits, 2)


def _inner_product_table(pair_count: int) -> int:
    """Renvoie x0.x1 XOR x2.x3 XOR ... (produit scalaire de ``pair_count`` paires).

    Toutes les entrées ont le même poids, mais deux entrées ne sont symétriques que
    par paires.
    """
    patterns = input_patterns(2 * pair_count)
    return reduce(
        lambda a, b: a ^ b,
        (patterns[2 * p] & patterns[2 * p + 1] for p in range(pair_count)),
        0,
    )


def _inverse(order: tuple[int, ...]) -> tuple[int, ...]:
    inverse = [0] * len(order)
    for position, value in enumerate(order):
        inverse[value] = position
    return tuple(inverse)


# --- input_patterns pour beaucoup d'entrées -------------------------------------------


@pytest.mark.parametrize("input_count", range(0, 10))
def test_input_patterns_match_the_definition(input_count: int) -> None:
    # Règle vérifiée : prompt phase 1, section C (l'entrée i vaut le bit i de k),
    # pour la construction par doublement qui permet de monter à beaucoup d'entrées.
    expected = tuple(
        sum(((k >> i) & 1) << k for k in range(2**input_count))
        for i in range(input_count)
    )
    assert input_patterns(input_count) == expected


# --- Permuter les entrées -------------------------------------------------------------


def test_swapping_inputs_moves_a_and_not_b_to_not_a_and_b() -> None:
    # Règle vérifiée : cahier, « Composants équivalents » : A ET NON B devient
    # NON A ET B.
    a_and_not_b = 0b0010
    not_a_and_b = 0b0100
    assert permute_inputs((a_and_not_b,), 2, (1, 0)) == (not_a_and_b,)
    assert permute_inputs((a_and_not_b,), 2, (0, 1)) == (a_and_not_b,)


def test_permute_inputs_matches_the_definition() -> None:
    # Règle vérifiée : décision de Téo (entrées permutées = même composant) ; la
    # permutation rapide par échanges de bits donne la définition bit à bit.
    rng = random.Random(SEED)
    for _ in range(60):
        input_count = rng.randint(1, 6)
        order = list(range(input_count))
        rng.shuffle(order)
        tables = tuple(
            rng.getrandbits(2**input_count) for _ in range(rng.randint(1, 3))
        )
        expected = tuple(
            _reference_permute(t, input_count, tuple(order)) for t in tables
        )
        assert permute_inputs(tables, input_count, order) == expected


def test_permuting_then_inverse_permuting_gives_the_original() -> None:
    # Règle vérifiée : décision de Téo (permuter les entrées ne change pas la fonction).
    rng = random.Random(SEED + 1)
    for _ in range(40):
        input_count = rng.randint(1, 7)
        order = list(range(input_count))
        rng.shuffle(order)
        tables = (rng.getrandbits(2**input_count), rng.getrandbits(2**input_count))
        permuted = permute_inputs(tables, input_count, order)
        assert permute_inputs(permuted, input_count, _inverse(tuple(order))) == tables


@pytest.mark.parametrize("order", [(0,), (0, 0), (0, 2), (1, 2), (0, 1, 2)])
def test_order_that_is_not_a_permutation_is_refused(order: tuple[int, ...]) -> None:
    # Règle vérifiée : CLAUDE.md (un refus dit ce qui est refusé et pourquoi).
    with pytest.raises(SignatureError):
        permute_inputs((0b0110,), 2, order)


# --- La décision de Téo ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "swapped"),
    [(0b0010, 0b0100), (0b1011, 0b1101)],
    ids=["A-ET-NON-B", "A-OU-NON-B"],
)
def test_inputs_swapped_is_one_single_discovery(table: int, swapped: int) -> None:
    # Règle vérifiée : cahier, « Composants équivalents » et réponse de Téo
    # (« A ET NON B » et « NON A ET B » ne sont qu'un seul composant).
    assert _signature(2, table) == _signature(2, swapped)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(0b1000, 0b0001, id="AND-NOR"),
        pytest.param(0b1110, 0b0111, id="OR-NAND"),
        pytest.param(0b1000, 0b0010, id="AND-ANDNOT"),
        pytest.param(0b0110, 0b1001, id="XOR-XNOR"),
    ],
)
def test_negating_inputs_is_not_merged(first: int, second: int) -> None:
    # Règle vérifiée : lecture (a) validée du plan : seules les entrées échangées
    # fusionnent ; AND et NOR restent deux découvertes (cahier, « Les paliers »).
    assert _signature(2, first) != _signature(2, second)


@pytest.mark.parametrize("input_count", [0, 1, 2, 3, 4])
def test_number_of_classes_matches_the_burnside_count(input_count: int) -> None:
    # Règle vérifiée : décision de Téo ; ni trop de fusions ni trop peu : le nombre de
    # signatures distinctes est le nombre de fonctions à permutation près (4, 12...).
    function_count = 2 ** (2**input_count)
    signatures = {_signature(input_count, table) for table in range(function_count)}
    assert len(signatures) == _burnside_class_count(input_count)


def test_burnside_reference_gives_the_known_small_values() -> None:
    # Règle vérifiée : garde-fou sur l'aide de test ci-dessus (calcul à la main :
    # 2 fonctions sans entrée, 4 avec une, 12 avec deux, 80 avec trois).
    assert [_burnside_class_count(n) for n in range(4)] == [2, 4, 12, 80]


def test_the_cahiers_ten_two_input_functions_make_eight_discoveries() -> None:
    # Règle vérifiée : cahier, « Les paliers » (palier 2 : 16 fonctions, 10 restent
    # après les filtres) ; avec la décision de Téo, ces 10 fonctions font 8 découvertes.
    names = [known_name(_signature(2, table)) for table in range(16)]
    named = [name for name in names if name is not None]
    assert len(named) == 10
    assert len(set(named)) == 8


# --- Forme canonique ------------------------------------------------------------------


def test_every_permutation_of_the_inputs_gives_the_same_signature() -> None:
    # Règle vérifiée : décision de Téo (entrées permutées = même signature), par force
    # brute : pour des fonctions tirées au hasard jusqu'à 4 entrées, TOUTES les
    # permutations des entrées donnent la même signature. (La signature est la plus
    # petite table parmi des ordres candidats communs à toute la famille, pas parmi
    # toutes les permutations : voir la docstring du module.)
    rng = random.Random(SEED + 2)
    for _ in range(80):
        input_count = rng.randint(1, 4)
        tables = tuple(
            rng.getrandbits(2**input_count) for _ in range(rng.randint(1, 2))
        )
        expected = _signature(input_count, *tables)
        for perm in itertools.permutations(range(input_count)):
            permuted = permute_inputs(tables, input_count, perm)
            assert _signature(input_count, *permuted) == expected


def test_input_order_leads_to_the_signature() -> None:
    # Règle vérifiée : contrat de ``CanonicalForm`` (input_order explique la signature).
    rng = random.Random(SEED + 3)
    for _ in range(60):
        input_count = rng.randint(1, 7)
        tables = tuple(
            rng.getrandbits(2**input_count) for _ in range(rng.randint(1, 3))
        )
        form = canonical_form(_stable(*tables), input_count)
        assert form.exact is True
        assert (
            permute_inputs(tables, input_count, form.input_order)
            == form.signature.outputs
        )


def test_permuted_functions_share_one_signature() -> None:
    # Règle vérifiée : décision de Téo, sur des fonctions tirées au hasard (graine
    # fixe), à une, deux ou trois sorties, jusqu'à 8 entrées.
    rng = random.Random(SEED + 4)
    for _ in range(80):
        input_count = rng.randint(2, 8)
        tables = tuple(
            rng.getrandbits(2**input_count) for _ in range(rng.randint(1, 3))
        )
        order = list(range(input_count))
        rng.shuffle(order)
        shuffled = permute_inputs(tables, input_count, order)
        assert _signature(input_count, *tables) == _signature(input_count, *shuffled)


def test_permutation_applies_to_all_outputs_together() -> None:
    # Règle vérifiée : décision du plan (une permutation d'entrées s'applique à toutes
    # les sorties à la fois) : permuter une seule des deux sorties change la fonction.
    both_swapped = (
        0b0100,
        0b1101,
    )  # A ET NON B -> NON A ET B, A OU NON B -> NON A OU B
    only_first_swapped = (0b0100, 0b1011)
    original = (0b0010, 0b1011)
    assert _signature(2, *original) == _signature(2, *both_swapped)
    assert _signature(2, *original) != _signature(2, *only_first_swapped)


def test_output_order_matters() -> None:
    # Règle vérifiée : décision de Téo (les sorties ne sont pas permutées : leur
    # ordre fait partie du composant).
    and_table, or_table = 0b1000, 0b1110
    assert _signature(2, and_table, or_table) != _signature(2, or_table, and_table)


def test_no_input_and_one_input() -> None:
    # Règle vérifiée : cahier, « Les paliers » (palier 1 : une seule entrée).
    constant = canonical_form(_stable(0b1), 0)
    assert constant.signature == Signature(0, (0b1,))
    assert constant.input_order == ()
    not_gate = canonical_form(_stable(0b01), 1)
    assert not_gate.signature == Signature(1, (0b01,))
    assert not_gate.input_order == (0,)


# --- Beaucoup d'entrées ---------------------------------------------------------------


@pytest.mark.parametrize("input_count", [12, 15])
@pytest.mark.parametrize(
    "make_table",
    [_parity_table, _majority_table],
    ids=["parite", "majorite"],
)
def test_symmetric_function_with_many_inputs_is_fast_and_exact(
    input_count: int, make_table: Callable[[int], int]
) -> None:
    # Règle vérifiée : réponse de Téo (jusqu'à 15 entrées, puis sans limite) : les 15!
    # permutations ne sont pas essayées, car toutes les entrées sont interchangeables.
    table = make_table(input_count)
    form = canonical_form(_stable(table), input_count)
    assert form.exact is True
    assert form.signature.outputs == (table,)  # une fonction symétrique ne change pas
    rng = random.Random(SEED + 5)
    order = list(range(input_count))
    rng.shuffle(order)
    shuffled = permute_inputs((table,), input_count, order)
    assert _signature(input_count, shuffled[0]) == form.signature


def test_arrangements_that_fit_are_still_exact() -> None:
    # Règle vérifiée : décision du plan (la méthode reste exacte tant que les ordres à
    # essayer tiennent dans MAX_ARRANGEMENTS). Produit scalaire de 4 paires : 8 entrées
    # de même poids, 4 classes de 2 entrées symétriques, 8!/2^4 = 2520 ordres.
    assert MAX_ARRANGEMENTS >= 2520
    table = _inner_product_table(4)
    form = canonical_form(_stable(table), 8)
    assert form.exact is True
    rng = random.Random(SEED + 6)
    order = list(range(8))
    rng.shuffle(order)
    shuffled = permute_inputs((table,), 8, order)
    assert _signature(8, shuffled[0]) == form.signature


def test_too_many_arrangements_keeps_the_original_order() -> None:
    # Règle vérifiée : décision du plan (au-delà de MAX_ARRANGEMENTS la fusion n'est
    # plus garantie : on le dit, et on garde l'ordre d'origine). Produit scalaire de
    # 5 paires : 10!/2^5 = 113 400 ordres.
    table = _inner_product_table(5)
    form = canonical_form(_stable(table), 10)
    assert form.exact is False
    assert form.input_order == tuple(range(10))
    assert form.signature == Signature(10, (table,))


# --- Données invalides ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "input_count"),
    [
        pytest.param(TruthTable(Status.UNSTABLE, (0b0110,)), 2, id="instable"),
        pytest.param(_stable(0b10000), 2, id="trop-grande"),
        pytest.param(_stable(-1), 2, id="negative"),
        pytest.param(_stable(0b1), -1, id="entrees-negatives"),
    ],
)
def test_invalid_table_is_refused(table: TruthTable, input_count: int) -> None:
    # Règle vérifiée : cahier, « Les trois cas détectés » (un circuit instable est
    # rejeté, il n'a pas de signature) ; CLAUDE.md (refus explicite).
    with pytest.raises(SignatureError):
        canonical_form(table, input_count)


# --- Noms connus ----------------------------------------------------------------------

_NAMED_FUNCTIONS = [
    ("NOT", 1, 0b01),
    ("AND", 2, 0b1000),
    ("OR", 2, 0b1110),
    ("NAND", 2, 0b0111),
    ("NOR", 2, 0b0001),
    ("XOR", 2, 0b0110),
    ("XNOR", 2, 0b1001),
    ("ANDNOT", 2, 0b0010),
    ("ORNOT", 2, 0b1011),
    ("MAJ", 3, 0b11101000),
    ("MUX", 3, 0b11100100),
]


@pytest.mark.parametrize(("name", "input_count", "table"), _NAMED_FUNCTIONS)
def test_known_gate_gets_its_name_whatever_the_input_order(
    name: str, input_count: int, table: int
) -> None:
    # Règle vérifiée : cahier, « Nom » (si la signature correspond à une porte connue,
    # elle prend son nom) ; décision de Téo : quel que soit l'ordre des entrées.
    for order in itertools.permutations(range(input_count)):
        (permuted,) = permute_inputs((table,), input_count, order)
        assert known_name(_signature(input_count, permuted)) == name


def test_each_known_name_has_its_own_signature() -> None:
    # Règle vérifiée : cahier, « Nom » (un nom par fonction).
    names = [known_name(_signature(n, table)) for _, n, table in _NAMED_FUNCTIONS]
    assert names == [name for name, _, _ in _NAMED_FUNCTIONS]


@pytest.mark.parametrize(
    ("input_count", "outputs"),
    [
        pytest.param(2, (0b0000,), id="constante-0"),
        pytest.param(2, (0b1111,), id="constante-1"),
        pytest.param(2, (0b1010,), id="recopie-A"),
        pytest.param(3, (0b11111110,), id="OU-a-3-entrees"),
        pytest.param(2, (0b1000, 0b1110), id="deux-sorties"),
    ],
)
def test_unknown_function_has_no_name(
    input_count: int, outputs: tuple[int, ...]
) -> None:
    # Règle vérifiée : cahier, « Nom » (sinon elle reçoit un numéro : pas de nom connu).
    assert known_name(_signature(input_count, *outputs)) is None
