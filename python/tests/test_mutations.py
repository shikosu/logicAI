"""Tests des mutations (cahier, « IA 1 : l'algorithme évolutionnaire »)."""

import random
from collections import defaultdict

import pytest

from builders import and_circuit, build_xor, gate, not_circuit, wire, xor_circuit
from logicai.circuit import Circuit, NodeKind, Pin, Wire
from logicai.errors import InvalidMutationRulesError
from logicai.filters import find_rejections
from logicai.library import Library
from logicai.mutations import (
    Mutation,
    MutationRules,
    apply_mutation,
    mutate,
)

# Réglages du palier 2 : jusqu'à 2 entrées, une seule sortie, pas de boucle.
LEVEL_2 = MutationRules(max_inputs=2, max_outputs=1)
SEEDS = range(40)


def _library_with_xor() -> Library:
    library = Library()
    library.register(xor_circuit())
    return library


def _snapshot(circuit: Circuit) -> tuple[object, object]:
    return circuit.nodes(), circuit.wires()


def _apply(
    kind: Mutation,
    circuit: Circuit,
    seed: int = 0,
    rules: MutationRules = LEVEL_2,
    library: Library | None = None,
) -> Circuit | None:
    return apply_mutation(
        kind, circuit, random.Random(seed), rules, library or Library()
    )


def _is_acyclic(circuit: Circuit) -> bool:
    """Cherche une boucle par tri topologique (indépendant du module testé)."""
    successors: dict[int, list[int]] = defaultdict(list)
    waiting = {node.node_id: 0 for node in circuit.nodes()}
    for w in circuit.wires():
        successors[w.source.node_id].append(w.sink.node_id)
        waiting[w.sink.node_id] += 1
    ready = [node_id for node_id, count in waiting.items() if count == 0]
    done = 0
    while ready:
        node_id = ready.pop()
        done += 1
        for next_id in successors[node_id]:
            waiting[next_id] -= 1
            if waiting[next_id] == 0:
                ready.append(next_id)
    return done == len(waiting)


def _assert_legal(circuit: Circuit, rules: MutationRules) -> None:
    """Vérifie les règles de câblage et les limites du palier, sans ``Circuit``."""
    nodes = {node.node_id: node for node in circuit.nodes()}
    sinks = set()
    for w in circuit.wires():
        assert w.source.node_id in nodes and w.sink.node_id in nodes
        assert 0 <= w.source.index < nodes[w.source.node_id].source_count
        assert 0 <= w.sink.index < nodes[w.sink.node_id].sink_count
        assert w.sink not in sinks  # un puits reçoit 0 ou 1 câble
        sinks.add(w.sink)
    assert len(circuit.inputs()) <= rules.max_inputs
    assert len(circuit.outputs()) <= rules.max_outputs
    if not rules.allow_loops:
        assert _is_acyclic(circuit)


# --- Ajouter une NAND, ajouter un composant ----------------------------------


def test_add_nand_adds_one_unwired_nand() -> None:
    # Règle : mutation « ajouter une NAND ». Possible même sur un circuit vide.
    parent = Circuit()
    child = _apply(Mutation.ADD_NAND, parent)
    assert child is not None
    assert (child.nand_count(), len(child.wires())) == (1, 0)
    assert parent.nand_count() == 0  # le parent n'est pas modifié


def test_add_component_poses_a_library_component() -> None:
    # Règle : mutation « ajouter un composant de la bibliothèque » : un nœud
    # COMPOSANT qui porte le nom du composant et ses nombres de broches (XOR : 2, 1).
    child = _apply(Mutation.ADD_COMPONENT, Circuit(), library=_library_with_xor())
    assert child is not None
    (node,) = child.nodes()
    assert (node.kind, node.component_ref) == (NodeKind.COMPONENT, "XOR")
    assert (node.sink_count, node.source_count) == (2, 1)


def test_add_component_chooses_among_all_components() -> None:
    # Règle : la mutation tire son composant au hasard dans toute la bibliothèque,
    # pas toujours le même.
    library = _library_with_xor()
    library.register(and_circuit())
    chosen = set()
    for seed in SEEDS:
        child = _apply(Mutation.ADD_COMPONENT, Circuit(), seed, library=library)
        assert child is not None
        chosen.add(child.nodes()[0].component_ref)
    assert chosen == {"XOR", "AND"}


def test_add_component_needs_a_component() -> None:
    # Règle : sans composant dans la bibliothèque, la mutation est impossible.
    assert _apply(Mutation.ADD_COMPONENT, Circuit()) is None


# --- Ajouter un câble --------------------------------------------------------


