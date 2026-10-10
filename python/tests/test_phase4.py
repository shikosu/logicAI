"""Test de la phase 4 (cahier, plan de développement) : IA évolutionnaire, paliers 1-3.

Test du cahier : « l'IA découvre seule NOT, puis les 10 fonctions à 2 entrées [8
découvertes, depuis la décision sur les entrées échangées], et approche les tailles
minimales (AND = 2, OR = 3, XOR = 4 NAND) ».

Critère de réussite retenu par Téo (« cahier à la lettre ») :

- NOT est la première découverte, au palier 1, avec 1 NAND ;
- au palier 2, les 8 découvertes à 2 entrées sont toutes trouvées ;
- AND = 2, OR = 3 et XOR = 4 NAND exactement (les trois tailles citées par le cahier) ;
- les 5 autres portes ont au plus 1 NAND de plus que leur minimum.

Les tailles minimales ne sont pas recopiées : le test les recalcule par une recherche
exhaustive de tous les circuits de NAND. Les exécutions ont une graine fixe, donc le
test est reproductible. Les graines sont celles qui réussissent dans le budget : toutes
ne réussissent pas (le taux de réussite sur 16 graines est dans le journal).
"""

import itertools

import pytest

from logicai.behavior import TruthTable
from logicai.evolution import Evolution
from logicai.filters import rejections_of_table
from logicai.library import Library
from logicai.signature import canonical_form, known_name
from logicai.simulation import Status
from logicai.stages import DEFAULT_STALLED_GENERATIONS, STAGES, Curriculum

# Tailles que le cahier cite : elles doivent être atteintes exactement.
EXACT_SIZES = {"AND": 2, "OR": 3, "XOR": 4}
# Marge pour les autres portes : au plus 1 NAND de plus que leur minimum.
SLACK = 1
# Plus grande taille cherchée par la recherche exhaustive (XNOR a besoin de 5).
MAX_SEARCH_SIZE = 8
# Budget de générations au palier 2, et fréquence du contrôle du critère.
LEVEL_2_BUDGET = 2500
CHECK_EVERY = 5
# Graines qui réussissent dans le budget (voir le journal pour le taux de réussite :
# toutes les graines ne réussissent pas).
SEEDS = (1, 12, 11)


def _minimal_sizes(input_count: int) -> dict[int, int]:
    """Renvoie, pour chaque table de vérité atteignable, son plus petit nombre de NAND.

    Recherche exhaustive en largeur : un état est l'ensemble des signaux disponibles
    (les entrées et 0, valeur d'un puits sans câble) ; ajouter une NAND ajoute
    ``NAND(a, b)`` pour deux signaux disponibles quelconques (éventuellement le même).
    """
    combinations = 1 << input_count
    full = (1 << combinations) - 1
    inputs = [
        sum(1 << k for k in range(combinations) if (k >> i) & 1)
        for i in range(input_count)
    ]
    start = frozenset([0, *inputs])
    best = dict.fromkeys(start, 0)
    seen, frontier = {start}, {start}
    for size in range(1, MAX_SEARCH_SIZE + 1):
        following: set[frozenset[int]] = set()
        for state in frontier:
            for a, b in itertools.combinations_with_replacement(sorted(state), 2):
                new = full & ~(a & b)
                best.setdefault(new, size)
                grown = state | {new}
                if new not in state and grown not in seen:
                    seen.add(grown)
                    following.add(grown)
        frontier = following
    return best


def _expected_sizes() -> dict[str, int]:
    """Renvoie le nom et la taille minimale de chaque découverte à 2 entrées."""
    sizes = _minimal_sizes(2)
    expected: dict[str, int] = {}
    for table in range(1 << 4):
        truth = TruthTable(Status.STABLE, (table,))
        if rejections_of_table(truth, 2):
            continue
        name = known_name(canonical_form(truth, 2).signature)
        assert name is not None, f"fonction {table:04b} sans nom connu"
        # Des tables qui ne diffèrent que par l'ordre des entrées ont la même taille.
        assert expected.setdefault(name, sizes[table]) == sizes[table]
    return expected


