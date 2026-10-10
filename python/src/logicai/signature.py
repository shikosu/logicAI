"""Signature canonique d'un circuit combinatoire, et noms des portes connues.

Décision de Téo : deux circuits dont les entrées sont seulement **échangées**
(permutées) ne font qu'une seule découverte, par exemple « A ET NON B » et « NON A ET
B ». Les sorties ne sont jamais permutées : leur ordre fait partie du composant. Nier
une entrée ne donne pas la même signature (AND et NOR restent deux découvertes).

La signature est la table de vérité dans une **forme canonique** : la même pour toutes
les fonctions qui ne diffèrent que par l'ordre de leurs entrées. Essayer les n!
permutations est impossible dès une dizaine d'entrées, donc on en essaie beaucoup moins,
sans rien perdre :

1. on range les entrées par une grandeur qui suit l'entrée quand on permute (le nombre
   de uns de chaque sortie quand l'entrée vaut 1) ; seuls les ordres compatibles avec
   ce rangement sont candidats ;
2. dans un groupe d'entrées à égalité, deux entrées « symétriques » (les échanger ne
   change pas la fonction) sont interchangeables : on n'essaie qu'un ordre pour elles ;
3. parmi les ordres candidats restants, on garde la table la plus petite.

La signature n'est donc pas la plus petite table parmi *toutes* les permutations, mais
la plus petite parmi des candidats qui sont les mêmes pour toute la famille de fonctions
équivalentes : c'est ce qui la rend identique pour elles toutes.

Si le nombre d'ordres candidats dépasse ``MAX_ARRANGEMENTS`` (cas extrême), la fusion ne
peut plus être garantie : la signature garde alors l'ordre d'origine et la forme
canonique le signale (``exact = False``). Deux fonctions différentes ne sont jamais
fusionnées par erreur ; seul un doublon peut échapper à la fusion.
"""

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

from logicai.behavior import TruthTable, full_mask, input_patterns
from logicai.errors import SignatureError
from logicai.simulation import Status

# Nombre maximal de façons d'ordonner les entrées qu'on accepte d'essayer (7!).
MAX_ARRANGEMENTS = 5040


@dataclass(frozen=True)
class Signature:
    """Table de vérité en forme canonique : le nombre d'entrées et un entier par sortie.

    Le bit k de chaque entier vaut la sortie pour la combinaison k (voir ``behavior``).
    """

    input_count: int
    outputs: tuple[int, ...]


@dataclass(frozen=True)
class CanonicalForm:
    """La signature d'un circuit, et comment y arriver.

    ``input_order[j]`` est l'indice, dans le circuit d'origine, de l'entrée qui devient
    l'entrée j de la forme canonique. ``exact`` vaut ``False`` quand il y avait trop
    d'ordres à essayer : la signature garde alors l'ordre d'origine.
    """

    signature: Signature
    input_order: tuple[int, ...]
    exact: bool


def permute_inputs(
    outputs: Sequence[int], input_count: int, order: Sequence[int]
) -> tuple[int, ...]:
    """Réordonne les entrées de tables de vérité : l'entrée j devient l'entrée order[j].

    Autrement dit, dans le résultat, l'entrée j joue le rôle de l'entrée ``order[j]`` de
    l'original. Toutes les tables (une par sortie) sont permutées de la même façon.
    """
    if sorted(order) != list(range(input_count)):
        raise SignatureError(
            f"L'ordre {tuple(order)} n'est pas une permutation "
            f"des {input_count} entrées."
        )
    patterns, full = input_patterns(input_count), full_mask(input_count)
    tables = list(outputs)
    current = list(range(input_count))
    for position, wanted in enumerate(order):
        found = current.index(wanted)
        if found != position:
            tables = [_swap_inputs(t, position, found, patterns, full) for t in tables]
            current[position], current[found] = current[found], current[position]
    return tuple(tables)


def canonical_form(table: TruthTable, input_count: int) -> CanonicalForm:
    """Renvoie la signature canonique d'une table de vérité stable."""
    _check_table(table, input_count)
    outputs = table.outputs
    identity = tuple(range(input_count))
    patterns, full = input_patterns(input_count), full_mask(input_count)

    groups = _tie_groups(outputs, patterns)
    classes = [_symmetry_classes(group, outputs, patterns, full) for group in groups]
    if _arrangement_count(classes) > MAX_ARRANGEMENTS:
        return CanonicalForm(Signature(input_count, outputs), identity, exact=False)

    # Il y a toujours au moins un ordre (sans entrée, l'ordre vide).
    orders = _candidate_orders(classes)
    best_order = orders[0]
    best_outputs = permute_inputs(outputs, input_count, best_order)
    for order in orders[1:]:
        permuted = permute_inputs(outputs, input_count, order)
        if permuted < best_outputs:
            best_order, best_outputs = order, permuted
    return CanonicalForm(Signature(input_count, best_outputs), best_order, exact=True)


def known_name(signature: Signature) -> str | None:
    """Renvoie le nom de la porte connue qui a cette signature, ou ``None``.

    Les noms servent à l'affichage uniquement (cahier, « Les paliers »).
    """
    return _KNOWN_NAMES.get(signature)


# --- Entrées : contrôle, invariants, symétries ----------------------------------


def _check_table(table: TruthTable, input_count: int) -> None:
    """Refuse une table instable, ou dont les valeurs ne tiennent pas dans 2**n bits."""
    if table.status is not Status.STABLE:
        raise SignatureError("Un circuit instable n'a pas de signature.")
    if input_count < 0:
        raise SignatureError(f"Le nombre d'entrées {input_count} est négatif.")
    full = full_mask(input_count)
    for value in table.outputs:
        if not 0 <= value <= full:
            raise SignatureError(
                f"La table {value} ne tient pas dans {1 << input_count} bits."
            )


