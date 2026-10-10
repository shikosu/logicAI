"""Format JSON d'un circuit (cahier, « Exemple de circuit en JSON »).

Un NOT fait d'une seule NAND dont les deux entrées sont alimentées par A :

    {
      "nom": "NOT",
      "noeuds": [
        {"id": 0, "type": "ENTREE", "x": 0, "y": 0},
        {"id": 1, "type": "NAND", "x": 2, "y": 0},
        {"id": 2, "type": "SORTIE", "x": 4, "y": 0}
      ],
      "cables": [
        {"de": [0, 0], "vers": [1, 0]},
        {"de": [0, 0], "vers": [1, 1]},
        {"de": [1, 0], "vers": [2, 0]}
      ]
    }

``[1, 0]`` se lit « nœud 1, broche 0 » ; pour ``de`` c'est une broche source, pour
``vers`` une broche puits. ``x`` et ``y`` sont calculés par Python (module ``layout``) :
Unity ne fait que dessiner. Ils sont écrits partout, et ignorés à la lecture.

Deux ajouts au format du cahier :

- un composant posé dans un circuit s'écrit
  ``{"id": 3, "type": "COMPOSANT", "x": 2, "y": 0, "ref": "XOR", "entrees": 2,
  "sorties": 1}`` ; on y met ses nombres de broches pour que le fichier se suffise ;
- une clé facultative ``etat`` donne les valeurs 0/1 du circuit à un top, pour que Unity
  colore les câbles (voir le module ``snapshot``) :
  ``"etat": {"top": 3, "stable": true, "noeuds": [0, 1, 1], "cables": [0, 0, 1]}``.
  Les listes suivent l'ordre de ``noeuds`` et de ``cables`` du fichier. Elle est
  ignorée à la lecture : c'est une photo pour l'affichage, pas une partie du circuit.
"""

import json
import re
from collections.abc import Mapping
from typing import Any, TypeVar

from logicai.circuit import Circuit, Node, NodeKind, Pin, Wire
from logicai.errors import CircuitError, LibraryFormatError, SnapshotError
from logicai.layout import Position, compute_layout
from logicai.snapshot import Snapshot

_TYPE_OF_KIND: dict[NodeKind, str] = {
    NodeKind.INPUT: "ENTREE",
    NodeKind.OUTPUT: "SORTIE",
    NodeKind.NAND: "NAND",
    NodeKind.CLK: "CLK",
    NodeKind.COMPONENT: "COMPOSANT",
}
_KIND_OF_TYPE: dict[str, NodeKind] = {
    name: kind for kind, name in _TYPE_OF_KIND.items()
}

T = TypeVar("T")

# Un nom sert de nom de fichier : lettres, chiffres, tiret et tiret bas seulement.
_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]+")

# Une broche s'écrit [identifiant du nœud, index].
_PIN_LENGTH = 2


def circuit_to_dict(
    name: str, circuit: Circuit, snapshot: Snapshot | None = None
) -> dict[str, Any]:
    """Écrit un circuit sous la forme d'un dictionnaire prêt pour ``json.dumps``.

    Les positions ``x`` et ``y`` sont toujours écrites. Avec un relevé de valeurs
    (``snapshot``), une clé ``etat`` est ajoutée ; il doit venir de ce circuit.
    """
    layout = compute_layout(circuit)
    result: dict[str, Any] = {
        "nom": name,
        "noeuds": [
            node_to_dict(node, layout[node.node_id]) for node in circuit.nodes()
        ],
        "cables": [
            {
                "de": [wire.source.node_id, wire.source.index],
                "vers": [wire.sink.node_id, wire.sink.index],
            }
            for wire in circuit.wires()
        ],
    }
    if snapshot is not None:
        result["etat"] = state_to_dict(circuit, snapshot)
    return result


