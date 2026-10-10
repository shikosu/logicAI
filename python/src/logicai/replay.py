"""Ordre de pose d'un circuit : de quoi le reconstruire pièce par pièce (rediffusion).

L'évolution ne construit pas pas à pas : elle modifie des circuits existants (cahier,
« IA 1 : l'algorithme évolutionnaire »). Pour montrer une découverte, on **reconstitue**
un ordre de pose : « les nœuds dans l'ordre des signaux, puis les câbles ».

- Les **nœuds** sont posés colonne par colonne, de gauche à droite (la colonne ``x``
  vient de la longueur du plus long chemin depuis une entrée : voir ``layout``), puis de
  haut en bas dans une colonne. Dans un circuit sans boucle, un nœud est donc toujours
  posé après ceux qui l'alimentent.
- Les **câbles** viennent après tous les nœuds, dans l'ordre de leur puits : un câble
  arrive sur un nœud déjà posé, et on suit la circulation du signal.

Chaque étape est un petit dictionnaire, avec le vocabulaire du futur message « action »
du cahier (phase 7) :

- ``{"action": "poser", "noeud": {...}}`` : le nœud est écrit comme dans un fichier de
  circuit, avec ses positions ``x`` et ``y`` (Unity ne calcule rien) ;
- ``{"action": "cabler", "de": [nœud, broche], "vers": [nœud, broche]}``.

``circuit_from_placement`` fait l'inverse : il rejoue les premières étapes et rend le
circuit obtenu. C'est ce que fera Unity pour la rediffusion, et ce qui permet de tester
l'ordre ici.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from logicai.circuit import Circuit
from logicai.errors import InvalidPlacementError
from logicai.layout import compute_layout
from logicai.serialization import circuit_from_dict, node_to_dict

POSE_ACTION = "poser"
WIRE_ACTION = "cabler"

# Nom donné au circuit reconstruit (le format d'un fichier exige un nom valide).
_REPLAY_NAME = "rediffusion"

# Une broche s'écrit [identifiant du nœud, index].
_PIN_LENGTH = 2


def placement_order(circuit: Circuit) -> tuple[dict[str, Any], ...]:
    """Renvoie l'ordre de pose : les nœuds dans l'ordre des signaux, puis les câbles.

    Le circuit n'est pas modifié. Le résultat est le même pour le même circuit.
    """
    layout = compute_layout(circuit)
    ordered = sorted(
        circuit.nodes(),
        key=lambda node: (layout[node.node_id].x, layout[node.node_id].y, node.node_id),
    )
    rank = {node.node_id: position for position, node in enumerate(ordered)}
    steps: list[dict[str, Any]] = [
        {"action": POSE_ACTION, "noeud": node_to_dict(node, layout[node.node_id])}
        for node in ordered
    ]
    wires = sorted(
        circuit.wires(),
        key=lambda wire: (rank[wire.sink.node_id], wire.sink.index),
    )
    steps.extend(
        {
            "action": WIRE_ACTION,
            "de": [wire.source.node_id, wire.source.index],
            "vers": [wire.sink.node_id, wire.sink.index],
        }
        for wire in wires
    )
    return tuple(steps)


def circuit_from_placement(
    steps: Sequence[Mapping[str, Any]], count: int | None = None
) -> Circuit:
    """Rejoue les ``count`` premières étapes (toutes par défaut) et renvoie le circuit.

    Un câble ne peut venir qu'après la pose de ses deux nœuds. Une étape incohérente
    lève ``InvalidPlacementError`` ; un nœud ou un câble que les règles du circuit
    refusent (nœud posé deux fois, broche inexistante, puits déjà relié...) lève
    ``LibraryFormatError``, avec le message du circuit.
    """
    if count is not None and count < 0:
        raise InvalidPlacementError(f"Le nombre d'étapes {count} est négatif.")
    played = list(steps) if count is None else list(steps)[:count]
    nodes: list[Any] = []
    wires: list[dict[str, Any]] = []
    posed: set[int] = set()
    for number, step in enumerate(played):
        action = step.get("action")
        if action == POSE_ACTION:
            node = step.get("noeud")
            if not isinstance(node, Mapping):
                raise InvalidPlacementError(f"Étape {number} : le nœud manque.")
            nodes.append(node)
            posed.add(_node_id(node.get("id"), number))
        elif action == WIRE_ACTION:
            wire = {key: step.get(key) for key in ("de", "vers")}
            for key in ("de", "vers"):
                if _pin_node_id(wire[key], number) not in posed:
                    raise InvalidPlacementError(
                        f"Étape {number} : le câble touche un nœud pas encore posé."
                    )
            wires.append(wire)
        else:
            raise InvalidPlacementError(
                f"Étape {number} : action inconnue {action!r} "
                f"(actions connues : {POSE_ACTION}, {WIRE_ACTION})."
            )
    nodes.sort(key=lambda node: node["id"])
    data = {"nom": _REPLAY_NAME, "noeuds": nodes, "cables": wires}
    return circuit_from_dict(data)[1]


def _node_id(value: object, number: int) -> int:
    """Vérifie qu'un identifiant de nœud est un vrai entier."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidPlacementError(f"Étape {number} : l'identifiant du nœud est faux.")
    return value


def _pin_node_id(pin: object, number: int) -> int:
    """Renvoie l'identifiant du nœud d'une broche écrite [nœud, index]."""
    if not isinstance(pin, list) or len(pin) != _PIN_LENGTH:
        raise InvalidPlacementError(
            f"Étape {number} : une broche s'écrit [nœud, index]."
        )
    return _node_id(pin[0], number)
