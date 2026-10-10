"""Modèle d'un circuit logique : nœuds, broches et câbles.

Un câble va toujours d'une source vers un puits, et un puits reçoit au plus un
câble (cahier des charges, « Règles du monde logique »). Ce module ne simule
rien : il garde la structure du circuit et refuse les actions interdites.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import NamedTuple

from logicai.errors import (
    SinkAlreadyConnectedError,
    SinkNotConnectedError,
    UnknownNodeError,
    UnknownPinError,
    WrongPinKindError,
)


class NodeKind(Enum):
    """Type d'un nœud. D'autres types (composant, CLK) viendront plus tard."""

    INPUT = auto()
    OUTPUT = auto()
    NAND = auto()


class PinKind(Enum):
    """Genre d'une broche : une source fournit un signal, un puits en reçoit un."""

    SOURCE = auto()
    SINK = auto()


@dataclass(frozen=True)
class Pin:
    """Une broche : l'identifiant du nœud et l'index dans son genre.

    L'index se compte séparément parmi les sources et parmi les puits du nœud.
    Le genre de la broche n'est pas écrit ici : il est donné par la place dans
    l'appel (argument « source » ou « puits » de ``connect``).

    Ce n'est pas un ``NamedTuple`` : un champ nommé ``index`` y écraserait la
    méthode ``tuple.index`` (mypy le refuse).
    """

    node_id: int
    index: int


class _PinCounts(NamedTuple):
    """Nombre de puits et de sources d'un type de nœud."""

    sinks: int
    sources: int


# Tableau de la spécification, section A : (puits, sources) de chaque type.
_PIN_COUNTS: dict[NodeKind, _PinCounts] = {
    NodeKind.INPUT: _PinCounts(sinks=0, sources=1),
    NodeKind.OUTPUT: _PinCounts(sinks=1, sources=0),
    NodeKind.NAND: _PinCounts(sinks=2, sources=1),
}

_PIN_KIND_LABEL: dict[PinKind, str] = {
    PinKind.SOURCE: "source",
    PinKind.SINK: "puits",
}


@dataclass(frozen=True)
class Node:
    """Un nœud du circuit, avec son nombre de broches de chaque genre."""

    node_id: int
    kind: NodeKind
    sink_count: int
    source_count: int

    def pin_count(self, pin_kind: PinKind) -> int:
        """Renvoie le nombre de broches du genre demandé."""
        if pin_kind is PinKind.SOURCE:
            return self.source_count
        return self.sink_count


@dataclass(frozen=True)
class Wire:
    """Un câble, de la broche source vers la broche puits."""

    source: Pin
    sink: Pin


def _describe(pin: Pin) -> str:
    """Écrit une broche sous la forme « (nœud, index) » pour les messages."""
    return f"({pin.node_id}, {pin.index})"


