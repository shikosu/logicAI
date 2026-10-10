"""Placement des nœuds d'un circuit pour l'affichage (positions x et y du JSON).

Python calcule les positions, Unity ne fait que dessiner (cahier, « Architecture
Python / Unity »). Le placement suit l'exemple du cahier : un NOT donne (0, 0), (2, 0)
et (4, 0).

- Les nœuds sont rangés en **colonnes** : ``x = 2 × couche``. La couche d'un nœud est la
  longueur du plus long chemin qui l'atteint depuis une entrée du circuit. Les entrées
  sont dans la couche 0, les sorties du circuit toutes dans la dernière colonne.
- Les boucles (câbles qui reviennent en arrière) sont ignorées pour calculer les
  couches : sinon un circuit à boucle n'aurait pas de colonne.
- Dans une colonne, les nœuds sont empilés de haut en bas, dans l'ordre de la hauteur
  moyenne de leurs sources, pour limiter les croisements de câbles. La première entrée
  est en haut. Les ``y`` sont des entiers.
- Un câble qui saute une colonne court à la hauteur de sa source jusqu'à la colonne
  d'arrivée. Une boîte ne doit pas se trouver sur son passage : sinon le câble
  disparaîtrait derrière elle et on ne saurait plus où il va. Quand une boîte tomberait
  sur un tel câble, elle est descendue jusqu'à la première hauteur libre.
- Une boîte fait ``max(2, broches)`` unités de haut, arrondi au pair supérieur, avec une
  unité entre deux broches : Unity utilise la même règle pour la dessiner.

Le résultat est déterministe et sans récursion (les circuits peuvent être grands).
"""

import itertools
from collections import deque
from dataclasses import dataclass

from logicai.circuit import Circuit, Node, NodeKind

# Écart horizontal entre deux colonnes (l'exemple du cahier : x = 0, 2, 4).
COLUMN_SPACING = 2

# Hauteur minimale d'une boîte, et espace vertical entre deux boîtes d'une colonne.
MIN_BOX_HEIGHT = 2
ROW_GAP = 2

# Distance minimale, en unités du fichier, entre un câble qui passe et le bord d'une
# boîte.
WIRE_CLEARANCE = 0.5

# Un câble « saute une colonne » quand sa cible est au moins 2 colonnes après sa source.
_MIN_LAYER_JUMP = 2

# Couche des nœuds sans prédécesseur qui ne sont pas des entrées (une NAND sans câble
# entrant, par exemple) : juste à droite des entrées.
_FIRST_GATE_LAYER = 1


@dataclass(frozen=True)
class Position:
    """Position du centre d'un nœud : x vers la droite, y vers le haut."""

    x: int
    y: int


def box_height(node: Node) -> int:
    """Renvoie la hauteur d'une boîte : ``max(2, broches)``, au pair supérieur."""
    pins = max(node.sink_count, node.source_count, MIN_BOX_HEIGHT)
    return pins + pins % 2


def compute_layout(circuit: Circuit) -> dict[int, Position]:
    """Place tous les nœuds du circuit et renvoie la position de chacun.

    Le dictionnaire suit l'ordre de création des nœuds.
    """
    successors = _successors(circuit)
    back_edges = _back_edges(circuit, successors)
    dag_successors = {
        node_id: [t for t in targets if (node_id, t) not in back_edges]
        for node_id, targets in successors.items()
    }
    layers = _layers(circuit, dag_successors)
    positions = _place(circuit, layers, dag_successors, _long_wires(circuit, layers))
    return {node.node_id: positions[node.node_id] for node in circuit.nodes()}


# --- Graphe ---------------------------------------------------------------------


def _successors(circuit: Circuit) -> dict[int, list[int]]:
    """Pour chaque nœud, les nœuds auxquels il envoie un câble (sans doublon, triés)."""
    targets: dict[int, set[int]] = {node.node_id: set() for node in circuit.nodes()}
    for wire in circuit.wires():
        targets[wire.source.node_id].add(wire.sink.node_id)
    return {node_id: sorted(found) for node_id, found in targets.items()}


def _back_edges(
    circuit: Circuit, successors: dict[int, list[int]]
) -> set[tuple[int, int]]:
    """Trouve les câbles qui reviennent en arrière, par un parcours en profondeur.

    On part des entrées puis de tous les autres nœuds, dans l'ordre de création. Un
    câble vers un nœud encore en cours de visite ferme une boucle : c'est un retour.
    Sans eux, le graphe n'a plus de cycle.
    """
    inputs = [n.node_id for n in circuit.nodes() if n.kind is NodeKind.INPUT]
    roots = itertools.chain(inputs, (n.node_id for n in circuit.nodes()))
    in_progress, finished = 1, 2
    state: dict[int, int] = {}
    back: set[tuple[int, int]] = set()
    for root in roots:
        if root in state:
            continue
        state[root] = in_progress
        stack = [(root, iter(successors[root]))]
        while stack:
            node_id, remaining = stack[-1]
            for target in remaining:
                target_state = state.get(target)
                if target_state is None:
                    state[target] = in_progress
                    stack.append((target, iter(successors[target])))
                    break
                if target_state == in_progress:
                    back.add((node_id, target))
            else:
                state[node_id] = finished
                stack.pop()
    return back