def circuit_to_json(
    name: str, circuit: Circuit, snapshot: Snapshot | None = None
) -> str:
    """Écrit un circuit en texte JSON lisible (terminé par un retour à la ligne)."""
    data = circuit_to_dict(name, circuit, snapshot)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def circuit_from_json(text: str) -> tuple[str, Circuit]:
    """Lit un texte JSON et renvoie (nom, circuit) ; sinon ``LibraryFormatError``."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise LibraryFormatError(f"Ce n'est pas du JSON valide : {error}.") from error
    return circuit_from_dict(data)


def circuit_from_dict(data: object) -> tuple[str, Circuit]:
    """Lit un dictionnaire et renvoie le nom et le circuit.

    Toute erreur (clé manquante, mauvais type, type de nœud inconnu, câble interdit
    par les règles de câblage...) lève ``LibraryFormatError`` avec un message qui dit
    où est le problème. Les identifiants lus sont conservés.
    """
    try:
        return _parse(data)
    except CircuitError as error:
        raise LibraryFormatError(f"Circuit invalide : {error}") from error


# --- Écriture --------------------------------------------------------------------


def node_to_dict(node: Node, position: Position) -> dict[str, Any]:
    """Écrit un nœud ; un composant porte son nom de définition et ses broches."""
    result: dict[str, Any] = {
        "id": node.node_id,
        "type": _TYPE_OF_KIND[node.kind],
        "x": position.x,
        "y": position.y,
    }
    if node.kind is NodeKind.COMPONENT:
        result["ref"] = node.component_ref
        result["entrees"] = node.sink_count
        result["sorties"] = node.source_count
    return result


def state_to_dict(circuit: Circuit, snapshot: Snapshot) -> dict[str, Any]:
    """Écrit un relevé de valeurs, après avoir vérifié qu'il correspond au circuit."""
    node_count, wire_count = len(circuit.nodes()), len(circuit.wires())
    if (len(snapshot.node_values), len(snapshot.wire_values)) != (
        node_count,
        wire_count,
    ):
        raise SnapshotError(
            f"Le relevé a {len(snapshot.node_values)} valeurs de nœuds et "
            f"{len(snapshot.wire_values)} valeurs de câbles, mais le circuit a "
            f"{node_count} nœuds et {wire_count} câbles."
        )
    return {
        "top": snapshot.top,
        "stable": snapshot.stable,
        "noeuds": list(snapshot.node_values),
        "cables": list(snapshot.wire_values),
    }


# --- Lecture ---------------------------------------------------------------------


def _parse(data: object) -> tuple[str, Circuit]:
    """Lit le dictionnaire complet ; un câblage interdit lève ``CircuitError``."""
    root = _as_object(data, "le fichier")
    name = _field(root, "nom", str, "le fichier")
    if not _NAME_PATTERN.fullmatch(name):
        raise LibraryFormatError(
            f"Le nom {name!r} est invalide : lettres, chiffres, '-' et '_' seulement."
        )
    nodes = [
        _node_from_dict(item, f"noeuds[{index}]")
        for index, item in enumerate(_field(root, "noeuds", list, "le fichier"))
    ]
    wires = [
        _wire_from_dict(item, f"cables[{index}]")
        for index, item in enumerate(_field(root, "cables", list, "le fichier"))
    ]
    return name, Circuit.from_parts(nodes, wires)


def _node_from_dict(item: object, where: str) -> Node:
    """Lit un nœud (``x`` et ``y`` sont ignorés)."""
    entry = _as_object(item, where)
    node_id = _field(entry, "id", int, where)
    type_name = _field(entry, "type", str, where)
    kind = _KIND_OF_TYPE.get(type_name)
    if kind is None:
        known = ", ".join(sorted(_KIND_OF_TYPE))
        raise LibraryFormatError(
            f"{where} : le type {type_name!r} est inconnu (types connus : {known})."
        )
    if kind is not NodeKind.COMPONENT:
        return Node.fixed(node_id, kind)
    return Node(
        node_id,
        kind,
        _field(entry, "entrees", int, where),
        _field(entry, "sorties", int, where),
        _field(entry, "ref", str, where),
    )


def _wire_from_dict(item: object, where: str) -> Wire:
    """Lit un câble : ``de`` (broche source) et ``vers`` (broche puits)."""
    entry = _as_object(item, where)
    return Wire(
        _pin_from_list(_field(entry, "de", list, where), f"{where}.de"),
        _pin_from_list(_field(entry, "vers", list, where), f"{where}.vers"),
    )


def _pin_from_list(values: list[Any], where: str) -> Pin:
    """Lit une broche écrite [identifiant du nœud, index]."""
    if len(values) != _PIN_LENGTH or not all(_is_int(value) for value in values):
        raise LibraryFormatError(
            f"{where} : une broche s'écrit [nœud, index], avec deux entiers."
        )
    return Pin(values[0], values[1])


def _as_object(value: object, where: str) -> Mapping[str, Any]:
    """Vérifie qu'une valeur est un objet JSON (un dictionnaire)."""
    if not isinstance(value, dict):
        raise LibraryFormatError(f"{where} : un objet JSON {{...}} est attendu.")
    return value


def _is_int(value: object) -> bool:
    """Dit si c'est un vrai entier (``True`` et ``False`` n'en sont pas)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _field(entry: Mapping[str, Any], key: str, expected: type[T], where: str) -> T:
    """Lit une clé obligatoire de type ``expected`` (un booléen n'est pas un entier)."""
    if key not in entry:
        raise LibraryFormatError(f"{where} : la clé {key!r} manque.")
    value = entry[key]
    wrong_bool = expected is int and isinstance(value, bool)
    if not isinstance(value, expected) or wrong_bool:
        raise LibraryFormatError(
            f"{where} : la clé {key!r} doit être de type {expected.__name__}, "
            f"pas {type(value).__name__}."
        )
    return value