class Circuit:
    """Un circuit : des nœuds numérotés et des câbles entre leurs broches.

    Toute opération refusée lève une exception de la famille ``CircuitError``
    et laisse le circuit exactement comme avant.
    """

    def __init__(self) -> None:
        """Crée un circuit vide."""
        self._nodes: dict[int, Node] = {}
        # Un câble est rangé sous son puits : cela impose « un câble par puits ».
        self._wires: dict[Pin, Pin] = {}
        # Compteur jamais décrémenté : un identifiant n'est jamais réutilisé.
        self._next_id = 0

    # --- Modification -------------------------------------------------------

    def add_node(self, kind: NodeKind) -> int:
        """Ajoute un nœud et renvoie son identifiant."""
        counts = _PIN_COUNTS[kind]
        node_id = self._next_id
        self._next_id += 1
        self._nodes[node_id] = Node(
            node_id=node_id,
            kind=kind,
            sink_count=counts.sinks,
            source_count=counts.sources,
        )
        return node_id

    def remove_node(self, node_id: int) -> None:
        """Supprime un nœud, ainsi que tous les câbles qui le touchent."""
        self.node(node_id)  # lève UnknownNodeError si le nœud n'existe pas
        del self._nodes[node_id]
        self._wires = {
            sink: source
            for sink, source in self._wires.items()
            if sink.node_id != node_id and source.node_id != node_id
        }

    def connect(self, source: Pin, sink: Pin) -> None:
        """Relie une broche source à une broche puits.

        Les contrôles se font dans cet ordre, avant toute modification :
        la source (nœud puis broche), le puits (nœud puis broche), puis le
        puits déjà relié. Le premier problème trouvé est signalé.
        """
        self._check_pin(source, PinKind.SOURCE)
        self._check_pin(sink, PinKind.SINK)
        if sink in self._wires:
            raise SinkAlreadyConnectedError(
                f"Le puits {_describe(sink)} reçoit déjà un câble venant de "
                f"{_describe(self._wires[sink])} : un puits n'accepte qu'un seul câble."
            )
        self._wires[sink] = source

    def disconnect(self, sink: Pin) -> None:
        """Retire le câble qui arrive sur ce puits."""
        self._check_pin(sink, PinKind.SINK)
        if sink not in self._wires:
            raise SinkNotConnectedError(
                f"Le puits {_describe(sink)} n'a pas de câble : rien à déconnecter."
            )
        del self._wires[sink]

    # --- Lecture ------------------------------------------------------------

    def node(self, node_id: int) -> Node:
        """Renvoie le nœud demandé, ou lève ``UnknownNodeError``."""
        try:
            return self._nodes[node_id]
        except KeyError:
            raise UnknownNodeError(
                f"Le nœud {node_id} n'existe pas dans le circuit."
            ) from None

    def nodes(self) -> tuple[Node, ...]:
        """Renvoie tous les nœuds, dans leur ordre de création."""
        return tuple(self._nodes.values())

    def inputs(self) -> tuple[int, ...]:
        """Renvoie les identifiants des entrées du circuit, dans l'ordre de création."""
        return self._ids_of_kind(NodeKind.INPUT)

    def outputs(self) -> tuple[int, ...]:
        """Renvoie les identifiants des sorties du circuit, dans l'ordre de création."""
        return self._ids_of_kind(NodeKind.OUTPUT)

    def nand_count(self) -> int:
        """Renvoie le nombre de NAND du circuit."""
        return len(self._ids_of_kind(NodeKind.NAND))

    def source_of(self, sink: Pin) -> Pin | None:
        """Renvoie la source qui alimente ce puits, ou ``None`` s'il est libre."""
        return self._wires.get(sink)

    def wires(self) -> tuple[Wire, ...]:
        """Renvoie tous les câbles, dans l'ordre où ils ont été posés."""
        return tuple(
            Wire(source=source, sink=sink) for sink, source in self._wires.items()
        )

    # --- Outils internes ----------------------------------------------------

    def _ids_of_kind(self, kind: NodeKind) -> tuple[int, ...]:
        """Renvoie les identifiants des nœuds d'un type, dans l'ordre de création."""
        return tuple(n.node_id for n in self._nodes.values() if n.kind is kind)

    def _check_pin(self, pin: Pin, pin_kind: PinKind) -> None:
        """Vérifie que la broche existe, avec le genre attendu."""
        node = self.node(pin.node_id)
        if 0 <= pin.index < node.pin_count(pin_kind):
            return
        expected = _PIN_KIND_LABEL[pin_kind]
        other_kind = PinKind.SINK if pin_kind is PinKind.SOURCE else PinKind.SOURCE
        if 0 <= pin.index < node.pin_count(other_kind):
            raise WrongPinKindError(
                f"La broche {_describe(pin)} est donnée comme {expected}, mais sur "
                f"le nœud {node.node_id} ({node.kind.name}) cet index n'existe que "
                f"comme {_PIN_KIND_LABEL[other_kind]}."
            )
        raise UnknownPinError(
            f"Le nœud {node.node_id} ({node.kind.name}) n'a pas de {expected} "
            f"d'index {pin.index} (il en a {node.pin_count(pin_kind)})."
        )
