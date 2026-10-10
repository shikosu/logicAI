"""Aplatissement : remplace chaque composant par les NAND qui le composent.

Pour simuler, on « ouvre » tous les composants (cahier, « Simulation d'un composant »).
Les NAND gardent leur retard d'un top, donc les retards restent exacts. Les entrées et
sorties d'un composant ne sont que des frontières : elles disparaissent, et les câbles
qui les traversent sont raccordés bout à bout, sans retard.

Le circuit aplati est un nouveau circuit, avec de nouveaux identifiants. Ses entrées
et ses sorties gardent l'ordre de création du circuit de départ.
"""

from collections.abc import Mapping

from logicai.circuit import Circuit, Node, NodeKind, Pin
from logicai.errors import (
    ComponentCycleError,
    ComponentNestingError,
    ComponentPinMismatchError,
    UnknownComponentError,
    WireLoopError,
)

# Le puits unique d'une sortie du circuit.
_OUTPUT_SINK = 0


class _Instance:
    """Un circuit posé dans l'aplatissement : le circuit de départ ou un composant.

    ``parent`` vaut ``None`` pour le circuit de départ ; sinon c'est le couple
    (instance qui contient le composant, identifiant du nœud composant dedans).
    """

    def __init__(
        self, uid: int, circuit: Circuit, parent: "tuple[_Instance, int] | None"
    ) -> None:
        """Prépare une instance vide ; ``_Flattener`` la remplit."""
        self.uid = uid
        self.circuit = circuit
        self.parent = parent
        # Identifiant, dans le circuit aplati, des NAND de cette instance (et des
        # entrées et sorties, seulement pour le circuit de départ).
        self.flat_ids: dict[int, int] = {}
        # Identifiant d'un nœud composant -> l'instance qui le remplace.
        self.children: dict[int, _Instance] = {}
        # Position (dans l'ordre de création) de chaque entrée du circuit.
        self.input_position = {
            node_id: position for position, node_id in enumerate(circuit.inputs())
        }


