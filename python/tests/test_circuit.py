"""Tests du modèle de circuit : nœuds, broches, câbles et règles de câblage."""

from collections.abc import Callable
from typing import NamedTuple

import pytest

from logicai.circuit import Circuit, Node, NodeKind, Pin, Wire
from logicai.errors import (
    CircuitError,
    SinkAlreadyConnectedError,
    SinkNotConnectedError,
    UnknownNodeError,
    UnknownPinError,
    WrongPinKindError,
)

# Un identifiant qu'aucun circuit de ces tests ne crée.
UNKNOWN_NODE_ID = 999


class _Ids(NamedTuple):
    """Identifiants du petit circuit de base construit par ``_build``."""

    input_a: int
    nand_1: int
    nand_2: int
    output: int


def _build() -> tuple[Circuit, _Ids]:
    """Construit un circuit avec une entrée, deux NAND et une sortie, sans câble."""
    circuit = Circuit()
    ids = _Ids(
        input_a=circuit.add_node(NodeKind.INPUT),
        nand_1=circuit.add_node(NodeKind.NAND),
        nand_2=circuit.add_node(NodeKind.NAND),
        output=circuit.add_node(NodeKind.OUTPUT),
    )
    return circuit, ids


def _snapshot(circuit: Circuit) -> tuple[tuple[Node, ...], tuple[Wire, ...]]:
    """Photographie les nœuds et les câbles, pour prouver que rien n'a changé."""
    return circuit.nodes(), circuit.wires()


# --- Nœuds et identifiants ---------------------------------------------------


def test_node_ids_are_unique() -> None:
    # Règle vérifiée : prompt phase 1, section A (identifiant entier unique).
    circuit = Circuit()
    ids = [circuit.add_node(NodeKind.NAND) for _ in range(5)]
    assert len(set(ids)) == len(ids)


def test_node_id_is_never_reused_after_removal() -> None:
    # Règle vérifiée : prompt phase 1, section A (identifiant jamais réutilisé).
    circuit = Circuit()
    seen = [circuit.add_node(NodeKind.NAND) for _ in range(3)]
    circuit.remove_node(seen[-1])  # on supprime le dernier créé...
    seen.append(circuit.add_node(NodeKind.NAND))
    circuit.remove_node(seen[1])  # ...puis un nœud du milieu
    seen.append(circuit.add_node(NodeKind.NAND))
    assert len(set(seen)) == len(seen)


@pytest.mark.parametrize(
    ("kind", "sinks", "sources"),
    [
        (NodeKind.INPUT, 0, 1),
        (NodeKind.OUTPUT, 1, 0),
        (NodeKind.NAND, 2, 1),
    ],
)
def test_pin_counts_per_kind(kind: NodeKind, sinks: int, sources: int) -> None:
    # Règle vérifiée : prompt phase 1, section A (puits et sources de chaque type).
    circuit = Circuit()
    node = circuit.node(circuit.add_node(kind))
    assert node.kind is kind
    assert (node.sink_count, node.source_count) == (sinks, sources)


def test_inputs_and_outputs_keep_creation_order() -> None:
    # Règle vérifiée : prompt phase 1, section A (ordre des entrées et sorties
    # = ordre de création), y compris après une suppression.
    circuit = Circuit()
    in_1 = circuit.add_node(NodeKind.INPUT)
    out_1 = circuit.add_node(NodeKind.OUTPUT)
    in_2 = circuit.add_node(NodeKind.INPUT)
    out_2 = circuit.add_node(NodeKind.OUTPUT)
    assert circuit.inputs() == (in_1, in_2)
    assert circuit.outputs() == (out_1, out_2)

    circuit.remove_node(in_1)
    in_3 = circuit.add_node(NodeKind.INPUT)
    assert circuit.inputs() == (in_2, in_3)
    assert circuit.outputs() == (out_1, out_2)


def test_nand_count() -> None:
    # Règle vérifiée : prompt phase 1, section B (T_max = nombre de NAND).
    circuit, ids = _build()
    assert circuit.nand_count() == 2
    circuit.remove_node(ids.nand_1)
    assert circuit.nand_count() == 1


def test_unknown_node_lookup_is_refused() -> None:
    # Règle vérifiée : prompt phase 1, section A (nœud inexistant refusé).
    circuit, _ = _build()
    with pytest.raises(UnknownNodeError):
        circuit.node(UNKNOWN_NODE_ID)


# --- Câblage accepté ---------------------------------------------------------


def test_connect_creates_a_wire() -> None:
    # Règle vérifiée : cahier, règle de câblage n°1 (source vers puits).
    circuit, ids = _build()
    source, sink = Pin(ids.input_a, 0), Pin(ids.nand_1, 0)
    circuit.connect(source, sink)
    assert circuit.source_of(sink) == source
    assert circuit.wires() == (Wire(source=source, sink=sink),)


