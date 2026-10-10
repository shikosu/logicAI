"""Mutations : modifier un circuit au hasard pour en essayer un nouveau.

Les mutations du cahier (« IA 1 : l'algorithme évolutionnaire ») sont :

- ajouter une NAND ou un composant de la bibliothèque ;
- ajouter un câble valide, ou en retirer un ;
- retirer un nœud ;
- ajouter une entrée ou une sortie de circuit.

Règles de ce module :

- **Le parent n'est jamais modifié** : chaque mutation travaille sur une copie.
- **Une mutation ne produit que des circuits légaux.** Les règles de câblage sont
  vérifiées *avant* d'agir (un câble n'est posé que sur un puits libre, et un câble
  qui créerait une boucle n'est pas proposé tant que les boucles sont interdites).
  Une mutation impossible rend ``None`` : rien n'est fait.
- **Tout le hasard vient du générateur ``rng`` donné par l'appelant** (avec sa
  graine) : mêmes données et même graine, même résultat.
- « Retirer un nœud » ne retire que des NAND et des composants. Les entrées et les
  sorties du circuit ne s'enlèvent pas : on en ajoute (dans la limite du palier), et une
  entrée inutile est de toute façon refusée par les filtres.
- Les paliers 1 à 3 n'ont qu'une sortie, et leurs mutations ne créent pas de boucle
  (les mémoires viennent avec les phases 5 et 6) : ce sont des réglages du palier
  (``MutationRules``), pas des règles de câblage.

Le choix de la mutation se fait parmi celles qui sont possibles, avec un **poids** par
mutation (``DEFAULT_MUTATION_WEIGHTS``, décision de Téo après des essais) : construire
un circuit demande bien plus d'ajouts que de retraits, donc les ajouts de câbles, de
NAND et de composants sont favorisés. Ces poids se règlent par essais.
"""

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from types import MappingProxyType

from logicai.circuit import Circuit, NodeKind, Pin
from logicai.errors import InvalidMutationRulesError
from logicai.library import Library


class Mutation(Enum):
    """Les sept mutations du cahier."""

    ADD_NAND = auto()
    ADD_COMPONENT = auto()
    ADD_WIRE = auto()
    REMOVE_WIRE = auto()
    REMOVE_NODE = auto()
    ADD_INPUT = auto()
    ADD_OUTPUT = auto()


# Poids de départ de chaque mutation (valeurs trouvées par essais, à régler encore) :
# ajouter un câble 4, ajouter une NAND ou un composant 2, tout le reste 1.
DEFAULT_MUTATION_WEIGHTS: Mapping[Mutation, int] = MappingProxyType(
    {
        Mutation.ADD_NAND: 2,
        Mutation.ADD_COMPONENT: 2,
        Mutation.ADD_WIRE: 4,
        Mutation.REMOVE_WIRE: 1,
        Mutation.REMOVE_NODE: 1,
        Mutation.ADD_INPUT: 1,
        Mutation.ADD_OUTPUT: 1,
    }
)


@dataclass(frozen=True)
class MutationRules:
    """Ce que les mutations ont le droit de faire (réglages du palier).

    ``max_inputs`` et ``max_outputs`` plafonnent le nombre d'entrées et de sorties
    du circuit. Avec ``allow_loops`` à ``False``, aucun câble qui créerait une
    boucle n'est posé : les circuits restent combinatoires.
    """

    max_inputs: int
    max_outputs: int
    allow_loops: bool = False

    def __post_init__(self) -> None:
        """Refuse un maximum négatif."""
        if self.max_inputs < 0 or self.max_outputs < 0:
            raise InvalidMutationRulesError(
                "Les maximums d'entrées et de sorties ne peuvent pas être négatifs "
                f"(reçu : {self.max_inputs} entrées, {self.max_outputs} sorties)."
            )


@dataclass(frozen=True)
class MutationResult:
    """Un circuit muté, et la mutation qui l'a produit."""

    kind: Mutation
    circuit: Circuit


# Une mutation modifie le circuit qu'on lui donne (une copie) et dit si elle a pu
# agir. Si elle répond ``False``, elle n'a rien modifié.
_Applier = Callable[[Circuit, random.Random, MutationRules, Library], bool]

# Nœuds qu'on a le droit de retirer (voir l'en-tête du module).
_REMOVABLE_KINDS = (NodeKind.NAND, NodeKind.COMPONENT)


def apply_mutation(
    kind: Mutation,
    circuit: Circuit,
    rng: random.Random,
    rules: MutationRules,
    library: Library,
) -> Circuit | None:
    """Applique une mutation précise et renvoie le nouveau circuit.

    Renvoie ``None`` si cette mutation est impossible sur ce circuit (par exemple
    retirer un câble d'un circuit sans câble). Le circuit donné n'est pas modifié.
    """
    child = circuit.copy()
    if _APPLIERS[kind](child, rng, rules, library):
        return child
    return None


def mutate(
    circuit: Circuit,
    rng: random.Random,
    rules: MutationRules,
    library: Library,
    weights: Mapping[Mutation, int] | None = None,
) -> MutationResult:
    """Applique une mutation tirée au hasard parmi celles qui sont possibles.

    Chaque mutation est tirée avec la chance donnée par son poids (par défaut
    ``DEFAULT_MUTATION_WEIGHTS``). Les poids doivent être des entiers positifs, un par
    mutation : ainsi ajouter une NAND, toujours possible, a toujours une chance, et
    cette fonction réussit toujours. Le circuit donné n'est pas modifié.
    """
    chosen = DEFAULT_MUTATION_WEIGHTS if weights is None else weights
    chances = _checked_weights(chosen)
    remaining = list(Mutation)
    while True:
        kind = rng.choices(remaining, weights=[chances[k] for k in remaining])[0]
        child = apply_mutation(kind, circuit, rng, rules, library)
        if child is not None:
            return MutationResult(kind, child)
        remaining.remove(kind)