# --- Colonnes ---------------------------------------------------------------------


def _layers(circuit: Circuit, dag_successors: dict[int, list[int]]) -> dict[int, int]:
    """Renvoie la couche de chaque nœud : le plus long chemin depuis une entrée."""
    layer = {
        node.node_id: 0 if node.kind is NodeKind.INPUT else _FIRST_GATE_LAYER
        for node in circuit.nodes()
    }
    waiting = {node.node_id: 0 for node in circuit.nodes()}
    for targets in dag_successors.values():
        for target in targets:
            waiting[target] += 1
    ready = deque(node_id for node_id, count in waiting.items() if count == 0)
    while ready:
        node_id = ready.popleft()
        for target in dag_successors[node_id]:
            layer[target] = max(layer[target], layer[node_id] + 1)
            waiting[target] -= 1
            if waiting[target] == 0:
                ready.append(target)
    outputs = [n.node_id for n in circuit.nodes() if n.kind is NodeKind.OUTPUT]
    others = (
        layer[n.node_id] for n in circuit.nodes() if n.kind is not NodeKind.OUTPUT
    )
    last_layer = max(others, default=0) + 1
    for node_id in outputs:
        layer[node_id] = last_layer
    return layer


# --- Lignes -----------------------------------------------------------------------


@dataclass(frozen=True)
class _LongWire:
    """Un câble qui saute au moins une colonne entre sa source et sa cible."""

    source_id: int
    source_index: int
    first_layer: int
    last_layer: int


def _long_wires(circuit: Circuit, layers: dict[int, int]) -> list[_LongWire]:
    """Renvoie les câbles dont la cible est au moins deux colonnes après la source.

    Que le câble soit un « retour » pour le parcours ou non ne compte pas ici : Unity le
    trace vers l'avant dès que la cible est à droite de la source.
    """
    return [
        _LongWire(
            wire.source.node_id,
            wire.source.index,
            layers[wire.source.node_id],
            layers[wire.sink.node_id],
        )
        for wire in circuit.wires()
        if layers[wire.sink.node_id] - layers[wire.source.node_id] >= _MIN_LAYER_JUMP
    ]


def _place(
    circuit: Circuit,
    layers: dict[int, int],
    dag_successors: dict[int, list[int]],
    long_wires: list[_LongWire],
) -> dict[int, Position]:
    """Donne x et y à chaque nœud, colonne par colonne, de gauche à droite."""
    predecessors: dict[int, list[int]] = {n.node_id: [] for n in circuit.nodes()}
    for node_id, targets in dag_successors.items():
        for target in targets:
            predecessors[target].append(node_id)

    columns: dict[int, list[Node]] = {}
    for node in circuit.nodes():
        columns.setdefault(layers[node.node_id], []).append(node)
    nodes_by_id = {node.node_id: node for node in circuit.nodes()}
    starting_here: dict[int, list[_LongWire]] = {}
    for wire in long_wires:
        starting_here.setdefault(wire.first_layer, []).append(wire)

    positions: dict[int, Position] = {}
    passing: list[
        tuple[float, int, int]
    ] = []  # (hauteur, colonne de départ, colonne d'arrivée)
    for layer in sorted(columns):
        blocked = [y for y, first, last in passing if first < layer < last]
        ordered = sorted(
            columns[layer],
            key=lambda n: (
                -_mean_height(predecessors[n.node_id], positions),
                n.node_id,
            ),
        )
        for node, y in zip(ordered, _stack(ordered, blocked), strict=True):
            positions[node.node_id] = Position(COLUMN_SPACING * layer, y)
        for wire in starting_here.get(layer, []):
            source = nodes_by_id[wire.source_id]
            pin_offset = (source.source_count - 1) / 2 - wire.source_index
            height = positions[wire.source_id].y + pin_offset
            passing.append((height, wire.first_layer, wire.last_layer))
    return positions


def _mean_height(node_ids: list[int], positions: dict[int, Position]) -> float:
    """Renvoie la hauteur moyenne des nœuds déjà placés (0 s'il n'y en a pas)."""
    heights = [positions[node_id].y for node_id in node_ids if node_id in positions]
    return sum(heights) / len(heights) if heights else 0.0


def _stack(ordered: list[Node], blocked: list[float]) -> list[int]:
    """Empile des boîtes de haut en bas, centrées sur y = 0, et renvoie leurs centres.

    Les hauteurs et l'écart sont pairs, donc tous les centres sont entiers. Une boîte
    qui tomberait sur un câble qui passe (une hauteur de ``blocked``) est descendue,
    d'une unité à la fois, jusqu'à la première place libre ; les suivantes suivent.
    """
    heights = [box_height(node) for node in ordered]
    total = sum(heights) + ROW_GAP * (len(heights) - 1)
    free_top = total // 2
    centers: list[int] = []
    for height in heights:
        center = free_top - height // 2
        while _touches_a_wire(center, height, blocked):
            center -= 1
        centers.append(center)
        free_top = center - height // 2 - ROW_GAP
    return centers


def _touches_a_wire(center: int, height: int, blocked: list[float]) -> bool:
    """Dit si un câble qui passe est trop près d'une boîte (ou la traverse)."""
    return any(abs(y - center) < height / 2 + WIRE_CLEARANCE for y in blocked)
