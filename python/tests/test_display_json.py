"""Tests du JSON d'affichage : positions x et y, et valeurs 0/1 dans « etat »."""

import json
from pathlib import Path
from typing import Any

import pytest

from builders import not_circuit, sr_latch, wire, xor_circuit
from logicai.circuit import Circuit, NodeKind
from logicai.errors import SnapshotError
from logicai.layout import compute_layout
from logicai.library import Library
from logicai.serialization import circuit_from_json, circuit_to_dict, circuit_to_json
from logicai.snapshot import settled_snapshot


def _snapshot_of_xor() -> tuple[Circuit, dict[str, Any]]:
    circuit = xor_circuit()
    return circuit, circuit_to_dict(
        "XOR_A1_B0", circuit, settled_snapshot(circuit, (1, 0))
    )


# --- Positions ------------------------------------------------------------------------


def test_every_node_carries_the_position_computed_by_python() -> None:
    # Règle vérifiée : réponse de Téo (Python calcule, Unity dessine) : chaque nœud
    # écrit
    # a les x et y de ``compute_layout``.
    circuit = xor_circuit()
    layout = compute_layout(circuit)
    for node_dict in circuit_to_dict("XOR", circuit)["noeuds"]:
        position = layout[node_dict["id"]]
        assert (node_dict["x"], node_dict["y"]) == (position.x, position.y)


def test_positions_are_written_for_every_kind_of_node() -> None:
    # Règle vérifiée : réponse de Téo (Python calcule les positions) : entrées, NAND,
    # sorties et composants.
    circuit = Circuit()
    a = circuit.add_node(NodeKind.INPUT)
    component = circuit.add_component_node("XOR", 2, 1)
    wire(circuit, a, component, 0)
    wire(circuit, a, component, 1)
    wire(circuit, component, circuit.add_node(NodeKind.OUTPUT))
    for node_dict in circuit_to_dict("TOP", circuit)["noeuds"]:
        assert isinstance(node_dict["x"], int)
        assert isinstance(node_dict["y"], int)


def test_library_files_have_positions_and_no_state(tmp_path: Path) -> None:
    # Règle vérifiée : réponse de Téo (Python calcule les positions) : les fichiers de
    # la
    # bibliothèque sont directement affichables ; ils n'ont pas de photo des valeurs.
    library = Library()
    library.register(xor_circuit())
    library.save(tmp_path)
    written = json.loads((tmp_path / "XOR.json").read_text(encoding="utf-8"))
    assert all("x" in node and "y" in node for node in written["noeuds"])
    assert "etat" not in written


# --- L'état ---------------------------------------------------------------------------


def test_without_a_snapshot_there_is_no_state() -> None:
    # Règle vérifiée : décision du plan (la clé etat est facultative).
    assert "etat" not in circuit_to_dict("NOT", not_circuit())


def test_state_holds_the_top_the_stability_and_the_values() -> None:
    # Règle vérifiée : cahier, message « etat » (les valeurs 0/1 de chaque fil à un top
    # donné) ; format du plan. XOR avec A = 1 et B = 0 : valeurs calculées à la main
    # dans
    # test_snapshot.
    _, data = _snapshot_of_xor()
    assert data["etat"] == {
        "top": 4,
        "stable": True,
        "noeuds": [1, 0, 1, 0, 1, 1, 1],
        "cables": [1, 0, 1, 1, 0, 1, 0, 1, 1],
    }


def test_state_lists_follow_the_order_of_the_nodes_and_the_wires() -> None:
    # Règle vérifiée : décision du plan (les listes suivent l'ordre de noeuds et de
    # cables du fichier, que Unity relit sans rien calculer).
    _, data = _snapshot_of_xor()
    state = data["etat"]
    assert len(state["noeuds"]) == len(data["noeuds"])
    assert len(state["cables"]) == len(data["cables"])
    # La sortie est le dernier nœud et lit le dernier câble (n4 > sortie).
    assert state["noeuds"][-1] == state["cables"][-1]


def test_oscillating_circuit_is_flagged_unstable() -> None:
    # Règle vérifiée : cahier, « Les trois cas détectés » (instable) : Unity peut le
    # dire.
    circuit = sr_latch()
    data = circuit_to_dict("META", circuit, settled_snapshot(circuit, (1, 1)))
    assert data["etat"]["stable"] is False


def test_snapshot_of_another_circuit_is_refused() -> None:
    # Règle vérifiée : CLAUDE.md (refus clair d'une donnée incohérente).
    other = settled_snapshot(not_circuit(), (0,))
    with pytest.raises(SnapshotError):
        circuit_to_dict("XOR", xor_circuit(), other)


# --- Lecture --------------------------------------------------------------------------


def test_reading_ignores_the_positions_and_the_state() -> None:
    # Règle vérifiée : décision du plan (x, y et etat sont ignorés à la lecture : ils
    # sont
    # pour l'affichage, ce n'est pas une partie du circuit).
    circuit = xor_circuit()
    text = circuit_to_json("XOR", circuit, settled_snapshot(circuit, (1, 0)))
    name, restored = circuit_from_json(text)
    assert name == "XOR"
    assert (restored.nodes(), restored.wires()) == (circuit.nodes(), circuit.wires())


def test_json_text_with_a_state_is_valid_json() -> None:
    # Règle vérifiée : cahier, « Enregistrement ... sous forme de fichier JSON ».
    circuit = xor_circuit()
    snapshot = settled_snapshot(circuit, (0, 1))
    text = circuit_to_json("XOR", circuit, snapshot)
    assert text.endswith("\n")
    assert json.loads(text) == circuit_to_dict("XOR", circuit, snapshot)