def _checked_weights(weights: Mapping[Mutation, int]) -> Mapping[Mutation, int]:
    """Refuse des poids qui ne donnent pas une chance à chaque mutation."""
    missing = [kind.name for kind in Mutation if kind not in weights]
    if missing:
        raise InvalidMutationRulesError(
            f"Il manque le poids des mutations : {', '.join(missing)}."
        )
    bad = [kind.name for kind in Mutation if weights[kind] < 1]
    if bad:
        raise InvalidMutationRulesError(
            "Les poids doivent être des entiers positifs "
            f"(refusé pour : {', '.join(bad)})."
        )
    return weights


# --- Les sept mutations ------------------------------------------------------


def _add_nand(
    circuit: Circuit, rng: random.Random, rules: MutationRules, library: Library
) -> bool:
    """Ajoute une NAND sans câble."""
    circuit.add_node(NodeKind.NAND)
    return True


def _add_component(
    circuit: Circuit, rng: random.Random, rules: MutationRules, library: Library
) -> bool:
    """Pose sans câble un composant de la bibliothèque, choisi au hasard."""
    names = library.names()
    if not names:
        return False
    library.instantiate(circuit, rng.choice(names))
    return True


def _add_wire(
    circuit: Circuit, rng: random.Random, rules: MutationRules, library: Library
) -> bool:
    """Pose un câble valide entre une source et un puits libre.

    On prend un puits libre au hasard, puis une source parmi celles qui ne créent
    pas de boucle (sauf si les boucles sont permises). Si ce puits n'a aucune source
    possible, on essaie un autre puits.
    """
    free_sinks = _free_sinks(circuit)
    rng.shuffle(free_sinks)
    for sink in free_sinks:
        sources = _allowed_sources(circuit, sink, rules)
        if sources:
            circuit.connect(rng.choice(sources), sink)
            return True
    return False


def _remove_wire(
    circuit: Circuit, rng: random.Random, rules: MutationRules, library: Library
) -> bool:
    """Retire un câble au hasard."""
    wires = circuit.wires()
    if not wires:
        return False
    circuit.disconnect(rng.choice(wires).sink)
    return True


def _remove_node(
    circuit: Circuit, rng: random.Random, rules: MutationRules, library: Library
) -> bool:
    """Retire une NAND ou un composant au hasard, avec les câbles qui le touchent."""
    removable = [n.node_id for n in circuit.nodes() if n.kind in _REMOVABLE_KINDS]
    if not removable:
        return False
    circuit.remove_node(rng.choice(removable))
    return True


def _add_input(
    circuit: Circuit, rng: random.Random, rules: MutationRules, library: Library
) -> bool:
    """Ajoute une entrée au circuit, si le palier le permet."""
    if len(circuit.inputs()) >= rules.max_inputs:
        return False
    circuit.add_node(NodeKind.INPUT)
    return True


def _add_output(
    circuit: Circuit, rng: random.Random, rules: MutationRules, library: Library
) -> bool:
    """Ajoute une sortie au circuit, si le palier le permet."""
    if len(circuit.outputs()) >= rules.max_outputs:
        return False
    circuit.add_node(NodeKind.OUTPUT)
    return True


_APPLIERS: dict[Mutation, _Applier] = {
    Mutation.ADD_NAND: _add_nand,
    Mutation.ADD_COMPONENT: _add_component,
    Mutation.ADD_WIRE: _add_wire,
    Mutation.REMOVE_WIRE: _remove_wire,
    Mutation.REMOVE_NODE: _remove_node,
    Mutation.ADD_INPUT: _add_input,
    Mutation.ADD_OUTPUT: _add_output,
}


# --- Câbler sans créer de boucle ---------------------------------------------


def _free_sinks(circuit: Circuit) -> list[Pin]:
    """Renvoie les puits qui ne reçoivent aucun câble, dans l'ordre des nœuds."""
    return [
        Pin(node.node_id, index)
        for node in circuit.nodes()
        for index in range(node.sink_count)
        if circuit.source_of(Pin(node.node_id, index)) is None
    ]


def _allowed_sources(circuit: Circuit, sink: Pin, rules: MutationRules) -> list[Pin]:
    """Renvoie les sources qu'on peut relier à ce puits sans boucle interdite."""
    forbidden = set() if rules.allow_loops else _reachable_from(circuit, sink.node_id)
    return [
        Pin(node.node_id, index)
        for node in circuit.nodes()
        if node.node_id not in forbidden
        for index in range(node.source_count)
    ]


def _reachable_from(circuit: Circuit, start_id: int) -> set[int]:
    """Renvoie les nœuds atteints en suivant les câbles depuis ``start_id`` (compris).

    Relier une source à un puits crée une boucle exactement quand le nœud du puits
    mène déjà au nœud de la source, ou quand c'est le même nœud. Un composant compte
    comme un seul nœud (toutes ses entrées mènent à toutes ses sorties) : on se
    trompe alors par prudence, jamais dans l'autre sens. La recherche n'est pas
    récursive, pour supporter les grands circuits.
    """
    successors: dict[int, list[int]] = {}
    for wire in circuit.wires():
        successors.setdefault(wire.source.node_id, []).append(wire.sink.node_id)
    reached = {start_id}
    to_visit = [start_id]
    while to_visit:
        for next_id in successors.get(to_visit.pop(), ()):
            if next_id not in reached:
                reached.add(next_id)
                to_visit.append(next_id)
    return reached
