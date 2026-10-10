"""Tests des fichiers d'exemples de la phase 1 écrits pour l'affichage Unity."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from logicai.examples import main, write_phase1_examples
from logicai.serialization import circuit_from_json

_GATES: dict[str, Callable[[int, int], int]] = {
    "nand": lambda a, b: 1 - (a & b),
    "and": lambda a, b: a & b,
    "or": lambda a, b: a | b,
    "xor": lambda a, b: a ^ b,
}

_EXPECTED_STEMS = sorted(
    ["not_A0", "not_A1"]
    + [f"{gate}_A{a}_B{b}" for gate in _GATES for a in (0, 1) for b in (0, 1)]
    + ["constante_1"]
    + [f"not_reboucle_top{t}" for t in range(4)]
    + [f"bascule_sr_pas{n}" for n in range(1, 5)]
    + [f"bascule_sr_metastable_top{t}" for t in range(4)]
)


@pytest.fixture(scope="module")
def examples(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """Écrit les exemples une fois, puis les relit comme le fera Unity."""
    directory = tmp_path_factory.mktemp("circuits")
    write_phase1_examples(directory)
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    }


def _output_values(data: dict[str, Any]) -> list[int]:
    """Valeurs des nœuds SORTIE, dans l'ordre : ce que Unity colorera."""
    return [
        value
        for node, value in zip(data["noeuds"], data["etat"]["noeuds"], strict=True)
        if node["type"] == "SORTIE"
    ]


def _gate_values(data: dict[str, Any]) -> list[int]:
    """Valeurs des NAND (ni entrée ni sortie), dans l'ordre de création."""
    return [
        value
        for node, value in zip(data["noeuds"], data["etat"]["noeuds"], strict=True)
        if node["type"] == "NAND"
    ]


# --- Les fichiers --------------------------------------------------------------------


def test_all_the_phase_1_examples_are_written(
    examples: dict[str, dict[str, Any]],
) -> None:
    # Règle vérifiée : cahier, plan de développement, phase 3 (les circuits de la phase
    # 1 s'affichent) : NOT, NAND, AND, OR, XOR pour chaque combinaison, constante 1, NOT
    # rebouclé, bascule SR.
    assert sorted(examples) == _EXPECTED_STEMS
    assert len(examples) == 31


def test_every_file_is_a_valid_circuit_with_positions_and_a_state(
    examples: dict[str, dict[str, Any]],
) -> None:
    # Règle vérifiée : cahier, « Exemple de circuit en JSON » (nom, noeuds avec x et y,
    # cables) et message « etat » : tout ce dont Unity a besoin, sans rien calculer.
    for stem, data in examples.items():
        name, _ = circuit_from_json(json.dumps(data))
        assert name == stem
        assert all(
            isinstance(n["x"], int) and isinstance(n["y"], int) for n in data["noeuds"]
        )
        state = data["etat"]
        assert len(state["noeuds"]) == len(data["noeuds"])
        assert len(state["cables"]) == len(data["cables"])
        assert set(state["noeuds"] + state["cables"]) <= {0, 1}


# --- Les valeurs ----------------------------------------------------------------------


@pytest.mark.parametrize("gate", _GATES)
def test_gate_files_show_the_right_output(
    examples: dict[str, dict[str, Any]], gate: str
) -> None:
    # Règle vérifiée : prompt phase 1, tableau E (valeurs attendues de NAND, AND, OR,
    # XOR) : la valeur du nœud SORTIE de chaque fichier est celle de la porte.
    for a in (0, 1):
        for b in (0, 1):
            data = examples[f"{gate}_A{a}_B{b}"]
            assert _output_values(data) == [_GATES[gate](a, b)]
            assert data["etat"]["stable"] is True


def test_not_and_constant_files(examples: dict[str, dict[str, Any]]) -> None:
    # Règle vérifiée : prompt phase 1, tableau E (NOT, constante 1).
    assert _output_values(examples["not_A0"]) == [1]
    assert _output_values(examples["not_A1"]) == [0]
    assert _output_values(examples["constante_1"]) == [1]


def test_input_values_are_shown(examples: dict[str, dict[str, Any]]) -> None:
    # Règle vérifiée : cahier, message « etat » : les entrées colorées valent ce qui est
    # appliqué (XOR avec A = 1 et B = 0).
    data = examples["xor_A1_B0"]
    inputs = [
        value
        for node, value in zip(data["noeuds"], data["etat"]["noeuds"], strict=True)
        if node["type"] == "ENTREE"
    ]
    assert inputs == [1, 0]


def test_looped_not_files_oscillate(examples: dict[str, dict[str, Any]]) -> None:
    # Règle vérifiée : cahier, « Les trois cas détectés » (instable) : la NAND vaut
    # 0, 1, 0, 1 aux tops 0 à 3 et le circuit n'est jamais stable.
    for top, value in enumerate((0, 1, 0, 1)):
        data = examples[f"not_reboucle_top{top}"]
        assert _gate_values(data) == [value]
        assert data["etat"]["top"] == top
        assert data["etat"]["stable"] is False


def test_sr_latch_files_show_the_memory(examples: dict[str, dict[str, Any]]) -> None:
    # Règle vérifiée : prompt phase 1, tableau E (bascule SR : Q = 1, 1, 0, 0, chaque
    # pas stable, en 3, 1, 3, 1 tops).
    steps = [examples[f"bascule_sr_pas{n}"] for n in range(1, 5)]
    assert [_output_values(data)[0] for data in steps] == [1, 1, 0, 0]
    assert [data["etat"]["top"] for data in steps] == [3, 1, 3, 1]
    assert all(data["etat"]["stable"] for data in steps)


def test_metastable_latch_files_oscillate(examples: dict[str, dict[str, Any]]) -> None:
    # Règle vérifiée : cahier, « Piège à connaître » (métastabilité) : (Q, Q̄) vaut
    # (0,0), (1,1), (0,0), (1,1) aux tops 0 à 3.
    for top, value in enumerate((0, 1, 0, 1)):
        data = examples[f"bascule_sr_metastable_top{top}"]
        assert _gate_values(data) == [value, value]
        assert data["etat"]["stable"] is False


# --- Écriture -------------------------------------------------------------------------


def test_writing_twice_gives_identical_files(tmp_path: Path) -> None:
    # Règle vérifiée : décision du plan (résultat déterministe).
    first = write_phase1_examples(tmp_path / "a")
    second = write_phase1_examples(tmp_path / "b")
    assert [p.name for p in first] == [p.name for p in second]
    for one, other in zip(first, second, strict=True):
        assert one.read_bytes() == other.read_bytes()


def test_existing_files_are_replaced_and_paths_are_sorted(tmp_path: Path) -> None:
    # Règle vérifiée : CLAUDE.md (comportement documenté et sans surprise).
    (tmp_path / "not_A0.json").write_text("vieux contenu", encoding="utf-8")
    paths = write_phase1_examples(tmp_path)
    assert list(paths) == sorted(paths)
    assert "vieux contenu" not in (tmp_path / "not_A0.json").read_text(encoding="utf-8")


def test_command_line_entry_point_writes_the_files(tmp_path: Path) -> None:
    # Règle vérifiée : décision du plan (commande qui régénère le dossier circuits/).
    main([str(tmp_path / "nouveau" / "circuits")])
    assert len(list((tmp_path / "nouveau" / "circuits").glob("*.json"))) == 31
