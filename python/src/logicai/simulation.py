"""Simulation par tops d'un circuit.

À chaque top, toutes les NAND recalculent leur sortie en même temps, à partir des
valeurs du top précédent : chaque NAND a un retard de 1 top.

Les signaux sont des entiers Python. Avec un masque d'un seul bit (``1``), on simule
une seule combinaison d'entrées. Avec un masque plus large, on en simule plusieurs à
la fois, une par bit (simulation bit-parallèle). Le calcul est le même dans les deux
cas : une NAND vaut ``~(a & b) & masque``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto
from typing import NamedTuple

from logicai.circuit import Circuit, NodeKind, Pin
from logicai.errors import SimulationError

# Les deux puits d'une NAND et l'unique puits d'une sortie du circuit.
_FIRST_SINK = 0
_SECOND_SINK = 1
_OUTPUT_SINK = 0

# Valeur d'un puits non relié, et valeur de départ de toutes les NAND.
_UNWIRED_VALUE = 0
_INITIAL_VALUE = 0

# Un circuit sans boucle de profondeur d <= T_max est figé après d tops ; il faut
# un top de plus pour constater que plus rien ne change.
_CONFIRMATION_TICKS = 1


class Status(Enum):
    """Résultat d'une simulation : le circuit s'est stabilisé ou non."""

    STABLE = auto()
    UNSTABLE = auto()


@dataclass(frozen=True)
class SettleResult:
    """Résultat de ``settle``.

    ``state`` donne la valeur de chaque NAND et ``outputs`` celle de chaque sortie
    du circuit, dans l'ordre de création. Si le statut est ``UNSTABLE``, ce sont les
    valeurs après le dernier top calculé : elles ne sont pas significatives.
    ``ticks`` est le nombre de tops calculés, top de confirmation compris.
    """

    status: Status
    state: tuple[int, ...]
    outputs: tuple[int, ...]
    ticks: int


class _Origin(Enum):
    """D'où vient la valeur lue par un puits."""

    NONE = auto()  # puits non relié : vaut 0
    NAND = auto()  # une NAND : sa valeur au top précédent
    INPUT = auto()  # une entrée du circuit : la valeur appliquée, sans retard


class _Link(NamedTuple):
    """Ce que lit un puits : une origine, et la position de la source dans celle-ci."""

    origin: _Origin
    position: int


class _Plan(NamedTuple):
    """Le circuit préparé pour le calcul : ce que lit chaque NAND et chaque sortie."""

    nand_links: tuple[tuple[_Link, _Link], ...]
    output_links: tuple[_Link, ...]


_NO_LINK = _Link(_Origin.NONE, _UNWIRED_VALUE)

# Seul endroit qui dit quels types de nœuds peuvent servir de source au calcul.
# Un nouveau type (composant, CLK) s'ajoutera ici.
_ORIGIN_OF_KIND: dict[NodeKind, _Origin] = {
    NodeKind.NAND: _Origin.NAND,
    NodeKind.INPUT: _Origin.INPUT,
}


def max_ticks(circuit: Circuit) -> int:
    """Renvoie le nombre maximal de tops : T_max + 1, avec T_max = nombre de NAND."""
    return circuit.nand_count() + _CONFIRMATION_TICKS


def tick(
    circuit: Circuit,
    input_values: Sequence[int],
    mask: int,
    state: Sequence[int] | None = None,
) -> tuple[int, ...]:
    """Renvoie l'état après un seul top (une valeur par NAND).

    ``state`` est l'état au top précédent ; sans lui, toutes les NAND valent 0.
    """
    plan, inputs, current = _prepare(circuit, input_values, mask, state)
    return _advance(plan, current, inputs, mask)


def settle(
    circuit: Circuit,
    input_values: Sequence[int],
    mask: int,
    state: Sequence[int] | None = None,
) -> SettleResult:
    """Fait tourner des tops, sur des entrées figées, jusqu'à la stabilité.

    On calcule au plus T_max + 1 tops. Le circuit est STABLE dès qu'un top ne change
    aucune valeur ; il est UNSTABLE s'il change encore au top T_max + 1.
    """
    plan, inputs, current = _prepare(circuit, input_values, mask, state)
    limit = max_ticks(circuit)
    for tick_number in range(1, limit + 1):
        following = _advance(plan, current, inputs, mask)
        if following == current:
            outputs = _read_outputs(plan, current, inputs)
            return SettleResult(Status.STABLE, current, outputs, tick_number)
        current = following
    return SettleResult(
        Status.UNSTABLE, current, _read_outputs(plan, current, inputs), limit
    )