class _Flattener:
    """Construit le circuit aplati, en deux temps : les nœuds, puis les câbles."""

    def __init__(self, definitions: Mapping[str, Circuit]) -> None:
        """Garde les définitions des composants et crée le circuit aplati vide."""
        self._definitions = definitions
        self._flat = Circuit()
        self._instance_count = 0
        # Résultat déjà trouvé pour une source, et sources en cours de recherche
        # (pour repérer une boucle de fils).
        self._memo: dict[tuple[int, Pin], Pin | None] = {}
        self._in_progress: set[tuple[int, Pin]] = set()

    def run(self, circuit: Circuit) -> Circuit:
        """Aplatit le circuit de départ et renvoie le circuit aplati."""
        root = self._instantiate(circuit, None, ())
        self._wire_instance(root)
        return self._flat

    # --- Temps 1 : créer les nœuds -----------------------------------------

    def _instantiate(
        self,
        circuit: Circuit,
        parent: tuple[_Instance, int] | None,
        stack: tuple[str, ...],
    ) -> _Instance:
        """Crée les NAND d'un circuit (et de ses composants, en ouvrant chacun)."""
        instance = _Instance(self._instance_count, circuit, parent)
        self._instance_count += 1
        is_root = parent is None
        for node in circuit.nodes():
            if node.kind is NodeKind.COMPONENT:
                instance.children[node.node_id] = self._instantiate_component(
                    instance, node, stack
                )
            elif node.kind is NodeKind.NAND or is_root:
                instance.flat_ids[node.node_id] = self._flat.add_node(node.kind)
        return instance

    def _instantiate_component(
        self, parent: _Instance, node: Node, stack: tuple[str, ...]
    ) -> _Instance:
        """Contrôle un nœud composant puis ouvre sa définition."""
        ref = node.component_ref or ""
        definition = self._definitions.get(ref)
        if definition is None:
            raise UnknownComponentError(
                f"Le nœud {node.node_id} pose le composant {ref!r}, "
                "qui n'a pas de définition."
            )
        if ref in stack:
            chain = " -> ".join((*stack, ref))
            raise ComponentCycleError(
                f"Le composant {ref!r} se contient lui-même : {chain}."
            )
        expected = (len(definition.inputs()), len(definition.outputs()))
        if (node.sink_count, node.source_count) != expected:
            raise ComponentPinMismatchError(
                f"Le nœud {node.node_id} a {node.sink_count} entrée(s) et "
                f"{node.source_count} sortie(s), mais le composant {ref!r} "
                f"en a {expected[0]} et {expected[1]}."
            )
        return self._instantiate(definition, (parent, node.node_id), (*stack, ref))

    # --- Temps 2 : poser les câbles ----------------------------------------

    def _wire_instance(self, instance: _Instance) -> None:
        """Pose les câbles qui arrivent sur les NAND (et les sorties du départ)."""
        is_root = instance.parent is None
        for node in instance.circuit.nodes():
            if node.kind is NodeKind.NAND or (node.kind is NodeKind.OUTPUT and is_root):
                flat_id = instance.flat_ids[node.node_id]
                for index in range(node.sink_count):
                    self._wire_sink(
                        instance, Pin(node.node_id, index), Pin(flat_id, index)
                    )
        for child in instance.children.values():
            self._wire_instance(child)

    def _wire_sink(self, instance: _Instance, sink: Pin, flat_sink: Pin) -> None:
        """Relie un puits du circuit aplati à la vraie source qui l'alimente."""
        source = self._resolve_sink(instance, sink)
        if source is not None:
            self._flat.connect(source, flat_sink)

    def _resolve_sink(self, instance: _Instance, sink: Pin) -> Pin | None:
        """Trouve la source du circuit aplati qui alimente ce puits (``None`` = 0)."""
        source = instance.circuit.source_of(sink)
        if source is None:
            return None
        return self._resolve(instance, source)

    def _resolve(self, instance: _Instance, source: Pin) -> Pin | None:
        """Suit les frontières de composants jusqu'à une vraie source (``None`` = 0)."""
        key = (instance.uid, source)
        if key in self._memo:
            return self._memo[key]
        if key in self._in_progress:
            raise WireLoopError(
                f"Boucle de fils sans NAND autour de la broche ({source.node_id}, "
                f"{source.index}) : sa valeur n'est pas définie."
            )
        self._in_progress.add(key)
        try:
            result = self._resolve_uncached(instance, source)
        finally:
            self._in_progress.discard(key)
        self._memo[key] = result
        return result

    def _resolve_uncached(self, instance: _Instance, source: Pin) -> Pin | None:
        """Cherche la vraie source d'une broche source (sans mémoire)."""
        node = instance.circuit.node(source.node_id)
        if node.kind is NodeKind.COMPONENT:
            # Sortie d'un composant : ce qui alimente la sortie correspondante dedans.
            child = instance.children[node.node_id]
            output_id = child.circuit.outputs()[source.index]
            return self._resolve_sink(child, Pin(output_id, _OUTPUT_SINK))
        if node.kind is NodeKind.INPUT and instance.parent is not None:
            # Entrée d'un composant : ce qui alimente ce composant, dehors.
            parent, component_id = instance.parent
            position = instance.input_position[node.node_id]
            return self._resolve_sink(parent, Pin(component_id, position))
        # NAND, ou entrée du circuit de départ : un vrai nœud du circuit aplati.
        return Pin(instance.flat_ids[node.node_id], source.index)


def flatten(circuit: Circuit, definitions: Mapping[str, Circuit]) -> Circuit:
    """Renvoie un nouveau circuit où chaque composant est remplacé par ses NAND.

    ``definitions`` donne, pour chaque nom de composant, le circuit qui le définit
    (il peut lui-même contenir des composants). Le circuit de départ n'est pas
    modifié. Un puits de composant non relié donne 0 à l'intérieur ; une sortie de
    composant non reliée donne 0 à l'extérieur.

    Limite connue : l'aplatissement est récursif, donc il supporte environ 240 niveaux
    de composants dans des composants (mesuré avec la limite de récursion par défaut
    de Python, 1000). Au-delà, ``ComponentNestingError`` est levée au lieu d'un
    plantage.
    """
    try:
        return _Flattener(definitions).run(circuit)
    except RecursionError as error:
        raise ComponentNestingError(
            "Les composants sont imbriqués trop profondément pour être aplatis "
            "(limite de récursion de Python)."
        ) from error


def flat_nand_count(circuit: Circuit, definitions: Mapping[str, Circuit]) -> int:
    """Renvoie le coût : le nombre de NAND après aplatissement (cahier, « Coût »)."""
    return flatten(circuit, definitions).nand_count()
