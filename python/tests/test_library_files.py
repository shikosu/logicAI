"""Tests de la sauvegarde et du rechargement d'une bibliothèque (fichiers JSON)."""

import json
from pathlib import Path

import pytest

from builders import (
    add_nand,
    add_not,
    bloated,
    build_and,
    build_xor,
    gate,
    not_circuit,
    wire,
    xor_circuit,
)
from logicai.behavior import TruthTable, truth_table
from logicai.circuit import Circuit, NodeKind
from logicai.errors import LibraryFormatError
from logicai.flatten import flatten
from logicai.library import Library, LibraryLimits, Outcome, Registration
from logicai.serialization import circuit_to_dict


def _stored_table(library: Library, name: str) -> TruthTable:
    circuit = library.component(name).circuit
    return truth_table(flatten(circuit, library.definitions()))


def _xnor_from_xor_component(library: Library) -> Circuit:
    """NON(XOR) : un circuit qui pose le composant XOR."""
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    xor_id = library.instantiate(circuit, "XOR")
    wire(circuit, a, xor_id, 0)
    wire(circuit, b, xor_id, 1)
    wire(circuit, add_not(circuit, xor_id), circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _constant_one() -> Circuit:
    return gate(0, lambda circuit, _: circuit.add_node(NodeKind.NAND))


def _full_library() -> Library:
    """NOT, AND, XOR (record), XNOR qui utilise XOR, et une constante sans nom connu."""
    library = Library()
    library.register(not_circuit())
    library.register(gate(2, build_and))
    library.register(gate(2, bloated(build_xor)))
    library.register(xor_circuit())  # record : XOR passe de 6 à 4 NAND
    library.register(_xnor_from_xor_component(library))
    library.register(_constant_one())
    return library


def _write(
    directory: Path, name: str, circuit: Circuit, file_name: str | None = None
) -> None:
    """Écrit à la main un fichier de composant (pour fabriquer des fichiers faux)."""
    text = json.dumps(circuit_to_dict(name, circuit), indent=2)
    (directory / (file_name or f"{name}.json")).write_text(text, encoding="utf-8")


# --- Sauvegarder -----------------------------------------------------------------


def test_save_writes_one_json_file_per_component(tmp_path: Path) -> None:
    # Règle vérifiée : cahier, « Enregistrement dans la bibliothèque, sous forme de
    # fichier JSON » ; décision du plan (un fichier par composant, <nom>.json).
    library = _full_library()
    library.save(tmp_path / "bibliotheque")
    files = sorted(path.name for path in (tmp_path / "bibliotheque").iterdir())
    assert files == sorted(f"{name}.json" for name in library.names())


def test_saved_not_matches_the_cahiers_example(tmp_path: Path) -> None:
    # Règle vérifiée : cahier, « Exemple de circuit en JSON », avec les positions x et y
    # (calculées par Python depuis la phase 3).
    library = Library()
    library.register(not_circuit())
    library.save(tmp_path)
    written = json.loads((tmp_path / "NOT.json").read_text(encoding="utf-8"))
    assert written == {
        "nom": "NOT",
        "noeuds": [
            {"id": 0, "type": "ENTREE", "x": 0, "y": 0},
            {"id": 1, "type": "NAND", "x": 2, "y": 0},
            {"id": 2, "type": "SORTIE", "x": 4, "y": 0},
        ],
        "cables": [
            {"de": [0, 0], "vers": [1, 0]},
            {"de": [0, 0], "vers": [1, 1]},
            {"de": [1, 0], "vers": [2, 0]},
        ],
    }


def test_save_creates_missing_folders_and_handles_an_empty_library(
    tmp_path: Path,
) -> None:
    # Règle vérifiée : CLAUDE.md (pas de surprise pour l'appelant).
    target = tmp_path / "a" / "b"
    Library().save(target)
    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_saving_again_replaces_a_component_by_its_record(tmp_path: Path) -> None:
    # Règle vérifiée : cahier, « Composants et bibliothèque » (le record remplace la
    # définition) : la sauvegarde suivante écrit la version la plus petite.
    library = Library()
    library.register(gate(2, bloated(build_xor)))
    library.save(tmp_path)
    assert Library.load(tmp_path).cost("XOR") == 6
    library.register(xor_circuit())
    library.save(tmp_path)
    assert Library.load(tmp_path).cost("XOR") == 4


# --- Recharger --------------------------------------------------------------------


def test_load_gives_back_the_same_library(tmp_path: Path) -> None:
    # Règle vérifiée : cahier, « Enregistrement » (sauvegarder puis relire) : mêmes
    # composants, mêmes définitions, signatures, coûts et tables de vérité.
    library = _full_library()
    library.save(tmp_path)
    loaded = Library.load(tmp_path)

    assert set(loaded.names()) == set(library.names())
    for name in library.names():
        original, restored = library.component(name), loaded.component(name)
        assert restored.signature == original.signature
        assert loaded.cost(name) == library.cost(name)
        assert _stored_table(loaded, name) == _stored_table(library, name)
        assert restored.circuit.nodes() == original.circuit.nodes()
        assert restored.circuit.wires() == original.circuit.wires()


def test_loaded_names_are_in_file_order(tmp_path: Path) -> None:
    # Règle vérifiée : contrat de ``Library.names`` (après un rechargement, l'ordre
    # alphabétique des fichiers).
    library = _full_library()
    library.save(tmp_path)
    assert Library.load(tmp_path).names() == tuple(sorted(library.names()))


def test_a_component_can_come_before_the_one_it_uses(tmp_path: Path) -> None:
    # Règle vérifiée : cahier, « Les composants sont rangés par référence ». XNOR
    # utilise XOR et son fichier est lu avant (ordre alphabétique) : le rechargement
    # n'en dépend pas.
    library = _full_library()
    library.save(tmp_path)
    assert library.component("XNOR").circuit.nodes()[2].component_ref == "XOR"
    assert sorted(library.names()).index("XNOR") < sorted(library.names()).index("XOR")
    assert Library.load(tmp_path).cost("XNOR") == 5  # NON(XOR) = 4 + 1


def test_loaded_library_keeps_working(tmp_path: Path) -> None:
    # Règle vérifiée : cahier, « Système de récompense » (déjà connu / record /
    # nouveauté) sur une bibliothèque rechargée ; la numérotation continue.
    library = _full_library()
    library.save(tmp_path)
    loaded = Library.load(tmp_path)

    assert loaded.register(not_circuit()) == Registration(Outcome.KNOWN, "NOT")
    assert loaded.register(gate(2, bloated(build_and))) == Registration(
        Outcome.KNOWN, "AND"
    )
    new = loaded.register(
        gate(3, lambda c, i: add_nand(c, add_nand(c, i[0], i[1]), i[2]))
    )
    assert new == Registration(Outcome.NEW, "C-002")  # C-001 existait déjà


def test_loaded_library_can_still_beat_a_record(tmp_path: Path) -> None:
    # Règle vérifiée : cahier, « Composants et bibliothèque » (record après un
    # rechargement).
    library = Library()
    library.register(gate(2, bloated(build_xor)))
    library.save(tmp_path)
    loaded = Library.load(tmp_path)
    assert loaded.register(xor_circuit()) == Registration(Outcome.RECORD, "XOR")
    assert loaded.cost("XOR") == 4


def test_loading_an_empty_folder_gives_an_empty_library(tmp_path: Path) -> None:
    # Règle vérifiée : cahier, « Bibliothèque » (une bibliothèque peut être vide).
    (tmp_path / "notes.txt").write_text("pas un composant", encoding="utf-8")
    assert Library.load(tmp_path).names() == ()


def test_limits_are_applied_when_loading(tmp_path: Path) -> None:
    # Règle vérifiée : réponse de Téo (limites réglables) : une bibliothèque sauvée sans
    # limite et rechargée avec les limites par défaut est refusée, pas tronquée.
    big = gate(16, lambda c, i: add_nand(c, i[0], i[1]))
    library = Library(LibraryLimits.unlimited())
    library.register(big)
    library.save(tmp_path)
    with pytest.raises(LibraryFormatError, match="16"):
        Library.load(tmp_path)
    assert Library.load(tmp_path, LibraryLimits.unlimited()).names() == ("C-001",)


# --- Fichiers invalides -----------------------------------------------------------


def test_missing_folder_is_refused(tmp_path: Path) -> None:
    # Règle vérifiée : CLAUDE.md (erreur dédiée, pas une bibliothèque vide par erreur).
    with pytest.raises(LibraryFormatError):
        Library.load(tmp_path / "n-existe-pas")


def test_file_that_is_not_json_is_refused(tmp_path: Path) -> None:
    # Règle vérifiée : CLAUDE.md (erreur dédiée, le message nomme le fichier).
    (tmp_path / "NOT.json").write_text("{", encoding="utf-8")
    with pytest.raises(LibraryFormatError, match="NOT.json"):
        Library.load(tmp_path)


def test_file_that_is_not_text_is_refused(tmp_path: Path) -> None:
    # Règle vérifiée : CLAUDE.md (erreur dédiée).
    (tmp_path / "NOT.json").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(LibraryFormatError, match="NOT.json"):
        Library.load(tmp_path)


def test_name_in_the_file_must_match_the_file_name(tmp_path: Path) -> None:
    # Règle vérifiée : décision du plan (un fichier par composant, <nom>.json).
    _write(tmp_path, "NOT", not_circuit(), file_name="AND.json")
    with pytest.raises(LibraryFormatError, match="AND.json"):
        Library.load(tmp_path)


def test_unknown_component_reference_in_a_file_is_refused(tmp_path: Path) -> None:
    # Règle vérifiée : cahier, « Les composants sont rangés par référence ».
    circuit = Circuit()
    circuit.add_node(NodeKind.INPUT)
    wire(
        circuit,
        circuit.add_component_node("GHOST", 1, 1),
        circuit.add_node(NodeKind.OUTPUT),
    )
    _write(tmp_path, "TOP", circuit)
    with pytest.raises(LibraryFormatError, match="GHOST"):
        Library.load(tmp_path)


def test_pin_counts_that_disagree_with_the_definition_are_refused(
    tmp_path: Path,
) -> None:
    # Règle vérifiée : cahier, « Ordre des broches » (le nœud doit avoir les broches de
    # la définition qu'il référence).
    _write(tmp_path, "NOT", not_circuit())
    circuit = Circuit()
    wire(
        circuit,
        circuit.add_component_node("NOT", 2, 1),
        circuit.add_node(NodeKind.OUTPUT),
    )
    _write(tmp_path, "TOP", circuit)
    with pytest.raises(LibraryFormatError, match="TOP"):
        Library.load(tmp_path)


def test_components_that_contain_each_other_are_refused(tmp_path: Path) -> None:
    # Règle vérifiée : cahier, « Simulation d'un composant » (aplatir doit se terminer).
    for name, other in (("A", "B"), ("B", "A")):
        circuit = Circuit()
        inside = circuit.add_component_node(other, 1, 1)
        wire(circuit, circuit.add_node(NodeKind.INPUT), inside)
        wire(circuit, inside, circuit.add_node(NodeKind.OUTPUT))
        _write(tmp_path, name, circuit)
    with pytest.raises(LibraryFormatError):
        Library.load(tmp_path)


def test_two_files_with_the_same_function_are_refused(tmp_path: Path) -> None:
    # Règle vérifiée : cahier, « Système de récompense » et décision de Téo (une seule
    # découverte par signature, entrées permutées comprises).
    _write(tmp_path, "AND", gate(2, build_and))
    _write(tmp_path, "C-001", gate(2, bloated(build_and)))
    with pytest.raises(LibraryFormatError, match="même fonction"):
        Library.load(tmp_path)


def test_unstable_component_in_a_file_is_refused(tmp_path: Path) -> None:
    # Règle vérifiée : cahier, « Les trois cas détectés » (instable : rejeté).
    looped = Circuit()
    nand_id = looped.add_node(NodeKind.NAND)
    wire(looped, nand_id, nand_id, 0)
    wire(looped, nand_id, nand_id, 1)
    wire(looped, nand_id, looped.add_node(NodeKind.OUTPUT))
    _write(tmp_path, "LOOP", looped)
    with pytest.raises(LibraryFormatError, match="LOOP"):
        Library.load(tmp_path)


def test_component_without_output_in_a_file_is_refused(tmp_path: Path) -> None:
    # Règle vérifiée : décision du plan (un circuit sans sortie est refusé).
    circuit = Circuit()
    circuit.add_node(NodeKind.INPUT)
    _write(tmp_path, "VIDE", circuit)
    with pytest.raises(LibraryFormatError, match="VIDE"):
        Library.load(tmp_path)