def _prepare(
    circuit: Circuit,
    input_values: Sequence[int],
    mask: int,
    state: Sequence[int] | None,
) -> tuple[_Plan, tuple[int, ...], tuple[int, ...]]:
    """Contrôle les données puis prépare le plan, les entrées et l'état de départ."""
    _check_mask(mask)
    inputs = tuple(input_values)
    if len(inputs) != len(circuit.inputs()):
        raise SimulationError(
            f"Le circuit a {len(circuit.inputs())} entrée(s), "
            f"mais {len(inputs)} valeur(s) sont données."
        )
    _check_range(inputs, mask, "d'entrée")

    nand_count = circuit.nand_count()
    if state is None:
        current = (_INITIAL_VALUE,) * nand_count
    else:
        current = tuple(state)
        if len(current) != nand_count:
            raise SimulationError(
                f"Le circuit a {nand_count} NAND, "
                f"mais l'état donne {len(current)} valeur(s)."
            )
        _check_range(current, mask, "d'état")
    return _compile(circuit), inputs, current


def _check_mask(mask: int) -> None:
    """Refuse un masque qui n'est pas fait uniquement de bits à 1 (1, 3, 15, 255...)."""
    if mask <= 0 or mask & (mask + 1) != 0:
        raise SimulationError(
            f"Le masque {mask} est invalide : il doit être fait uniquement de bits à 1."
        )


def _check_range(values: Sequence[int], mask: int, label: str) -> None:
    """Refuse une valeur qui ne tient pas dans le masque."""
    for value in values:
        if not 0 <= value <= mask:
            raise SimulationError(
                f"La valeur {label} {value} ne tient pas dans le masque {mask}."
            )


def _compile(circuit: Circuit) -> _Plan:
    """Traduit le circuit en positions, pour ne pas relire les câbles à chaque top."""
    positions: dict[_Origin, dict[int, int]] = {
        _Origin.NAND: {
            node.node_id: position
            for position, node in enumerate(
                n for n in circuit.nodes() if n.kind is NodeKind.NAND
            )
        },
        _Origin.INPUT: {
            node_id: position for position, node_id in enumerate(circuit.inputs())
        },
    }
    nand_links = tuple(
        (
            _link(circuit, Pin(nand_id, _FIRST_SINK), positions),
            _link(circuit, Pin(nand_id, _SECOND_SINK), positions),
        )
        for nand_id in positions[_Origin.NAND]
    )
    output_links = tuple(
        _link(circuit, Pin(output_id, _OUTPUT_SINK), positions)
        for output_id in circuit.outputs()
    )
    return _Plan(nand_links, output_links)


def _link(
    circuit: Circuit, sink: Pin, positions: dict[_Origin, dict[int, int]]
) -> _Link:
    """Dit ce que lit un puits : rien, une NAND ou une entrée."""
    source = circuit.source_of(sink)
    if source is None:
        return _NO_LINK
    kind = circuit.node(source.node_id).kind
    origin = _ORIGIN_OF_KIND.get(kind)
    if origin is None:
        raise SimulationError(
            f"Le nœud {source.node_id} ({kind.name}) ne peut pas servir de source "
            "dans la simulation."
        )
    return _Link(origin, positions[origin][source.node_id])


def _value(link: _Link, state: tuple[int, ...], inputs: tuple[int, ...]) -> int:
    """Lit la valeur d'un puits : NAND au top précédent, entrée actuelle, ou 0."""
    if link.origin is _Origin.NAND:
        return state[link.position]
    if link.origin is _Origin.INPUT:
        return inputs[link.position]
    return _UNWIRED_VALUE


def _advance(
    plan: _Plan, state: tuple[int, ...], inputs: tuple[int, ...], mask: int
) -> tuple[int, ...]:
    """Renvoie le top suivant : toutes les NAND lisent l'ancien état, en même temps."""
    return tuple(
        ~(_value(first, state, inputs) & _value(second, state, inputs)) & mask
        for first, second in plan.nand_links
    )


def _read_outputs(
    plan: _Plan, state: tuple[int, ...], inputs: tuple[int, ...]
) -> tuple[int, ...]:
    """Lit les sorties du circuit : la valeur de leur source, sans retard."""
    return tuple(_value(link, state, inputs) for link in plan.output_links)