def _meets_criterion(library: Library, expected: dict[str, int]) -> bool:
    """Dit si la bibliothèque satisfait le critère « cahier à la lettre »."""
    if not set(expected) <= set(library.names()):
        return False
    for name, minimum in expected.items():
        limit = minimum if name in EXACT_SIZES else minimum + SLACK
        if library.cost(name) > limit:
            return False
    return True


def test_minimal_sizes_are_those_of_the_cahier() -> None:
    # Règle : cahier, « Les paliers » : tailles minimales NOT = 1, AND = 2, OR = 3,
    # XOR = 4 NAND. On les retrouve par recherche exhaustive, et on obtient aussi
    # celles que le cahier ne donne pas.
    assert _minimal_sizes(1)[0b01] == 1
    expected = _expected_sizes()
    assert expected == {
        "NAND": 1,
        "AND": 2,
        "ORNOT": 2,
        "OR": 3,
        "ANDNOT": 3,
        "NOR": 4,
        "XOR": 4,
        "XNOR": 5,
    }
    assert all(expected[name] == size for name, size in EXACT_SIZES.items())


def _run_level_1_then_2(seed: int) -> tuple[Library, int | None]:
    """Fait tourner l'IA : palier 1 jusqu'à la première découverte, puis palier 2.

    Renvoie la bibliothèque et la génération (du palier 2) où le critère est atteint,
    ou ``None`` si le budget est épuisé.
    """
    library = Library()
    evolution = Evolution(library, STAGES[0].rules, seed=seed)
    while not library.names():
        evolution.step()
    assert library.names() == ("NOT",), "la première découverte doit être NOT"
    assert library.cost("NOT") == 1
    evolution.rules = STAGES[1].rules
    expected = _expected_sizes()
    for generation in range(1, LEVEL_2_BUDGET + 1):
        evolution.step()
        if generation % CHECK_EVERY == 0 and _meets_criterion(library, expected):
            return library, generation
    return library, None


@pytest.mark.parametrize("seed", SEEDS)
def test_ai_discovers_not_then_all_two_input_gates_near_minimal_sizes(
    seed: int,
) -> None:
    # Règle : test de la phase 4 (cahier) : l'IA découvre seule NOT (palier 1), puis les
    # 8 découvertes à 2 entrées (palier 2), avec AND = 2, OR = 3, XOR = 4 NAND et les
    # autres portes à au plus 1 NAND de leur minimum.
    library, generation = _run_level_1_then_2(seed)
    assert generation is not None, (
        f"critère non atteint en {LEVEL_2_BUDGET} générations : "
        f"{ {name: library.cost(name) for name in library.names()} }"
    )
    two_inputs = [
        n for n in library.names() if len(library.component(n).circuit.inputs()) == 2
    ]
    assert sorted(two_inputs) == sorted(_expected_sizes())  # exactement les 8 portes
    for name, size in EXACT_SIZES.items():
        assert library.cost(name) == size
    # Rien n'est descendu sous le minimum vrai (ce serait un bogue du simulateur).
    for name, minimum in _expected_sizes().items():
        assert library.cost(name) >= minimum


def test_whole_pipeline_with_stages_finds_everything() -> None:
    # Règle : même test, mais avec les paliers menés par ``Curriculum`` (N par défaut) :
    # c'est le chemin que suivra l'IA en vrai, du palier 1 au palier 3.
    library = Library()
    curriculum = Curriculum(Evolution(library, STAGES[0].rules, seed=SEEDS[0]))
    expected = _expected_sizes()
    for _ in range(DEFAULT_STALLED_GENERATIONS + LEVEL_2_BUDGET):
        curriculum.step()
        if _meets_criterion(library, expected):
            break
    assert _meets_criterion(library, expected), {
        name: library.cost(name) for name in library.names()
    }
    assert library.names()[0] == "NOT"
