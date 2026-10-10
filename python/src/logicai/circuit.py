"""Modèle d'un circuit logique : nœuds, broches et câbles.

Un câble va toujours d'une source vers un puits, et un puits reçoit au plus un
câble (cahier des charges, « Règles du monde logique »). Ce module ne simule
rien : il garde la structure du circuit et refuse les actions interdites.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto
from typing import NamedTuple, Self

from logicai.errors import (
    InvalidInputOrderError,
    InvalidNodeError,
    SinkAlreadyConnectedError,
    SinkNotConnectedError,
    UnknownNodeError,
    UnknownPinError,
    WrongPinKindError,
)


class NodeKind(Enum):
    """Type d'un nœud. La CLK viendra plus tard."""

    INPUT = auto()
    OUTPUT = auto()
    NAND = auto()
    # Un composant est une boîte noire posée par référence : ses broches dépendent
    # de sa définition, donc elles ne sont pas dans le tableau ``_PIN_COUNTS``.
    COMPONENT = auto()


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


# Tableau de la spécification, section A : (puits, sources) de chaque type fixe.
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
    """Un nœud du circuit, avec son nombre de broches de chaque genre.

    ``component_ref`` n'est renseigné que pour un composant : c'est le nom de sa
    définition dans la bibliothèque. Un nœud incohérent ne peut pas exister.
    """

    node_id: int
    kind: NodeKind
    sink_count: int
    source_count: int
    component_ref: str | None = None

    def __post_init__(self) -> None:
        """Refuse un nœud incohérent : identifiant, type, broches ou référence."""
        if self.node_id < 0:
            raise InvalidNodeError(f"L'identifiant {self.node_id} est négatif.")
        if self.kind is NodeKind.COMPONENT:
            self._check_component()
        else:
            self._check_fixed_kind()

    def _check_component(self) -> None:
        """Un composant a un nom, et un nombre de broches positif ou nul."""
        if not self.component_ref:
            raise InvalidNodeError("Un composant doit avoir un nom de définition.")
        if self.sink_count < 0 or self.source_count < 0:
            raise InvalidNodeError(
                f"Le composant {self.component_ref} ne peut pas avoir un nombre "
                f"négatif de broches ({self.sink_count} puits, "
                f"{self.source_count} sources)."
            )

    def _check_fixed_kind(self) -> None:
        """INPUT, OUTPUT et NAND n'ont pas de référence et un nombre de broches fixe."""
        if self.component_ref is not None:
            raise InvalidNodeError(
                f"Un nœud {self.kind.name} n'a pas de définition "
                f"(référence reçue : {self.component_ref})."
            )
        counts = _PIN_COUNTS[self.kind]
        if (self.sink_count, self.source_count) != (counts.sinks, counts.sources):
            raise InvalidNodeError(
                f"Un nœud {self.kind.name} a {counts.sinks} puits et "
                f"{counts.sources} source(s), pas {self.sink_count} et "
                f"{self.source_count}."
            )

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

    @classmethod
    def from_parts(cls, nodes: Sequence[Node], wires: Sequence[Wire]) -> Self:
        """Reconstruit un circuit en gardant les identifiants des nœuds donnés.

        Sert à recharger un circuit (JSON) ou à en copier une partie. Les nœuds
        doivent être donnés dans l'ordre de création, avec des identifiants
        strictement croissants ; les câbles passent par ``connect``, donc les
        règles de câblage s'appliquent. Les identifiants suivants repartent
        après le plus grand identifiant donné : un nœud supprimé avant la copie,
        avec un identifiant plus grand que tous les autres, n'est plus connu et
        son identifiant peut donc être attribué de nouveau.
        """
        circuit = cls()
        previous_id = -1
        for node in nodes:
            if node.node_id <= previous_id:
                raise InvalidNodeError(
                    f"Les identifiants doivent être strictement croissants : "
                    f"{node.node_id} arrive après {previous_id}."
                )
            circuit._nodes[node.node_id] = node
            previous_id = node.node_id
        circuit._next_id = previous_id + 1
        for wire in wires:
            circuit.connect(wire.source, wire.sink)
        return circuit

    def copy(self) -> Self:
        """Renvoie une copie indépendante du circuit (mêmes identifiants et câbles)."""
        clone = type(self)()
        clone._nodes = dict(self._nodes)
        clone._wires = dict(self._wires)
        clone._next_id = self._next_id
        return clone

    def with_inputs_reordered(self, order: Sequence[int]) -> Self:
        """Renvoie une copie où l'entrée j joue le rôle de l'entrée ``order[j]``.

        Même convention que ``permute_inputs`` (module ``signature``) : la table de
        vérité de la copie est celle de l'original avec ses entrées permutées de la
        même façon. Les nœuds gardent leur identifiant et leur place ; seuls les câbles
        qui partent des entrées changent de source. Le circuit n'est pas modifié.
        """
        inputs = self.inputs()
        if sorted(order) != list(range(len(inputs))):
            raise InvalidInputOrderError(
                f"L'ordre {tuple(order)} n'est pas une permutation "
                f"des {len(inputs)} entrées."
            )
        new_id_of = {inputs[order[j]]: inputs[j] for j in range(len(inputs))}
        wires = [
            Wire(
                Pin(
                    new_id_of.get(wire.source.node_id, wire.source.node_id),
                    wire.source.index,
                ),
                wire.sink,
            )
            for wire in self.wires()
        ]
        return type(self).from_parts(self.nodes(), wires)

    def add_node(self, kind: NodeKind) -> int:
        """Ajoute un nœud INPUT, OUTPUT ou NAND et renvoie son identifiant."""
        if kind is NodeKind.COMPONENT:
            raise InvalidNodeError(
                "Un composant se pose avec add_component_node : il faut son nom "
                "et son nombre de broches."
            )
        counts = _PIN_COUNTS[kind]
        return self._store(kind, counts.sinks, counts.sources, None)

    def add_component_node(self, ref: str, sink_count: int, source_count: int) -> int:
        """Pose un composant par référence et renvoie l'identifiant du nœud.

        ``ref`` est le nom de la définition ; ``sink_count`` et ``source_count``
        sont ses nombres d'entrées et de sorties.
        """
        return self._store(NodeKind.COMPONENT, sink_count, source_count, ref)

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

    def _store(
        self, kind: NodeKind, sink_count: int, source_count: int, ref: str | None
    ) -> int:
        """Crée le nœud (qui se vérifie lui-même), puis consomme un identifiant."""
        node = Node(self._next_id, kind, sink_count, source_count, ref)
        self._nodes[node.node_id] = node
        self._next_id += 1
        return node.node_id

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
