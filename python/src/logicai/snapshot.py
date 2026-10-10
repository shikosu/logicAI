"""Relevé des valeurs 0/1 d'un circuit à un top donné, pour l'afficher.

Python fait la simulation, Unity colore les câbles (cahier, « Architecture Python /
Unity ») : ce module produit, pour un circuit et des entrées données, la valeur de
chaque nœud et de chaque câble. C'est le contenu du message « etat » du cahier (« les
valeurs 0/1 de chaque fil à un top donné »).

La valeur d'un câble est celle de sa source : une NAND vaut son état à ce top, une
entrée vaut la valeur appliquée, une sortie lit sa source (ou 0 si elle n'est pas
reliée). Les circuits qui contiennent des composants ne sont pas pris en charge : on ne
calcule pas leurs valeurs internes (il faudrait les aplatir et suivre chaque fil).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from logicai.circuit import Circuit, NodeKind, Pin
from logicai.errors import SnapshotError
from logicai.simulation import Status, settle, tick

# Une seule combinaison d'entrées : les signaux valent 0 ou 1.
_SINGLE_COMBINATION_MASK = 1


@dataclass(frozen=True)
class Snapshot:
    """Les valeurs d'un circuit à un top.

    ``node_values`` suit l'ordre de ``circuit.nodes()`` et ``wire_values`` celui de
    ``circuit.wires()``. ``stable`` dit si le circuit ne change plus à partir de ce top.
    """

    top: int
    stable: bool
    node_values: tuple[int, ...]
    wire_values: tuple[int, ...]


def snapshot_at_tick(
    circuit: Circuit,
    input_values: Sequence[int],
    ticks: int,
    state: Sequence[int] | None = None,
) -> Snapshot:
    """Relève les valeurs après exactement ``ticks`` tops, entrées figées.

    On part de ``state`` (sinon toutes les NAND à 0). Sert à voir un circuit instable
    osciller, top par top.
    """
    _refuse_components(circuit)
    if ticks < 0:
        raise SnapshotError(f"Le nombre de tops {ticks} est négatif.")
    current = tuple(state) if state is not None else (0,) * circuit.nand_count()
    for _ in range(ticks):
        current = tick(circuit, input_values, _SINGLE_COMBINATION_MASK, current)
    following = tick(circuit, input_values, _SINGLE_COMBINATION_MASK, current)
    return _build(circuit, input_values, current, ticks, stable=following == current)


def settled_snapshot(
    circuit: Circuit, input_values: Sequence[int], state: Sequence[int] | None = None
) -> Snapshot:
    """Relève les valeurs une fois le circuit stabilisé (règle T_max + 1 de ``settle``).

    Si le circuit est instable, ce sont les valeurs du dernier top calculé et
    ``stable`` vaut ``False``.
    """
    _refuse_components(circuit)
    result = settle(circuit, input_values, _SINGLE_COMBINATION_MASK, state)
    return _build(
        circuit,
        input_values,
        result.state,
        result.ticks,
        stable=result.status is Status.STABLE,
    )


def sequence_snapshots(
    circuit: Circuit, steps: Sequence[Sequence[int]]
) -> tuple[Snapshot, ...]:
    """Relève les valeurs à la fin de chaque pas d'une séquence d'entrées.

    L'état est conservé d'un pas au suivant, comme dans ``run_sequence`` : c'est ce qui
    permet de voir une bascule se souvenir.
    """
    snapshots: list[Snapshot] = []
    state: tuple[int, ...] | None = None
    for vector in steps:
        snapshot = settled_snapshot(circuit, vector, state)
        state = _state_of(circuit, snapshot)
        snapshots.append(snapshot)
    return tuple(snapshots)


def _refuse_components(circuit: Circuit) -> None:
    """Refuse un circuit qui contient des composants (valeurs non calculées)."""
    for node in circuit.nodes():
        if node.kind is NodeKind.COMPONENT:
            raise SnapshotError(
                f"Le nœud {node.node_id} est un composant ({node.component_ref}) : "
                "les valeurs d'un circuit avec composants ne sont pas calculées."
            )


def _state_of(circuit: Circuit, snapshot: Snapshot) -> tuple[int, ...]:
    """Retrouve l'état des NAND (leur valeur, dans l'ordre de création) d'un relevé."""
    return tuple(
        value
        for node, value in zip(circuit.nodes(), snapshot.node_values, strict=True)
        if node.kind is NodeKind.NAND
    )


def _build(
    circuit: Circuit,
    input_values: Sequence[int],
    state: Sequence[int],
    top: int,
    *,
    stable: bool,
) -> Snapshot:
    """Renvoie la valeur de chaque nœud puis de chaque câble."""
    inputs = dict(zip(circuit.inputs(), input_values, strict=True))
    nand_values = iter(state)
    values: dict[int, int] = {}
    for node in circuit.nodes():
        if node.kind is NodeKind.NAND:
            values[node.node_id] = next(nand_values)
        elif node.kind is NodeKind.INPUT:
            values[node.node_id] = inputs[node.node_id]
    for output_id in circuit.outputs():
        source = circuit.source_of(Pin(output_id, 0))
        values[output_id] = values[source.node_id] if source is not None else 0
    return Snapshot(
        top=top,
        stable=stable,
        node_values=tuple(values[node.node_id] for node in circuit.nodes()),
        wire_values=tuple(values[wire.source.node_id] for wire in circuit.wires()),
    )