def test_unwired_sink_has_no_source() -> None:
    # Règle vérifiée : cahier, règle de câblage n°2 (un puits reçoit 0 ou 1 câble).
    circuit, ids = _build()
    assert circuit.source_of(Pin(ids.nand_1, 0)) is None


def test_fan_out_is_unlimited() -> None:
    # Règle vérifiée : cahier, règle de câblage n°3 (une source alimente
    # un nombre illimité de puits).
    circuit = Circuit()
    source = Pin(circuit.add_node(NodeKind.INPUT), 0)
    fan_out = 20
    for _ in range(fan_out):
        nand_id = circuit.add_node(NodeKind.NAND)
        circuit.connect(source, Pin(nand_id, 0))
        circuit.connect(source, Pin(nand_id, 1))
    assert len(circuit.wires()) == 2 * fan_out


def test_nand_can_feed_its_own_sinks() -> None:
    # Règle vérifiée : cahier, règle de câblage n°5 (boucle sur sa propre porte)
    # et NOT(A) = NAND(A, A) : deux puits d'une même NAND sur une même source.
    circuit = Circuit()
    nand_id = circuit.add_node(NodeKind.NAND)
    own_output = Pin(nand_id, 0)
    circuit.connect(own_output, Pin(nand_id, 0))
    circuit.connect(own_output, Pin(nand_id, 1))
    assert len(circuit.wires()) == 2


# --- Câblage refusé ----------------------------------------------------------


def _assert_refused(
    circuit: Circuit, source: Pin, sink: Pin, error: type[CircuitError]
) -> None:
    """Vérifie que ``connect`` lève ``error`` et que le circuit n'a pas bougé."""
    before = _snapshot(circuit)
    with pytest.raises(error):
        circuit.connect(source, sink)
    assert _snapshot(circuit) == before


def test_second_wire_on_same_sink_is_refused() -> None:
    # Règle vérifiée : cahier, règle de câblage n°2 (un seul câble par puits).
    circuit, ids = _build()
    sink = Pin(ids.nand_1, 0)
    circuit.connect(Pin(ids.input_a, 0), sink)
    _assert_refused(circuit, Pin(ids.nand_2, 0), sink, SinkAlreadyConnectedError)
    assert circuit.source_of(sink) == Pin(ids.input_a, 0)  # le 1er câble est resté


_PinPair = Callable[[_Ids], tuple[Pin, Pin]]  # (source, puits) à partir des ids


@pytest.mark.parametrize(
    "make_pins",
    [
        pytest.param(
            lambda i: (Pin(i.nand_1, 2), Pin(i.output, 0)), id="source-trop-grand"
        ),
        pytest.param(
            lambda i: (Pin(i.input_a, 0), Pin(i.nand_1, 2)), id="puits-trop-grand"
        ),
        pytest.param(
            lambda i: (Pin(i.input_a, -1), Pin(i.output, 0)), id="source-negatif"
        ),
        pytest.param(
            lambda i: (Pin(i.input_a, 0), Pin(i.output, -1)), id="puits-negatif"
        ),
        pytest.param(
            lambda i: (Pin(i.input_a, 0), Pin(i.output, 1)), id="sortie-puits-1"
        ),
    ],
)
def test_nonexistent_pin_index_is_refused(make_pins: _PinPair) -> None:
    # Règle vérifiée : prompt phase 1, section A (index de broche inexistant).
    circuit, ids = _build()
    source, sink = make_pins(ids)
    _assert_refused(circuit, source, sink, UnknownPinError)


@pytest.mark.parametrize(
    "make_pins",
    [
        pytest.param(
            lambda i: (Pin(UNKNOWN_NODE_ID, 0), Pin(i.output, 0)), id="source"
        ),
        pytest.param(
            lambda i: (Pin(i.input_a, 0), Pin(UNKNOWN_NODE_ID, 0)), id="puits"
        ),
    ],
)
def test_nonexistent_node_is_refused(make_pins: _PinPair) -> None:
    # Règle vérifiée : prompt phase 1, section A (nœud inexistant).
    circuit, ids = _build()
    source, sink = make_pins(ids)
    _assert_refused(circuit, source, sink, UnknownNodeError)


@pytest.mark.parametrize(
    "make_pins",
    [
        pytest.param(
            lambda i: (Pin(i.output, 0), Pin(i.nand_1, 0)), id="sortie-comme-source"
        ),
        pytest.param(
            lambda i: (Pin(i.nand_1, 0), Pin(i.input_a, 0)), id="entree-comme-puits"
        ),
        pytest.param(
            lambda i: (Pin(i.nand_1, 1), Pin(i.output, 0)), id="puits-nand-comme-source"
        ),
    ],
)
def test_pin_of_wrong_kind_is_refused(make_pins: _PinPair) -> None:
    # Règle vérifiée : cahier, règle de câblage n°1 (sortie vers sortie et entrée
    # vers entrée impossibles) ; prompt phase 1, section A (broche du mauvais genre).
    circuit, ids = _build()
    source, sink = make_pins(ids)
    _assert_refused(circuit, source, sink, WrongPinKindError)