def test_add_wire_fills_the_free_sink_from_a_source() -> None:
    # Règles de câblage 1 à 3 : un câble va d'une source vers un puits libre. Dans un
    # NOT dont on libère le 2e puits de la NAND, le seul câble possible relie l'entrée
    # du circuit à ce puits (la NAND elle-même créerait une boucle).
    parent = not_circuit()
    parent.disconnect(Pin(1, 1))
    before = _snapshot(parent)
    for seed in SEEDS:
        child = _apply(Mutation.ADD_WIRE, parent, seed)
        assert child is not None
        assert child.wires()[-1] == Wire(Pin(0, 0), Pin(1, 1))
        assert len(child.wires()) == len(parent.wires()) + 1
        _assert_legal(child, LEVEL_2)
    assert _snapshot(parent) == before


def test_add_wire_chooses_among_free_sinks() -> None:
    # Règle : le puits à câbler est tiré au hasard parmi les puits libres. Une NAND
    # et une entrée : les deux puits de la NAND sont possibles, et chacun sort un jour.
    circuit = Circuit()
    wire(circuit, circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.NAND))
    chosen = set()
    for seed in SEEDS:
        child = _apply(Mutation.ADD_WIRE, circuit, seed)
        assert child is not None
        chosen.add(child.wires()[-1].sink.index)
    assert chosen == {1}  # le puits 0 est déjà pris : seul le puits 1 est libre
    two_free = Circuit()
    two_free.add_node(NodeKind.INPUT)
    two_free.add_node(NodeKind.NAND)
    chosen = {
        child.wires()[-1].sink.index
        for seed in SEEDS
        if (child := _apply(Mutation.ADD_WIRE, two_free, seed)) is not None
    }
    assert chosen == {0, 1}


def test_add_wire_needs_a_free_sink() -> None:
    # Règle de câblage 2 : un puits reçoit au plus un câble. Ici tous les puits sont
    # pris (NAND de NOT et sortie) : il n'y a plus rien à câbler.
    assert _apply(Mutation.ADD_WIRE, not_circuit()) is None


@pytest.mark.parametrize("seed", SEEDS)
def test_add_wire_never_creates_a_loop_when_loops_are_forbidden(seed: int) -> None:
    # Décision Q5 : les mutations des paliers 1 à 3 ne créent pas de boucle.
    # N1 alimente N2. Aucune entrée. Les puits de N1 ne peuvent recevoir que N2 (qui
    # dépend de N1) ou N1 elle-même : ce serait une boucle. Le seul câble sans boucle
    # est N1 vers le 2e puits de N2, quel que soit le puits choisi en premier.
    circuit = Circuit()
    n1, n2 = circuit.add_node(NodeKind.NAND), circuit.add_node(NodeKind.NAND)
    wire(circuit, n1, n2, 0)
    child = _apply(Mutation.ADD_WIRE, circuit, seed)
    assert child is not None
    assert child.wires()[-1] == Wire(Pin(n1, 0), Pin(n2, 1))


def test_add_wire_is_impossible_when_only_a_loop_is_left() -> None:
    # Décision Q5 : une NAND seule, sans entrée, ne peut se câbler qu'à elle-même.
    circuit = Circuit()
    circuit.add_node(NodeKind.NAND)
    assert _apply(Mutation.ADD_WIRE, circuit) is None


def test_add_wire_can_loop_when_loops_are_allowed() -> None:
    # Règle de câblage 5 : les boucles sont autorisées, y compris une sortie qui
    # revient sur sa propre porte. Quand le palier le permet, la mutation en pose une.
    circuit = Circuit()
    nand = circuit.add_node(NodeKind.NAND)
    rules = MutationRules(max_inputs=1, max_outputs=1, allow_loops=True)
    child = _apply(Mutation.ADD_WIRE, circuit, rules=rules)
    assert child is not None
    assert child.wires()[0].source == Pin(nand, 0)


def test_add_wire_uses_component_outputs_as_sources() -> None:
    # Règle de câblage 1 : la sortie d'un composant est une source. Sans entrée de
    # circuit, le seul câble possible va du composant vers la sortie du circuit.
    library = _library_with_xor()
    circuit = Circuit()
    xor = library.instantiate(circuit, "XOR")
    out = circuit.add_node(NodeKind.OUTPUT)
    for seed in SEEDS:
        child = _apply(Mutation.ADD_WIRE, circuit, seed, library=library)
        assert child is not None
        assert child.wires() == (Wire(Pin(xor, 0), Pin(out, 0)),)


# --- Retirer un câble, retirer un nœud ---------------------------------------


def test_remove_wire_frees_the_sink() -> None:
    # Règle : mutation « retirer un câble » ; le puits redevient libre (vaut 0).
    parent = not_circuit()
    child = _apply(Mutation.REMOVE_WIRE, parent)
    assert child is not None
    assert len(child.wires()) == len(parent.wires()) - 1
    removed = set(parent.wires()) - set(child.wires())
    (gone,) = removed
    assert child.source_of(gone.sink) is None


