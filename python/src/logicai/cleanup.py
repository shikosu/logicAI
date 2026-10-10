"""Nettoyage : retire ce qui n'influence aucune sortie du circuit.

Première étape de l'encapsulation (cahier, « Composants et bibliothèque »). Un nœud est
utile s'il existe un chemin de câbles depuis lui jusqu'à une sortie du circuit. Ce test
est structurel : on ne simplifie pas la logique, on retire seulement ce qui n'est relié
à aucune sortie. Une boucle qui alimente une sortie est donc gardée, et une boucle qui
n'en alimente aucune est retirée.
"""

from logicai.circuit import Circuit, NodeKind, Pin

# Seuls ces types de nœuds peuvent être retirés : les entrées et les sorties du circuit
# sont ses broches, elles restent toujours (l'ordre des broches en dépend).
_REMOVABLE_KINDS = frozenset({NodeKind.NAND, NodeKind.COMPONENT})


def remove_useless_nodes(circuit: Circuit) -> Circuit:
    """Renvoie une copie du circuit sans les NAND ni les composants inutiles.

    Les câbles des nœuds retirés disparaissent avec eux. Les nœuds gardés conservent
    leur identifiant. Le circuit donné n'est pas modifié.

    Le résultat est reconstruit en un seul passage avec ``from_parts`` : appeler
    ``remove_node`` pour chaque nœud inutile relirait tous les câbles à chaque fois.
    """
    useful = _useful_node_ids(circuit)
    kept = [
        node
        for node in circuit.nodes()
        if node.kind not in _REMOVABLE_KINDS or node.node_id in useful
    ]
    kept_ids = {node.node_id for node in kept}
    wires = [
        wire
        for wire in circuit.wires()
        if wire.source.node_id in kept_ids and wire.sink.node_id in kept_ids
    ]
    return Circuit.from_parts(kept, wires)


def _useful_node_ids(circuit: Circuit) -> set[int]:
    """Trouve les nœuds qui ont un chemin vers une sortie, en remontant les câbles.

    On part des sorties et on suit, pour chaque nœud trouvé, la source de chacun de
    ses puits. Un composant est gardé en entier : on ne sait pas, sans l'ouvrir, quelle
    entrée influence quelle sortie. La recherche est une boucle, pas une récursion,
    pour supporter de très longues chaînes de portes.
    """
    useful: set[int] = set()
    pending = list(circuit.outputs())
    while pending:
        node_id = pending.pop()
        if node_id in useful:
            continue
        useful.add(node_id)
        for index in range(circuit.node(node_id).sink_count):
            source = circuit.source_of(Pin(node_id, index))
            if source is not None:
                pending.append(source.node_id)
    return useful