def test_all_refusals_share_one_base_class() -> None:
    # Règle vérifiée : prompt phase 1, section A (« une exception dédiée »).
    for error in (
        UnknownNodeError,
        UnknownPinError,
        WrongPinKindError,
        SinkAlreadyConnectedError,
        SinkNotConnectedError,
    ):
        assert issubclass(error, CircuitError)


# --- Suppression -------------------------------------------------------------


def test_remove_node_removes_its_wires() -> None:
    # Règle vérifiée : prompt phase 1, section A (supprimer un nœud supprime
    # aussi ses câbles), côté puits comme côté source.
    circuit, ids = _build()
    circuit.connect(Pin(ids.input_a, 0), Pin(ids.nand_1, 0))  # entrée vers n1
    circuit.connect(Pin(ids.nand_1, 0), Pin(ids.nand_1, 1))  # n1 sur lui-même
    circuit.connect(Pin(ids.nand_1, 0), Pin(ids.output, 0))  # n1 vers la sortie
    circuit.connect(Pin(ids.input_a, 0), Pin(ids.nand_2, 0))  # entrée vers n2

    circuit.remove_node(ids.nand_1)

    assert circuit.wires() == (
        Wire(source=Pin(ids.input_a, 0), sink=Pin(ids.nand_2, 0)),
    )
    # Le puits de la sortie est de nouveau libre.
    assert circuit.source_of(Pin(ids.output, 0)) is None


def test_removing_a_source_node_frees_its_sinks() -> None:
    # Règle vérifiée : prompt phase 1, section A (suppression) et cahier,
    # règle n°2 : le puits libéré peut recevoir un nouveau câble.
    circuit, ids = _build()
    circuit.connect(Pin(ids.input_a, 0), Pin(ids.nand_1, 0))
    circuit.remove_node(ids.input_a)
    assert circuit.wires() == ()
    circuit.connect(Pin(ids.nand_2, 0), Pin(ids.nand_1, 0))  # ne doit pas lever
    assert circuit.source_of(Pin(ids.nand_1, 0)) == Pin(ids.nand_2, 0)


def test_removing_unknown_node_is_refused_and_changes_nothing() -> None:
    # Règle vérifiée : CLAUDE.md (une opération refusée laisse l'objet inchangé).
    circuit, ids = _build()
    circuit.connect(Pin(ids.input_a, 0), Pin(ids.nand_1, 0))
    before = _snapshot(circuit)
    with pytest.raises(UnknownNodeError):
        circuit.remove_node(UNKNOWN_NODE_ID)
    assert _snapshot(circuit) == before


# --- Déconnexion -------------------------------------------------------------


def test_disconnect_frees_the_sink() -> None:
    # Règle vérifiée : prompt phase 1, section A (opération déconnecter(puits)).
    circuit, ids = _build()
    sink = Pin(ids.nand_1, 0)
    circuit.connect(Pin(ids.input_a, 0), sink)
    circuit.disconnect(sink)
    assert circuit.source_of(sink) is None
    assert circuit.wires() == ()
    circuit.connect(Pin(ids.nand_2, 0), sink)  # le puits accepte de nouveau un câble


@pytest.mark.parametrize(
    ("make_sink", "error"),
    [
        pytest.param(lambda i: Pin(UNKNOWN_NODE_ID, 0), UnknownNodeError, id="noeud"),
        pytest.param(lambda i: Pin(i.nand_1, 2), UnknownPinError, id="index"),
        pytest.param(lambda i: Pin(i.input_a, 0), WrongPinKindError, id="genre"),
        pytest.param(
            lambda i: Pin(i.nand_2, 0), SinkNotConnectedError, id="sans-cable"
        ),
    ],
)
def test_disconnect_refusals_change_nothing(
    make_sink: Callable[[_Ids], Pin], error: type[CircuitError]
) -> None:
    # Règle vérifiée : CLAUDE.md (une opération refusée laisse l'objet inchangé) ;
    # ambiguïté 2 du plan validée par Téo (disconnect lève une exception).
    circuit, ids = _build()
    circuit.connect(Pin(ids.input_a, 0), Pin(ids.nand_1, 0))
    before = _snapshot(circuit)
    with pytest.raises(error):
        circuit.disconnect(make_sink(ids))
    assert _snapshot(circuit) == before
