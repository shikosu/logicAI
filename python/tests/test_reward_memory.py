"""Tests du bonus mémoire dans la récompense.

Cahier, « La formule » : ``R = R_nouveauté + R_record + R_mémoire + R_réutilisation
- k · N_NAND - P_filtres``. Mémoire : « le circuit a un comportement séquentiel », ordre
de grandeur « grand ». Interprétation (à confirmer par Téo) : comme la réutilisation, le
bonus s'ajoute à une **nouveauté** seulement, pas à un record.
"""

import pytest

from builders import add_not, not_circuit, sr_latch, wire
from logicai.circuit import Circuit, NodeKind
from logicai.errors import InvalidRewardSettingsError
from logicai.filters import Rejection
from logicai.library import Library
from logicai.reward import (
    DEFAULT_MEMORY_BONUS,
    DEFAULT_RECORD_REWARD,
    DEFAULT_REUSE_BONUS,
    NO_REWARD,
    RewardSettings,
    RewardTracker,
    TrialKind,
)

DEFAULT = RewardSettings()
CUSTOM = RewardSettings(novelty=50.0, record=10.0, reuse=3.0, nand_cost=2.0, memory=7.0)


def _tracker(settings: RewardSettings = DEFAULT) -> RewardTracker:
    return RewardTracker(Library(), settings)


def _latch_with_unused_input() -> Circuit:
    circuit = sr_latch()
    circuit.add_node(NodeKind.INPUT)
    return circuit


def _bloated_latch() -> Circuit:
    """Bascule SR dont la sortie Q passe par deux NOT inutiles (4 NAND)."""
    circuit = Circuit()
    s_bar = circuit.add_node(NodeKind.INPUT)
    r_bar = circuit.add_node(NodeKind.INPUT)
    q = circuit.add_node(NodeKind.NAND)
    q_bar = circuit.add_node(NodeKind.NAND)
    wire(circuit, s_bar, q, 0)
    wire(circuit, q_bar, q, 1)
    wire(circuit, r_bar, q_bar, 0)
    wire(circuit, q, q_bar, 1)
    wire(
        circuit,
        add_not(circuit, add_not(circuit, q)),
        circuit.add_node(NodeKind.OUTPUT),
    )
    wire(circuit, q_bar, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _oscillator_with_an_input() -> Circuit:
    circuit = Circuit()
    circuit.add_node(NodeKind.INPUT)
    nand = circuit.add_node(NodeKind.NAND)
    wire(circuit, nand, nand, 0)
    wire(circuit, nand, nand, 1)
    wire(circuit, nand, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _not_with_an_irrelevant_loop() -> Circuit:
    """Un NOT dont la NAND est aussi dans une boucle qui ne change rien (stable)."""
    circuit = Circuit()
    data = circuit.add_node(NodeKind.INPUT)
    not_data = circuit.add_node(NodeKind.NAND)
    constant_one = circuit.add_node(NodeKind.NAND)
    wire(circuit, data, not_data, 0)
    wire(circuit, constant_one, not_data, 1)
    wire(circuit, not_data, constant_one, 0)
    wire(circuit, not_data, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def test_default_memory_bonus_is_large() -> None:
    # Cahier, tableau de la formule : mémoire « grand » (au-dessus de record et
    # réutilisation).
    assert DEFAULT_MEMORY_BONUS > DEFAULT_RECORD_REWARD > DEFAULT_REUSE_BONUS > 0


def test_negative_memory_weight_is_refused() -> None:
    with pytest.raises(InvalidRewardSettingsError, match="mémoire"):
        RewardSettings(memory=-1.0)


@pytest.mark.parametrize(
    ("settings", "expected"),
    [(DEFAULT, 100.0 + 100.0 - 1.0 * 2), (CUSTOM, 50.0 + 7.0 - 2.0 * 2)],
    ids=["défaut", "réglages choisis"],
)
def test_a_new_latch_earns_novelty_plus_memory_minus_size(
    settings: RewardSettings, expected: float
) -> None:
    result = _tracker(settings).evaluate(sr_latch())
    assert (result.kind, result.name, result.memory) == (TrialKind.NEW, "C-001", True)
    assert result.reward == expected


def test_a_new_circuit_without_memory_gets_no_bonus() -> None:
    result = _tracker().evaluate(not_circuit())
    assert result.kind is TrialKind.NEW
    assert result.memory is False
    assert result.reward == 100.0 - 1.0


def test_a_loop_that_remembers_nothing_gets_no_bonus() -> None:
    # La NAND de la boucle alimente le NOT : le nettoyage la garde, le coût est de 2.
    result = _tracker().evaluate(_not_with_an_irrelevant_loop())
    assert (result.kind, result.name, result.memory) == (TrialKind.NEW, "NOT", False)
    assert result.reward == 100.0 - 1.0 * 2


def test_a_zero_memory_weight_removes_the_bonus() -> None:
    result = _tracker(RewardSettings(memory=0.0)).evaluate(sr_latch())
    assert result.reward == 100.0 - 1.0 * 2


def test_a_record_on_a_memory_circuit_gets_no_memory_bonus() -> None:
    # Interprétation : le bonus s'ajoute à une nouveauté, pas à un record.
    tracker = _tracker()
    assert tracker.evaluate(_bloated_latch()).kind is TrialKind.NEW
    result = tracker.evaluate(sr_latch())
    assert (result.kind, result.name, result.memory) == (
        TrialKind.RECORD,
        "C-001",
        True,
    )
    assert result.reward == 30.0 - 1.0 * 2


def test_a_known_memory_circuit_earns_nothing() -> None:
    tracker = _tracker()
    tracker.evaluate(sr_latch())
    result = tracker.evaluate(sr_latch())
    assert (result.kind, result.reward, result.memory) == (
        TrialKind.NOTHING,
        NO_REWARD,
        True,
    )


def test_filters_still_apply_to_memory_circuits() -> None:
    # Cahier, « Les filtres anti-triche » : un circuit à mémoire inutile est refusé.
    tracker = _tracker()
    unused = tracker.evaluate(_latch_with_unused_input())
    assert unused.kind is TrialKind.REJECTED
    assert unused.rejections == (Rejection.UNUSED_INPUT,)
    unstable = tracker.evaluate(_oscillator_with_an_input())
    assert unstable.kind is TrialKind.REJECTED
    assert unstable.rejections == (Rejection.UNSTABLE,)
    assert (
        tracker.evaluate(sr_latch()).kind is TrialKind.NEW
    )  # rien n'a été gardé avant
