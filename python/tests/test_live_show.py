"""Tests de ce qu'on montre pour un essai en direct (cahier, « Affichage »)."""

from collections.abc import Sequence
from typing import Any

from builders import (
    add_nand,
    add_not,
    bloated,
    build_and,
    build_mux,
    build_xor,
    gate,
    not_circuit,
    wire,
    xor_circuit,
)
from logicai.circuit import Circuit, NodeKind
from logicai.library import Library
from logicai.live_show import MAX_SHOWN_COMBINATIONS, shown_nand_count, trial_messages
from logicai.protocol import (
    CIRCUIT_MESSAGE,
    STATE_MESSAGE,
    decode_message,
    encode_message,
)
from logicai.serialization import circuit_from_dict
from logicai.snapshot import settled_snapshot

NO_COMPONENTS: dict[str, Circuit] = {}


Message = dict[str, Any]


def _show(
    circuit: Circuit, definitions: dict[str, Circuit] | None = None
) -> tuple[Message, ...]:
    return trial_messages(
        circuit, NO_COMPONENTS if definitions is None else definitions
    )


def _frames(messages: Sequence[Message]) -> list[Message]:
    """Garde le contenu des messages ``etat``."""
    return [m["etat"] for m in messages if m["message"] == STATE_MESSAGE]


def _runs(frames: Sequence[Message]) -> list[list[Message]]:
    """Découpe les images en combinaisons : une nouvelle combinaison repart du top 0."""
    runs: list[list[Message]] = []
    for frame in frames:
        if frame["top"] == 0:
            runs.append([])
        runs[-1].append(frame)
    return runs


# --- La forme d'un essai -----------------------------------------------------


def test_trial_is_a_circuit_message_then_state_frames() -> None:
    # Règle : un essai montré = un message « circuit » puis des messages « etat ».
    messages = _show(not_circuit())
    assert messages[0]["message"] == CIRCUIT_MESSAGE
    assert messages[0]["circuit"]["nom"] == "essai"  # (Unity affiche ce nom)
    assert all(m["message"] == STATE_MESSAGE for m in messages[1:])


def test_not_circuit_frames_follow_the_ticks() -> None:
    # Règle : cahier, « La simulation par tops » : chaque NAND a un retard de 1 top,
    # toutes les sorties valent 0 au départ. NOT, entrée A = 0 : au top 0 la NAND vaut
    # encore 0 (instable), au top 1 elle vaut 1 (stable) : 2 images. A = 1 : NAND(1, 1)
    # = 0, déjà stable au top 0 : 1 image. Nœuds : entrée, NAND, sortie.
    frames = _frames(_show(not_circuit()))
    assert [(f["top"], f["stable"], f["noeuds"], f["cables"]) for f in frames] == [
        (0, False, [0, 0, 0], [0, 0, 0]),
        (1, True, [0, 1, 1], [0, 0, 1]),
        (0, True, [1, 0, 0], [1, 1, 0]),
    ]


def test_each_combination_restarts_and_ends_stable() -> None:
    # Règle : chaque combinaison d'entrées repart du top 0 et se termine par un top
    # stable (un circuit sans boucle se stabilise toujours : T_max + 1 tops).
    messages = _show(gate(2, build_xor))
    runs = _runs(_frames(messages))
    assert len(runs) == 4  # 2 entrées : 4 combinaisons
    for run in runs:
        assert [f["top"] for f in run] == list(range(len(run)))
        assert run[-1]["stable"] and not any(f["stable"] for f in run[:-1])


def test_last_frame_of_each_combination_is_the_settled_state() -> None:
    # Règle : la dernière image d'une combinaison est l'état stabilisé du circuit
    # (même relevé que ``settled_snapshot``), pour chacune des 4 combinaisons du XOR.
    circuit = gate(2, build_xor)
    runs = _runs(_frames(_show(circuit)))
    for k, run in enumerate(runs):
        settled = settled_snapshot(circuit, (k & 1, (k >> 1) & 1))
        assert run[-1]["noeuds"] == list(settled.node_values)
        assert run[-1]["cables"] == list(settled.wire_values)


def test_frames_match_the_circuit_sent_first() -> None:
    # Règle : chaque image a une valeur par nœud et par câble du circuit envoyé avant.
    messages = _show(gate(3, build_mux))
    _, circuit = circuit_from_dict(messages[0]["circuit"])
    for frame in _frames(messages):
        assert len(frame["noeuds"]) == len(circuit.nodes())
        assert len(frame["cables"]) == len(circuit.wires())


def test_messages_are_valid_protocol_messages() -> None:
    # Règle : tout message produit s'écrit en ligne JSON et se relit à l'identique.
    for message in _show(gate(2, build_and)):
        assert decode_message(encode_message(message)) == message


# --- Aplati, nettoyé, borné --------------------------------------------------


def test_components_are_flattened_so_that_wires_have_values() -> None:
    # Règle : les valeurs ne sont pas suivies dans un composant : l'essai est montré
    # aplati (que des NAND), avec des valeurs pour chaque fil.
    library = Library()
    library.register(xor_circuit())
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    xor = library.instantiate(circuit, "XOR")
    wire(circuit, a, xor, 0)
    wire(circuit, b, xor, 1)
    wire(circuit, xor, circuit.add_node(NodeKind.OUTPUT))
    messages = _show(circuit, dict(library.definitions()))
    kinds = {n["type"] for n in messages[0]["circuit"]["noeuds"]}
    assert kinds == {"ENTREE", "NAND", "SORTIE"}
    assert (
        len([n for n in messages[0]["circuit"]["noeuds"] if n["type"] == "NAND"]) == 4
    )
    assert len(_runs(_frames(messages))) == 4