def test_remove_wire_chooses_among_all_wires() -> None:
    # Règle : le câble retiré est tiré au hasard ; les 3 câbles du NOT partent un jour.
    parent = not_circuit()
    removed = set()
    for seed in SEEDS:
        child = _apply(Mutation.REMOVE_WIRE, parent, seed)
        assert child is not None
        removed |= set(parent.wires()) - set(child.wires())
    assert removed == set(parent.wires())


def test_remove_wire_needs_a_wire() -> None:
    # Règle : sans câble, la mutation est impossible.
    assert _apply(Mutation.REMOVE_WIRE, Circuit()) is None


@pytest.mark.parametrize("seed", SEEDS)
def test_remove_node_removes_a_nand_and_its_wires(seed: int) -> None:
    # Règle : mutation « retirer un nœud ». Ici la seule NAND de NOT : elle part avec
    # ses 3 câbles, l'entrée et la sortie du circuit restent.
    child = _apply(Mutation.REMOVE_NODE, not_circuit(), seed)
    assert child is not None
    assert child.nand_count() == 0
    assert (len(child.inputs()), len(child.outputs()), len(child.wires())) == (1, 1, 0)


def test_remove_node_chooses_among_all_removable_nodes() -> None:
    # Règle : le nœud retiré est tiré au hasard ; avec deux NAND, chacune part un jour.
    circuit = Circuit()
    nands = {circuit.add_node(NodeKind.NAND), circuit.add_node(NodeKind.NAND)}
    removed = set()
    for seed in SEEDS:
        child = _apply(Mutation.REMOVE_NODE, circuit, seed)
        assert child is not None
        removed |= nands - {node.node_id for node in child.nodes()}
    assert removed == nands


def test_remove_node_can_remove_a_component() -> None:
    # Règle : un composant se retire comme une NAND.
    library = _library_with_xor()
    circuit = Circuit()
    library.instantiate(circuit, "XOR")
    child = _apply(Mutation.REMOVE_NODE, circuit, library=library)
    assert child is not None
    assert child.nodes() == ()


@pytest.mark.parametrize("seed", SEEDS)
def test_remove_node_never_removes_circuit_inputs_or_outputs(seed: int) -> None:
    # Interprétation retenue (à confirmer par Téo) : « retirer un nœud » ne touche
    # ni aux entrées ni aux sorties du circuit. Sans NAND ni composant, rien à faire.
    circuit = Circuit()
    wire(circuit, circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.OUTPUT))
    assert _apply(Mutation.REMOVE_NODE, circuit, seed) is None


# --- Ajouter une entrée ou une sortie, selon le palier -----------------------


def test_add_input_stops_at_the_level_maximum() -> None:
    # Décision Q4 : « ajouter une entrée » s'arrête au maximum du palier.
    one_input = gate(1, lambda circuit, i: i[0])
    child = _apply(Mutation.ADD_INPUT, one_input)  # palier 2 : max 2 entrées
    assert child is not None
    assert len(child.inputs()) == 2
    assert _apply(Mutation.ADD_INPUT, child) is None  # déjà 2 entrées


def test_add_output_is_forbidden_at_levels_with_one_output() -> None:
    # Décision Q4 : aux paliers 1 à 3 il n'y a qu'une sortie, donc « ajouter une
    # sortie » est interdit dès que le circuit en a une.
    assert _apply(Mutation.ADD_OUTPUT, not_circuit()) is None
    assert _apply(Mutation.ADD_OUTPUT, Circuit()) is not None  # 0 sortie : permis


def test_add_output_allows_several_outputs_when_the_level_does() -> None:
    # Règle : à partir du palier 4, plusieurs sorties sont permises.
    rules = MutationRules(max_inputs=4, max_outputs=2)
    child = _apply(Mutation.ADD_OUTPUT, not_circuit(), rules=rules)
    assert child is not None
    assert len(child.outputs()) == 2


def test_rules_refuse_negative_maximums() -> None:
    # Règle : erreurs dédiées avec un message qui dit ce qui est refusé.
    with pytest.raises(InvalidMutationRulesError):
        MutationRules(max_inputs=-1, max_outputs=1)
    with pytest.raises(InvalidMutationRulesError):
        MutationRules(max_inputs=1, max_outputs=-1)
    MutationRules(max_inputs=0, max_outputs=0)  # zéro est permis


# --- mutate : choix au hasard, parent intact ---------------------------------


# Réglages assez larges pour que les 7 mutations soient possibles sur ``_rich_circuit``.
RICH_RULES = MutationRules(max_inputs=3, max_outputs=2)


