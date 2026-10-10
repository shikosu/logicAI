"""Tests du nœud CLK : modèle, simulation, aplatissement, nettoyage, JSON, placement.

Cahier, « Les éléments » : « CLK | 1 source | Horloge fournie par la simulation, que
l'IA peut câbler ». Décision de Téo (10 octobre 2026) : la CLK est un nœud que l'IA pose
et câble comme une NAND ; ce n'est pas une broche du composant.
"""

import pytest

from builders import add_nand, add_not, sr_latch, wire
from logicai.behavior import truth_table
from logicai.circuit import Circuit, NodeKind, Pin
from logicai.cleanup import remove_useless_nodes
from logicai.errors import SimulationError, WrongPinKindError
from logicai.flatten import flat_nand_count, flatten
from logicai.layout import compute_layout
from logicai.serialization import circuit_from_json, circuit_to_json
from logicai.simulation import Status, settle, tick
from logicai.snapshot import settled_snapshot

# Masque d'une seule combinaison d'entrées : les signaux valent 0 ou 1.
ONE_COMBINATION = 1


def _clock_to_output() -> Circuit:
    """Une CLK reliée directement à une sortie."""
    circuit = Circuit()
    clock = circuit.add_node(NodeKind.CLK)
    wire(circuit, clock, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _inverted_clock() -> Circuit:
    """Une CLK, un NOT (NAND dont les deux puits sont sur la CLK), et une sortie."""
    circuit = Circuit()
    clock = circuit.add_node(NodeKind.CLK)
    wire(circuit, add_not(circuit, clock), circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _d_latch() -> Circuit:
    """Bascule D à horloge : entrée D, une CLK, 5 NAND, sortie Q.

    S̄ = NAND(D, CLK), R̄ = NAND(NON D, CLK), puis la bascule SR en NAND.
    Quand CLK = 1, Q suit D ; quand CLK = 0, Q garde sa valeur.
    """
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    clock = circuit.add_node(NodeKind.CLK)
    not_data = add_not(circuit, data)
    set_bar = add_nand(circuit, data, clock)
    reset_bar = add_nand(circuit, not_data, clock)
    q = circuit.add_node(NodeKind.NAND)
    q_bar = circuit.add_node(NodeKind.NAND)
    wire(circuit, set_bar, q, 0)
    wire(circuit, q_bar, q, 1)
    wire(circuit, reset_bar, q_bar, 0)
    wire(circuit, q, q_bar, 1)
    wire(circuit, q, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _clock_component_definition() -> Circuit:
    """Définition d'un composant sans entrée : CLK, un NOT, une sortie."""
    return _inverted_clock()


# --- Le modèle ---------------------------------------------------------------------


def test_clock_has_one_source_and_no_sink() -> None:
    # Cahier, « Les éléments » : CLK = 1 source (et aucun puits).
    circuit = Circuit()
    clock = circuit.add_node(NodeKind.CLK)
    node = circuit.node(clock)
    assert (node.sink_count, node.source_count) == (0, 1)


def test_clock_is_not_a_circuit_pin() -> None:
    # Décision de Téo : la CLK n'est pas une broche du composant (ni entrée, ni sortie).
    circuit = _d_latch()
    assert len(circuit.inputs()) == 1
    assert len(circuit.outputs()) == 1
    assert len(circuit.clocks()) == 1


def test_clocks_are_listed_in_creation_order() -> None:
    circuit = Circuit()
    first = circuit.add_node(NodeKind.CLK)
    circuit.add_node(NodeKind.NAND)
    second = circuit.add_node(NodeKind.CLK)
    assert circuit.clocks() == (first, second)


def test_wire_into_a_clock_is_refused_and_changes_nothing() -> None:
    # Règle de câblage 1 : un câble va d'une source vers un puits ; la CLK n'a pas de
    # puits. L'index 0 existe comme source seulement : mauvais genre de broche.
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    clock = circuit.add_node(NodeKind.CLK)
    with pytest.raises(WrongPinKindError):
        circuit.connect(Pin(data, 0), Pin(clock, 0))
    assert circuit.wires() == ()


def test_clock_can_feed_unlimited_sinks() -> None:
    # Règle de câblage 3 : une source alimente un nombre illimité de puits.
    circuit = Circuit()
    clock = circuit.add_node(NodeKind.CLK)
    for _ in range(5):
        nand = circuit.add_node(NodeKind.NAND)
        wire(circuit, clock, nand, 0)
        wire(circuit, clock, nand, 1)
    assert len(circuit.wires()) == 10


# --- La simulation -----------------------------------------------------------------


def test_circuit_with_a_clock_refuses_to_run_without_the_clock_value() -> None:
    # La valeur de la CLK est imposée par la simulation : l'oublier n'est pas un 0.
    circuit = _inverted_clock()
    with pytest.raises(SimulationError, match="CLK"):
        settle(circuit, [], ONE_COMBINATION)
    with pytest.raises(SimulationError, match="CLK"):
        tick(circuit, [], ONE_COMBINATION)


def test_truth_table_and_snapshot_do_not_guess_the_clock() -> None:
    # La table de vérité (combinatoire) et les relevés ne donnent pas de valeur à la
    # CLK : ils refusent un circuit qui en a une, au lieu de la prendre pour 0.
    circuit = _d_latch()
    with pytest.raises(SimulationError, match="CLK"):
        truth_table(circuit)
    with pytest.raises(SimulationError, match="CLK"):
        settled_snapshot(circuit, [0])


def test_circuit_without_a_clock_ignores_the_clock_value() -> None:
    # Sans CLK dans le circuit, la valeur de l'horloge n'est lue par personne.
    circuit = sr_latch()
    plain = settle(circuit, [0, 1], ONE_COMBINATION)
    with_clock = settle(circuit, [0, 1], ONE_COMBINATION, clock=1)
    assert plain == with_clock


def test_clock_value_must_fit_the_mask() -> None:
    # Comme les entrées : une valeur qui ne tient pas dans le masque est refusée.
    with pytest.raises(SimulationError, match="horloge"):
        settle(_clock_to_output(), [], ONE_COMBINATION, clock=2)
    with pytest.raises(SimulationError, match="horloge"):
        settle(_clock_to_output(), [], ONE_COMBINATION, clock=-1)


@pytest.mark.parametrize("clock", [0, 1])
def test_clock_to_output_has_no_delay(clock: int) -> None:
    # La CLK est une source comme une entrée : sans retard, lue au même top.
    result = settle(_clock_to_output(), [], ONE_COMBINATION, clock=clock)
    assert (result.status, result.outputs) == (Status.STABLE, (clock,))


@pytest.mark.parametrize(("clock", "expected"), [(0, 1), (1, 0)])
def test_nand_on_the_clock_inverts_it_after_one_tick(clock: int, expected: int) -> None:
    # Retard d'1 top par NAND : la CLK est lue tout de suite, la NAND répond au top 1.
    circuit = _inverted_clock()
    assert tick(circuit, [], ONE_COMBINATION, clock=clock) == (expected,)
    result = settle(circuit, [], ONE_COMBINATION, clock=clock)
    assert (result.status, result.outputs) == (Status.STABLE, (expected,))


def test_all_clocks_of_a_circuit_share_the_same_clock() -> None:
    # Décision de Téo : toutes les CLK d'un circuit sont la même horloge.
    circuit = Circuit()
    for _ in range(2):
        wire(circuit, circuit.add_node(NodeKind.CLK), circuit.add_node(NodeKind.OUTPUT))
    for clock in (0, 1):
        result = settle(circuit, [], ONE_COMBINATION, clock=clock)
        assert result.outputs == (clock, clock)


def test_clock_is_read_bit_by_bit_in_parallel_simulation() -> None:
    # Simulation bit-parallèle : le bit k de la CLK est la CLK de la combinaison k.
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    clock = circuit.add_node(NodeKind.CLK)
    wire(circuit, add_nand(circuit, data, clock), circuit.add_node(NodeKind.OUTPUT))
    result = settle(circuit, [0b1100], 0b1111, clock=0b1010)
    assert result.outputs == (0b0111,)  # ~(0b1100 & 0b1010) & 0b1111


def test_d_latch_follows_while_the_clock_is_high_and_holds_while_it_is_low() -> None:
    # Cahier, « L'entrée CLK » : chaque moitié de période laisse le circuit se
    # stabiliser (un appel à settle par moitié). Le test part de CLK = 1 : voir le
    # test suivant pour CLK = 0.
    circuit = _d_latch()
    state: tuple[int, ...] | None = None
    # (D, CLK, Q attendu) : suit, garde, suit, garde.
    for data, clock, expected in ((1, 1, 1), (0, 0, 1), (0, 1, 0), (1, 0, 0)):
        result = settle(circuit, [data], ONE_COMBINATION, state, clock)
        assert result.status is Status.STABLE
        assert result.outputs == (expected,)
        state = result.state


def test_d_latch_started_with_a_low_clock_oscillates() -> None:
    # Piège du cahier : toutes les sorties à 0 au départ, et CLK = 0 donne S̄ = R̄ = 1
    # sur la bascule SR : elle oscille (métastabilité simulée), donc instable.
    result = settle(_d_latch(), [0], ONE_COMBINATION, None, 0)
    assert result.status is Status.UNSTABLE


# --- Aplatissement et nettoyage -----------------------------------------------------


def test_flatten_keeps_the_clock_of_a_component() -> None:
    # Une CLK dans un composant reste une CLK dans le circuit aplati, sans broche en
    # plus pour le composant.
    parent = Circuit()
    box = parent.add_component_node("CLOCKED", 0, 1)
    parent.connect(Pin(box, 0), Pin(parent.add_node(NodeKind.OUTPUT), 0))
    flat = flatten(parent, {"CLOCKED": _clock_component_definition()})
    assert len(flat.clocks()) == 1
    assert flat.nand_count() == 1
    for clock in (0, 1):
        assert settle(flat, [], ONE_COMBINATION, clock=clock).outputs == (1 - clock,)


def test_two_instances_of_a_clocked_component_share_the_clock() -> None:
    # Décision de Téo : toutes les CLK sont la même horloge, même dans deux composants.
    parent = Circuit()
    for _ in range(2):
        box = parent.add_component_node("CLOCKED", 0, 1)
        parent.connect(Pin(box, 0), Pin(parent.add_node(NodeKind.OUTPUT), 0))
    definitions = {"CLOCKED": _clock_component_definition()}
    flat = flatten(parent, definitions)
    assert len(flat.clocks()) == 2
    assert flat_nand_count(parent, definitions) == 2
    assert settle(flat, [], ONE_COMBINATION, clock=1).outputs == (0, 0)


def test_cleanup_removes_a_clock_that_feeds_nothing_useful() -> None:
    # Cahier, « Nettoyage » : on retire ce qui n'influence aucune sortie.
    circuit = _d_latch()
    useless_clock = circuit.add_node(NodeKind.CLK)
    useless_nand = circuit.add_node(NodeKind.NAND)
    wire(circuit, useless_clock, useless_nand, 0)
    cleaned = remove_useless_nodes(circuit)
    assert len(cleaned.clocks()) == 1
    assert cleaned.nand_count() == 5  # les 5 NAND de la bascule D, sans la NAND inutile


def test_cleanup_keeps_the_clock_that_feeds_an_output() -> None:
    cleaned = remove_useless_nodes(_inverted_clock())
    assert len(cleaned.clocks()) == 1
    assert cleaned.nand_count() == 1


# --- JSON et placement --------------------------------------------------------------


def test_clock_survives_a_json_round_trip() -> None:
    # Cahier, « Exemple de circuit en JSON » : un type de nœud de plus, "CLK".
    circuit = _d_latch()
    text = circuit_to_json("D-LATCH", circuit)
    assert '"type": "CLK"' in text
    name, restored = circuit_from_json(text)
    assert name == "D-LATCH"
    assert restored.nodes() == circuit.nodes()
    assert restored.wires() == circuit.wires()


def test_clock_is_placed_in_the_first_column_like_an_input() -> None:
    # Cahier : les colonnes sont x = 2 × couche ; la CLK, source sans prédécesseur,
    # est dans la couche 0 avec les entrées.
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    clock = circuit.add_node(NodeKind.CLK)
    wire(circuit, add_nand(circuit, data, clock), circuit.add_node(NodeKind.OUTPUT))
    layout = compute_layout(circuit)
    assert layout[data].x == 0
    assert layout[clock].x == 0
    assert layout[data].y != layout[clock].y