def _swap_inputs(
    table: int, first: int, second: int, patterns: tuple[int, ...], full: int
) -> int:
    """Échange deux entrées dans une table de vérité, avec quelques opérations de bits.

    Une combinaison où ``first`` vaut 1 et ``second`` vaut 0 (ou l'inverse) change de
    position : le numéro de sa case varie de ``2**second - 2**first``.
    """
    low, high = min(first, second), max(first, second)
    goes_up = patterns[low] & (full ^ patterns[high])  # entrée basse à 1, haute à 0
    goes_down = patterns[high] & (full ^ patterns[low])  # l'inverse
    shift = (1 << high) - (1 << low)
    stay = full ^ (goes_up | goes_down)
    return (
        (table & stay) | ((table & goes_up) << shift) | ((table & goes_down) >> shift)
    )


def _tie_groups(outputs: Sequence[int], patterns: tuple[int, ...]) -> list[list[int]]:
    """Trie les entrées par un invariant, puis regroupe celles qui sont à égalité.

    L'invariant d'une entrée est, pour chaque sortie, le nombre de uns de la table
    quand cette entrée vaut 1 : il suit l'entrée quand on permute les entrées.
    """
    weights = {
        i: tuple((table & pattern).bit_count() for table in outputs)
        for i, pattern in enumerate(patterns)
    }
    ordered = sorted(weights, key=lambda i: weights[i])
    return [
        list(group) for _, group in itertools.groupby(ordered, key=weights.__getitem__)
    ]


def _symmetry_classes(
    group: list[int], outputs: Sequence[int], patterns: tuple[int, ...], full: int
) -> list[list[int]]:
    """Range les entrées d'un groupe en classes d'entrées symétriques.

    Deux entrées sont symétriques si les échanger ne change aucune sortie. C'est une
    relation d'équivalence, donc comparer à un représentant par classe suffit.
    """
    classes: list[list[int]] = []
    for candidate in group:
        for members in classes:
            representative = members[0]
            if all(
                _swap_inputs(t, representative, candidate, patterns, full) == t
                for t in outputs
            ):
                members.append(candidate)
                break
        else:
            classes.append([candidate])
    return classes


# --- Les ordres à essayer --------------------------------------------------------


def _arrangement_count(classes: list[list[list[int]]]) -> int:
    """Compte les ordres à essayer : par groupe, n! divisé par le produit des n_c!."""
    total = 1
    for group_classes in classes:
        size = sum(len(members) for members in group_classes)
        arrangements = math.factorial(size)
        for members in group_classes:
            arrangements //= math.factorial(len(members))
        total *= arrangements
    return total


def _candidate_orders(classes: list[list[list[int]]]) -> list[tuple[int, ...]]:
    """Renvoie les ordres d'entrées à essayer (un seul par ordre de classes)."""
    per_group = [_group_orders(group_classes) for group_classes in classes]
    return [
        tuple(itertools.chain.from_iterable(parts))
        for parts in itertools.product(*per_group)
    ]


def _group_orders(group_classes: list[list[int]]) -> list[tuple[int, ...]]:
    """Ordonne un groupe de toutes les façons, sans distinguer deux entrées symétriques.

    On choisit à chaque place la classe d'entrée qui s'y trouve ; deux entrées de la
    même classe étant interchangeables, on les prend dans l'ordre où elles viennent.
    """
    remaining = [len(members) for members in group_classes]
    total = sum(remaining)
    chosen: list[int] = []
    orders: list[tuple[int, ...]] = []

    def extend() -> None:
        if len(chosen) == total:
            used = [0] * len(group_classes)
            order: list[int] = []
            for label in chosen:
                order.append(group_classes[label][used[label]])
                used[label] += 1
            orders.append(tuple(order))
            return
        for label, count in enumerate(remaining):
            if count:
                remaining[label] -= 1
                chosen.append(label)
                extend()
                chosen.pop()
                remaining[label] += 1

    extend()
    return orders


# --- Noms connus -----------------------------------------------------------------

# Portes connues, avec leur table de vérité (bit k = sortie pour la combinaison k,
# l'entrée 0 étant le bit de poids faible de k). Chaque nom désigne une famille : les
# entrées permutées donnent le même nom. Cette liste est une donnée facile à étendre.
_KNOWN_FUNCTIONS: tuple[tuple[str, int, int], ...] = (
    ("NOT", 1, 0b01),
    ("AND", 2, 0b1000),
    ("OR", 2, 0b1110),
    ("NAND", 2, 0b0111),
    ("NOR", 2, 0b0001),
    ("XOR", 2, 0b0110),
    ("XNOR", 2, 0b1001),
    ("ANDNOT", 2, 0b0010),  # A ET NON B (et NON A ET B)
    ("ORNOT", 2, 0b1011),  # A OU NON B (et NON A OU B)
    ("MAJ", 3, 0b11101000),  # majorité : au moins deux entrées à 1
    ("MUX", 3, 0b11100100),  # multiplexeur 2 vers 1 : (entrée 0 ? entrée 2 : entrée 1)
)


def _build_known_names() -> dict[Signature, str]:
    """Renvoie la signature canonique de chaque porte connue, avec son nom."""
    names: dict[Signature, str] = {}
    for name, input_count, table in _KNOWN_FUNCTIONS:
        form = canonical_form(TruthTable(Status.STABLE, (table,)), input_count)
        names[form.signature] = name
    return names


_KNOWN_NAMES = _build_known_names()