def _rich_circuit() -> Circuit:
    """Un circuit où les 7 mutations sont possibles (avec RICH_RULES et XOR)."""
    circuit = Circuit()
    input_id = circuit.add_node(NodeKind.INPUT)
    nand = circuit.add_node(NodeKind.NAND)
    wire(circuit, input_id, nand, 0)
    circuit.add_node(NodeKind.OUTPUT)
    return circuit


def test_all_seven_mutations_can_be_drawn() -> None:
    # Règle : les 7 mutations du cahier existent et sont toutes tirées un jour.
    library, rng = _library_with_xor(), random.Random(0)
    drawn = {mutate(_rich_circuit(), rng, RICH_RULES, library).kind for _ in range(400)}
    assert drawn == set(Mutation)


def test_mutate_always_succeeds_because_adding_a_nand_is_always_possible() -> None:
    # Règle : sur un circuit vide, sans entrée ni sortie permise ni composant, seule
    # « ajouter une NAND » est possible ; mutate la trouve.
    empty_rules = MutationRules(max_inputs=0, max_outputs=0)
    for seed in SEEDS:
        result = mutate(Circuit(), random.Random(seed), empty_rules, Library())
        assert result.kind is Mutation.ADD_NAND


def test_mutations_never_change_the_parent() -> None:
    # Règle : une opération laisse l'objet d'origine inchangé (CLAUDE.md) ; les
    # parents restent intacts pour pouvoir être mutés encore.
    library, parent = _library_with_xor(), _rich_circuit()
    before = _snapshot(parent)
    rng = random.Random(1)
    for kind in Mutation:
        apply_mutation(kind, parent, rng, RICH_RULES, library)
        assert _snapshot(parent) == before
    for _ in range(50):
        mutate(parent, rng, RICH_RULES, library)
    assert _snapshot(parent) == before


# --- Graine : mêmes données, même résultat -----------------------------------


def _chain(seed: int, steps: int) -> list[tuple[Mutation, object]]:
    """Enchaîne ``steps`` mutations et note la mutation et le circuit de chaque pas."""
    library, rng = _library_with_xor(), random.Random(seed)
    circuit, history = _rich_circuit(), []
    for _ in range(steps):
        result = mutate(circuit, rng, RICH_RULES, library)
        circuit = result.circuit
        history.append((result.kind, _snapshot(circuit)))
    return history


def test_same_seed_gives_the_same_mutations() -> None:
    # Règle (CLAUDE.md) : tout tirage aléatoire passe par un générateur avec une
    # graine, pour que les résultats soient reproductibles.
    assert _chain(7, 60) == _chain(7, 60)


def test_different_seeds_give_different_mutations() -> None:
    # Règle : la graine compte vraiment (sinon le test précédent ne prouverait rien).
    assert len({repr(_chain(seed, 20)) for seed in range(10)}) > 1


def test_global_random_state_is_never_used() -> None:
    # Règle : seul le générateur donné compte, pas l'état global de ``random``.
    random.seed(1)
    first = _chain(3, 40)
    random.seed(2)
    assert _chain(3, 40) == first


# --- Légalité sur de longues suites de mutations -----------------------------


def _starting_circuits() -> list[Circuit]:
    return [Circuit(), not_circuit(), gate(2, build_xor), _rich_circuit()]


@pytest.mark.parametrize("start", range(4))
def test_long_chains_stay_legal_and_loop_free(start: int) -> None:
    # Règles de câblage 1 à 3, vérifiées avant chaque action : une suite de mutations
    # ne produit jamais un circuit illégal, ne dépasse pas les limites du palier, et
    # (Q5) ne crée jamais de boucle. De plus, les filtres savent juger chaque résultat.
    library = _library_with_xor()
    for seed in range(25):
        rng, circuit = random.Random(seed), _starting_circuits()[start]
        for _ in range(60):
            circuit = mutate(circuit, rng, RICH_RULES, library).circuit
            _assert_legal(circuit, RICH_RULES)
            find_rejections(circuit, library.definitions())  # ne doit pas lever


def test_long_chains_stay_legal_when_loops_are_allowed() -> None:
    # Règle de câblage 5 : avec des boucles permises, les circuits restent légaux
    # (une boucle n'est pas une erreur), et les mutations en créent bien parfois.
    rules = MutationRules(max_inputs=3, max_outputs=2, allow_loops=True)
    library, loops_seen = _library_with_xor(), 0
    for seed in range(25):
        rng, circuit = random.Random(seed), _rich_circuit()
        for _ in range(60):
            circuit = mutate(circuit, rng, rules, library).circuit
            _assert_legal(circuit, rules)
        loops_seen += not _is_acyclic(circuit)
    assert loops_seen > 0