def test_useless_nodes_are_not_shown() -> None:
    # Règle : on montre ce que le simulateur garde (cahier : « nettoyage ») : une NAND
    # qui n'alimente aucune sortie n'apparaît pas.
    circuit = not_circuit()
    junk = add_nand(circuit, circuit.inputs()[0], circuit.inputs()[0])
    assert junk not in [n["id"] for n in _show(circuit)[0]["circuit"]["noeuds"]]
    assert len(_show(circuit)[0]["circuit"]["noeuds"]) == 3


def test_number_of_combinations_is_bounded() -> None:
    # Règle : au plus ``MAX_SHOWN_COMBINATIONS`` combinaisons sont montrées (4 entrées
    # en ont 16 ; un essai ne doit pas durer trop longtemps à regarder).
    circuit = Circuit()
    inputs = [circuit.add_node(NodeKind.INPUT) for _ in range(4)]
    nand = add_nand(circuit, inputs[0], inputs[1])
    nand2 = add_nand(circuit, inputs[2], inputs[3])
    wire(circuit, add_nand(circuit, nand, nand2), circuit.add_node(NodeKind.OUTPUT))
    assert len(_runs(_frames(_show(circuit)))) == MAX_SHOWN_COMBINATIONS


def test_circuit_without_inputs_shows_one_combination() -> None:
    # Règle : sans entrée, il n'y a qu'une combinaison (2**0 = 1) : on la montre.
    circuit = Circuit()
    wire(circuit, circuit.add_node(NodeKind.NAND), circuit.add_node(NodeKind.OUTPUT))
    assert len(_runs(_frames(_show(circuit)))) == 1


def test_unstable_circuit_shows_a_bounded_number_of_frames() -> None:
    # Règle : un circuit instable ne se stabilise jamais : on montre les tops jusqu'à la
    # limite T_max + 1 (ici 1 NAND : tops 0 à 2), sans jamais tourner indéfiniment.
    circuit = Circuit()
    nand = circuit.add_node(NodeKind.NAND)
    wire(circuit, nand, nand, 0)
    wire(circuit, nand, nand, 1)
    wire(circuit, nand, circuit.add_node(NodeKind.OUTPUT))
    frames = _frames(_show(circuit))
    assert [f["top"] for f in frames] == [0, 1, 2]
    assert not any(f["stable"] for f in frames)


def test_circuit_given_is_not_changed() -> None:
    # Règle : un contrôle ne modifie jamais l'objet contrôlé.
    circuit = gate(2, build_xor)
    before = (circuit.nodes(), circuit.wires())
    _show(circuit)
    assert (circuit.nodes(), circuit.wires()) == before


# --- La taille de ce qu'on montre ----------------------------------------------


def _nand_count_in_message(messages: Sequence[Message]) -> int:
    """Compte les NAND du circuit contenu dans le message ``circuit`` d'un essai."""
    first = next(m for m in messages if m["message"] == CIRCUIT_MESSAGE)
    return circuit_from_dict(first["circuit"])[1].nand_count()


def _with_xor_component_and_nots(library: Library, extra_nots: int) -> Circuit:
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    node = library.instantiate(circuit, "XOR")
    wire(circuit, a, node, 0)
    wire(circuit, b, node, 1)
    for _ in range(extra_nots):
        node = add_not(circuit, node)
    wire(circuit, node, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _with_dead_end() -> Circuit:
    def build(circuit: Circuit, inputs: list[int]) -> int:
        out = build_xor(circuit, inputs)
        add_not(circuit, add_not(circuit, out))  # n'influence aucune sortie
        return out

    return gate(2, build)


def test_shown_size_is_the_size_of_the_circuit_sent_to_unity() -> None:
    # Règle (choix de Téo : ne pas montrer d'essais énormes) : la taille mesurée est
    # celle du circuit que reçoit Unity, pour des circuits simples, redondants, avec une
    # impasse ou avec un composant.
    library = Library()
    library.register(xor_circuit())
    definitions = library.definitions()
    circuits = {
        "NOT": not_circuit(),
        "XOR": xor_circuit(),
        "XOR redondant": gate(2, bloated(build_xor)),
        "impasse": _with_dead_end(),
        "composant": _with_xor_component_and_nots(library, 3),
    }
    for name, circuit in circuits.items():
        expected = _nand_count_in_message(_show(circuit, definitions))
        assert shown_nand_count(circuit, definitions) == expected, name


def test_shown_size_ignores_useless_nodes_and_flattens_components() -> None:
    # Règle : l'impasse (2 NAND qui n'influencent aucune sortie) ne compte pas ; un
    # composant compte pour les NAND qu'il contient.
    library = Library()
    library.register(xor_circuit())
    definitions = library.definitions()
    assert _with_dead_end().nand_count() == 6
    assert shown_nand_count(_with_dead_end(), definitions) == 4
    assert shown_nand_count(_with_xor_component_and_nots(library, 3), definitions) == 7


def test_shown_size_does_not_change_the_circuit() -> None:
    circuit = _with_dead_end()
    before = (circuit.nodes(), circuit.wires())
    shown_nand_count(circuit, NO_COMPONENTS)
    assert (circuit.nodes(), circuit.wires()) == before
