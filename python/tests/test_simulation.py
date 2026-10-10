"""Tests de la simulation par tops : retard, entrées, stabilité, bascule SR."""

import pytest

from logicai.circuit import Circuit, NodeKind, Pin
from logicai.errors import SimulationError
from logicai.simulation import SettleResult, Status, max_ticks, settle, tick

# Masque d'une seule combinaison d'entrées : les signaux valent 0 ou 1.
ONE_COMBINATION = 1


def _wire(circuit: Circuit, source_id: int, sink_id: int, sink_index: int = 0) -> None:
    """Relie la source 0 d'un nœud au puits ``sink_index`` d'un autre."""
    circuit.connect(Pin(source_id, 0), Pin(sink_id, sink_index))


def _add_not(circuit: Circuit, source_id: int) -> int:
    """Ajoute une NAND dont les deux puits sont alimentés par ``source_id`` (un NOT)."""
    nand_id = circuit.add_node(NodeKind.NAND)
    _wire(circuit, source_id, nand_id, 0)
    _wire(circuit, source_id, nand_id, 1)
    return nand_id


def _chain_of_three_nots() -> Circuit:
    """Une entrée A, trois NOT en chaîne (n1, n2, n3), et une sortie reliée à n3."""
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    n1 = _add_not(circuit, input_a)
    n2 = _add_not(circuit, n1)
    n3 = _add_not(circuit, n2)
    _wire(circuit, n3, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _looped_not() -> Circuit:
    """Une NAND dont les deux puits sont sur sa propre sortie, lue par une OUTPUT."""
    circuit = Circuit()
    nand_id = circuit.add_node(NodeKind.NAND)
    _wire(circuit, nand_id, nand_id, 0)
    _wire(circuit, nand_id, nand_id, 1)
    _wire(circuit, nand_id, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _sr_latch() -> Circuit:
    """Bascule SR en NAND : Q = NAND(S̄, Q̄) et Q̄ = NAND(R̄, Q).

    Entrées dans l'ordre (S̄, R̄) ; sorties dans l'ordre (Q, Q̄) ;
    l'état du moteur est donc (Q, Q̄).
    """
    circuit = Circuit()
    s_bar = circuit.add_node(NodeKind.INPUT)
    r_bar = circuit.add_node(NodeKind.INPUT)
    nand_q = circuit.add_node(NodeKind.NAND)
    nand_q_bar = circuit.add_node(NodeKind.NAND)
    _wire(circuit, s_bar, nand_q, 0)
    _wire(circuit, nand_q_bar, nand_q, 1)
    _wire(circuit, r_bar, nand_q_bar, 0)
    _wire(circuit, nand_q, nand_q_bar, 1)
    _wire(circuit, nand_q, circuit.add_node(NodeKind.OUTPUT))
    _wire(circuit, nand_q_bar, circuit.add_node(NodeKind.OUTPUT))
    return circuit


# --- Les tops -----------------------------------------------------------------


def test_default_state_is_all_zero() -> None:
    # Règle vérifiée : prompt phase 1, section B (au départ, toutes les NAND valent 0).
    # NAND rebouclée : si elle part de 0, son premier top donne NAND(0, 0) = 1.
    assert tick(_looped_not(), (), ONE_COMBINATION) == (1,)


def test_nand_reads_other_nands_one_tick_late() -> None:
    # Règle vérifiée : cahier, « La simulation par tops » (retard de 1 top par NAND).
    # Chaîne A -> n1 -> n2 -> n3 avec A = 0, calculée à la main top par top :
    #   top 1 : (1, 1, 1)   top 2 : (1, 0, 0)   top 3 : (1, 0, 1)   top 4 : (1, 0, 1)
    circuit = _chain_of_three_nots()
    state = tick(circuit, (0,), ONE_COMBINATION)
    assert state == (1, 1, 1)
    state = tick(circuit, (0,), ONE_COMBINATION, state)
    assert state == (1, 0, 0)
    state = tick(circuit, (0,), ONE_COMBINATION, state)
    assert state == (1, 0, 1)
    state = tick(circuit, (0,), ONE_COMBINATION, state)
    assert state == (1, 0, 1)


def test_chain_settles_after_confirmation_tick() -> None:
    # Règle vérifiée : prompt phase 1, section B (figé après d = 3 tops, le top 4
    # le confirme : c'est exactement T_max + 1).
    result = settle(_chain_of_three_nots(), (0,), ONE_COMBINATION)
    assert result == SettleResult(Status.STABLE, (1, 0, 1), (1,), 4)


def test_input_is_applied_without_delay() -> None:
    # Règle vérifiée : prompt phase 1, section B (INPUT : valeur actuelle, sans retard).
    # NAND(1, 1) = 0 dès le top 1. Avec un retard, la NAND lirait 0 et vaudrait 1.
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    input_b = circuit.add_node(NodeKind.INPUT)
    nand_id = circuit.add_node(NodeKind.NAND)
    _wire(circuit, input_a, nand_id, 0)
    _wire(circuit, input_b, nand_id, 1)
    assert tick(circuit, (1, 1), ONE_COMBINATION) == (0,)


@pytest.mark.parametrize("wired_sink", [0, 1])
def test_unwired_sink_is_zero(wired_sink: int) -> None:
    # Règle vérifiée : cahier, règle de câblage n°4 (un puits sans câble vaut 0).
    # NAND(1, 0) = 1 ; si le puits libre valait 1, on aurait NAND(1, 1) = 0.
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    nand_id = circuit.add_node(NodeKind.NAND)
    _wire(circuit, input_a, nand_id, wired_sink)
    assert tick(circuit, (1,), ONE_COMBINATION) == (1,)


def test_nand_without_any_wire_is_constant_one() -> None:
    # Règle vérifiée : cahier, règle de câblage n°4 (NAND(0, 0) = 1).
    circuit = Circuit()
    circuit.add_node(NodeKind.NAND)
    assert settle(circuit, (), ONE_COMBINATION) == SettleResult(
        Status.STABLE, (1,), (), 2
    )


def test_all_nands_update_at_the_same_time() -> None:
    # Règle vérifiée : prompt phase 1, section B (toutes les NAND mises à jour en
    # même temps). Bascule SR avec (S̄, R̄) = (1, 1), départ (0, 0) : les deux NAND
    # lisent l'ancien état et valent 1. Une mise à jour l'une après l'autre
    # donnerait (1, 0).
    assert tick(_sr_latch(), (1, 1), ONE_COMBINATION) == (1, 1)


def test_nand_formula_uses_the_mask() -> None:
    # Règle vérifiée : prompt phase 1, section C (NAND = ~(a & b) & masque) ;
    # exemple du cahier : A = 0b1010, B = 0b1100, NAND = 0b0111.
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    input_b = circuit.add_node(NodeKind.INPUT)
    nand_id = circuit.add_node(NodeKind.NAND)
    _wire(circuit, input_a, nand_id, 0)
    _wire(circuit, input_b, nand_id, 1)
    assert tick(circuit, (0b1010, 0b1100), 0b1111) == (0b0111,)


# --- Les sorties ---------------------------------------------------------------


def test_unwired_output_is_zero() -> None:
    # Règle vérifiée : prompt phase 1, section B (OUTPUT non reliée : 0).
    circuit = Circuit()
    circuit.add_node(NodeKind.OUTPUT)
    assert settle(circuit, (), ONE_COMBINATION) == SettleResult(
        Status.STABLE, (), (0,), 1
    )


@pytest.mark.parametrize("value", [0, 1])
def test_output_wired_to_input_follows_it_without_delay(value: int) -> None:
    # Règle vérifiée : prompt phase 1, section B (OUTPUT : valeur de sa source,
    # sans retard). Sans aucune NAND, le circuit est stable dès le premier top.
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    _wire(circuit, input_a, circuit.add_node(NodeKind.OUTPUT))
    assert settle(circuit, (value,), ONE_COMBINATION) == SettleResult(
        Status.STABLE, (), (value,), 1
    )


# --- Stabilité -----------------------------------------------------------------


def test_max_ticks_is_nand_count_plus_one() -> None:
    # Règle vérifiée : prompt phase 1, section B (au plus T_max + 1 tops).
    assert max_ticks(Circuit()) == 1
    assert max_ticks(_chain_of_three_nots()) == 4
    assert max_ticks(_sr_latch()) == 3


def test_stable_as_soon_as_a_tick_changes_nothing() -> None:
    # Règle vérifiée : prompt phase 1, section B (STABLE dès qu'un top ne change
    # aucune valeur). NOT avec A = 1 : NAND(1, 1) = 0, l'état de départ ne bouge pas.
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    _add_not(circuit, input_a)
    assert settle(circuit, (1,), ONE_COMBINATION) == SettleResult(
        Status.STABLE, (0,), (), 1
    )


def test_stable_on_the_last_allowed_tick() -> None:
    # Règle vérifiée : prompt phase 1, section B. NOT avec A = 0 : le top 1 change
    # (0 -> 1), le top 2 confirme. Le top 2 est le dernier autorisé (T_max + 1 = 2).
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    _add_not(circuit, input_a)
    result = settle(circuit, (0,), ONE_COMBINATION)
    assert result == SettleResult(Status.STABLE, (1,), (), 2)
    assert result.ticks == max_ticks(circuit)


def test_looped_not_is_unstable() -> None:
    # Règle vérifiée : prompt phase 1, tableau E (NOT rebouclé : UNSTABLE).
    # Départ 0 : top 1 -> 1, top 2 -> 0, ça change encore au top T_max + 1 = 2.
    # Les valeurs rendues sont celles du dernier top calculé (ambiguïté 4 du plan),
    # et la sortie les lit sans retard.
    assert settle(_looped_not(), (), ONE_COMBINATION) == SettleResult(
        Status.UNSTABLE, (0,), (0,), 2
    )


def test_sr_latch_step_by_step() -> None:
    # Règle vérifiée : prompt phase 1, tableau E (bascule SR, séquence
    # (S̄, R̄) = (0,1), (1,1), (1,0), (1,1) : Q = 1, 1, 0, 0, chaque pas stable).
    # L'état est repris d'un pas au suivant. Tops calculés à la main : 3, 1, 3, 1.
    circuit = _sr_latch()
    step_1 = settle(circuit, (0, 1), ONE_COMBINATION)
    assert step_1 == SettleResult(Status.STABLE, (1, 0), (1, 0), 3)
    step_2 = settle(circuit, (1, 1), ONE_COMBINATION, step_1.state)
    assert step_2 == SettleResult(Status.STABLE, (1, 0), (1, 0), 1)
    step_3 = settle(circuit, (1, 0), ONE_COMBINATION, step_2.state)
    assert step_3 == SettleResult(Status.STABLE, (0, 1), (0, 1), 3)
    step_4 = settle(circuit, (1, 1), ONE_COMBINATION, step_3.state)
    assert step_4 == SettleResult(Status.STABLE, (0, 1), (0, 1), 1)


def test_sr_latch_metastability_is_unstable() -> None:
    # Règle vérifiée : prompt phase 1, tableau E (métastabilité) ; cahier,
    # « Piège à connaître ». Départ (0, 0) et (S̄, R̄) = (1, 1) :
    # top 1 -> (1, 1), top 2 -> (0, 0), top 3 -> (1, 1) : ça change encore.
    assert settle(_sr_latch(), (1, 1), ONE_COMBINATION) == SettleResult(
        Status.UNSTABLE, (1, 1), (1, 1), 3
    )


# --- Données invalides ---------------------------------------------------------


@pytest.mark.parametrize("input_values", [(), (0, 0)])
def test_wrong_number_of_input_values_is_refused(input_values: tuple[int, ...]) -> None:
    # Règle vérifiée : ambiguïté 8 du plan (entrée de simulation invalide).
    with pytest.raises(SimulationError):
        settle(_chain_of_three_nots(), input_values, ONE_COMBINATION)


@pytest.mark.parametrize("value", [2, -1])
def test_input_value_outside_the_mask_is_refused(value: int) -> None:
    # Règle vérifiée : ambiguïté 8 du plan (valeur autre que 0 ou 1, masque de 1 bit).
    with pytest.raises(SimulationError):
        settle(_chain_of_three_nots(), (value,), ONE_COMBINATION)


@pytest.mark.parametrize("mask", [0, -1, 2, 5, 6])
def test_mask_that_is_not_all_ones_is_refused(mask: int) -> None:
    # Règle vérifiée : prompt phase 1, section C (masque = (1 << 2**n) - 1, soit
    # uniquement des bits à 1).
    with pytest.raises(SimulationError):
        settle(_chain_of_three_nots(), (0,), mask)


@pytest.mark.parametrize("state", [(), (0, 0), (0, 0, 0, 0), (0, 0, 2)])
def test_invalid_state_is_refused(state: tuple[int, ...]) -> None:
    # Règle vérifiée : ambiguïté 8 du plan (état de mauvaise longueur ou hors masque).
    with pytest.raises(SimulationError):
        settle(_chain_of_three_nots(), (0,), ONE_COMBINATION, state)


def test_engine_refuses_a_source_it_cannot_simulate() -> None:
    # Règle vérifiée : prompt phase 1, intro (le code doit accepter de nouveaux types
    # de nœuds sans réécriture : un type inconnu du moteur est refusé proprement).
    # On pose ici un câble que ``connect`` interdit (une OUTPUT n'a pas de source),
    # en écrivant directement dans le dictionnaire privé, pour atteindre ce refus.
    circuit = Circuit()
    nand_id = circuit.add_node(NodeKind.NAND)
    output_id = circuit.add_node(NodeKind.OUTPUT)
    circuit._wires[Pin(nand_id, 0)] = Pin(output_id, 0)
    with pytest.raises(SimulationError):
        settle(circuit, (), ONE_COMBINATION)
