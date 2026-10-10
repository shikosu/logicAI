"""Constructeurs de petits circuits, partagés par les tests."""

import random
from collections.abc import Callable

from logicai.circuit import Circuit, NodeKind, Pin

# Une fonction qui câble des portes à partir des entrées et renvoie l'identifiant
# du nœud dont la valeur doit sortir du circuit.
Builder = Callable[[Circuit, list[int]], int]


def wire(circuit: Circuit, source_id: int, sink_id: int, sink_index: int = 0) -> None:
    """Relie la source 0 d'un nœud au puits ``sink_index`` d'un autre."""
    circuit.connect(Pin(source_id, 0), Pin(sink_id, sink_index))


def add_nand(circuit: Circuit, source_a: int, source_b: int) -> int:
    """Ajoute une NAND alimentée par deux sources et renvoie son identifiant."""
    nand_id = circuit.add_node(NodeKind.NAND)
    wire(circuit, source_a, nand_id, 0)
    wire(circuit, source_b, nand_id, 1)
    return nand_id


def add_not(circuit: Circuit, source_id: int) -> int:
    """Ajoute un NOT : une NAND dont les deux puits ont la même source."""
    return add_nand(circuit, source_id, source_id)


def gate(input_count: int, build: Builder) -> Circuit:
    """Crée les entrées, laisse ``build`` câbler les portes, puis ajoute la sortie."""
    circuit = Circuit()
    inputs = [circuit.add_node(NodeKind.INPUT) for _ in range(input_count)]
    wire(circuit, build(circuit, inputs), circuit.add_node(NodeKind.OUTPUT))
    return circuit


def build_not(circuit: Circuit, i: list[int]) -> int:
    return add_not(circuit, i[0])


def build_nand(circuit: Circuit, i: list[int]) -> int:
    return add_nand(circuit, i[0], i[1])


def build_and(circuit: Circuit, i: list[int]) -> int:
    return add_not(circuit, add_nand(circuit, i[0], i[1]))


def build_or(circuit: Circuit, i: list[int]) -> int:
    return add_nand(circuit, add_not(circuit, i[0]), add_not(circuit, i[1]))


def build_xor(circuit: Circuit, i: list[int]) -> int:
    n1 = add_nand(circuit, i[0], i[1])
    n2 = add_nand(circuit, i[0], n1)
    n3 = add_nand(circuit, i[1], n1)
    return add_nand(circuit, n2, n3)


def build_and_not(circuit: Circuit, i: list[int]) -> int:
    """Construit A ET NON B : 3 NAND."""
    return add_not(circuit, add_nand(circuit, i[0], add_not(circuit, i[1])))


def build_not_and(circuit: Circuit, i: list[int]) -> int:
    """NON A ET B : 3 NAND. Même fonction que ``build_and_not``, entrées échangées."""
    return add_not(circuit, add_nand(circuit, add_not(circuit, i[0]), i[1]))


def build_mux(circuit: Circuit, i: list[int]) -> int:
    """Multiplexeur : (entrée 0 ? entrée 2 : entrée 1), 4 NAND."""
    select, low, high = i
    return add_nand(
        circuit,
        add_nand(circuit, add_not(circuit, select), low),
        add_nand(circuit, select, high),
    )


def build_mux_rotated(circuit: Circuit, i: list[int]) -> int:
    """Le même multiplexeur, mais câblé avec les entrées dans un autre ordre."""
    return build_mux(circuit, [i[1], i[2], i[0]])


def build_mux_with_roles(roles: tuple[int, int, int]) -> Builder:
    """Multiplexeur dont (sélecteur, bas, haut) sont les entrées roles[0], [1], [2]."""

    def build(circuit: Circuit, inputs: list[int]) -> int:
        return build_mux(circuit, [inputs[role] for role in roles])

    return build


def bloated(build: Builder) -> Builder:
    """Ajoute deux NOT en série à la sortie d'une porte (2 NAND de plus)."""

    def build_bloated(circuit: Circuit, inputs: list[int]) -> int:
        return add_not(circuit, add_not(circuit, build(circuit, inputs)))

    return build_bloated


def not_circuit() -> Circuit:
    """NOT : 1 entrée, 1 NAND, 1 sortie."""
    return gate(1, build_not)


def and_circuit() -> Circuit:
    """AND : 2 entrées, 2 NAND, 1 sortie."""
    return gate(2, build_and)


def xor_circuit() -> Circuit:
    """XOR : 2 entrées, 4 NAND, 1 sortie."""
    return gate(2, build_xor)


def chain_of_nots(count: int) -> Circuit:
    """Une entrée, ``count`` NOT en chaîne, une sortie."""

    def build(circuit: Circuit, inputs: list[int]) -> int:
        node_id = inputs[0]
        for _ in range(count):
            node_id = add_not(circuit, node_id)
        return node_id

    return gate(1, build)


def pass_through() -> Circuit:
    """Une entrée reliée directement à une sortie : un fil, sans NAND."""
    circuit = Circuit()
    wire(circuit, circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.OUTPUT))
    return circuit


def sr_latch() -> Circuit:
    """Bascule SR en NAND : Q = NAND(S̄, Q̄) et Q̄ = NAND(R̄, Q).

    Entrées dans l'ordre (S̄, R̄) ; sorties dans l'ordre (Q, Q̄).
    """
    circuit = Circuit()
    s_bar = circuit.add_node(NodeKind.INPUT)
    r_bar = circuit.add_node(NodeKind.INPUT)
    nand_q = circuit.add_node(NodeKind.NAND)
    nand_q_bar = circuit.add_node(NodeKind.NAND)
    wire(circuit, s_bar, nand_q, 0)
    wire(circuit, nand_q_bar, nand_q, 1)
    wire(circuit, r_bar, nand_q_bar, 0)
    wire(circuit, nand_q, nand_q_bar, 1)
    wire(circuit, nand_q, circuit.add_node(NodeKind.OUTPUT))
    wire(circuit, nand_q_bar, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def random_circuit(rng: random.Random) -> Circuit:
    """Un circuit au hasard, avec des boucles, des fan-out et des câbles manquants."""
    circuit = Circuit()
    inputs = [circuit.add_node(NodeKind.INPUT) for _ in range(rng.randint(0, 4))]
    nands = [circuit.add_node(NodeKind.NAND) for _ in range(rng.randint(0, 12))]
    outputs = [circuit.add_node(NodeKind.OUTPUT) for _ in range(rng.randint(0, 4))]
    sources = inputs + nands
    if not sources:
        return circuit
    for nand_id in nands:
        for sink_index in (0, 1):
            if rng.random() < 0.85:
                circuit.connect(Pin(rng.choice(sources), 0), Pin(nand_id, sink_index))
    for output_id in outputs:
        if rng.random() < 0.9:
            circuit.connect(Pin(rng.choice(sources), 0), Pin(output_id, 0))
    return circuit
