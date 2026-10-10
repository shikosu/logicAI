"""Tests du format JSON d'un circuit (cahier, « Exemple de circuit en JSON »)."""

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest

from builders import not_circuit, sr_latch, wire, xor_circuit
from logicai.circuit import Circuit, Node, NodeKind, Wire
from logicai.errors import LibraryFormatError
from logicai.serialization import (
    circuit_from_dict,
    circuit_from_json,
    circuit_to_dict,
    circuit_to_json,
)

# L'exemple du cahier : un NOT fait d'une seule NAND dont les deux entrées sont
# alimentées par A (avec les positions x et y, que le modèle Python n'a pas).
CAHIER_EXAMPLE: dict[str, Any] = {
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


def _snapshot(circuit: Circuit) -> tuple[tuple[Node, ...], tuple[Wire, ...]]:
    return circuit.nodes(), circuit.wires()


def _circuit_with_gaps_and_a_component() -> Circuit:
    """Des identifiants avec un trou, et un nœud composant."""
    circuit = Circuit()
    input_a = circuit.add_node(NodeKind.INPUT)
    removed = circuit.add_node(NodeKind.NAND)
    component_id = circuit.add_component_node("XOR", 2, 1)
    wire(circuit, input_a, component_id, 0)
    wire(circuit, input_a, component_id, 1)
    wire(circuit, component_id, circuit.add_node(NodeKind.OUTPUT))
    circuit.remove_node(removed)
    return circuit


# --- Écrire ---------------------------------------------------------------------


def test_not_circuit_is_written_like_the_cahiers_example() -> None:
    # Règle vérifiée : cahier, « Exemple de circuit en JSON » (mêmes clés, mêmes types
    # ENTREE / NAND / SORTIE, mêmes câbles), sans les positions x et y.
    expected = copy.deepcopy(CAHIER_EXAMPLE)
    for node in expected["noeuds"]:
        del node["x"], node["y"]
    assert circuit_to_dict("NOT", not_circuit()) == expected


def test_component_node_carries_its_name_and_pin_counts() -> None:
    # Règle vérifiée : décision du plan (type COMPOSANT avec une référence) et choix
    # de ce format : le fichier d'un circuit se suffit à lui-même.
    written = circuit_to_dict("TOP", _circuit_with_gaps_and_a_component())
    assert written["noeuds"][1] == {
        "id": 2,
        "type": "COMPOSANT",
        "ref": "XOR",
        "entrees": 2,
        "sorties": 1,
    }


def test_json_text_is_valid_and_ends_with_a_newline() -> None:
    # Règle vérifiée : cahier, « Enregistrement ... sous forme de fichier JSON ».
    text = circuit_to_json("NOT", not_circuit())
    assert text.endswith("\n")
    assert json.loads(text) == circuit_to_dict("NOT", not_circuit())


# --- Lire -----------------------------------------------------------------------


def test_the_cahiers_example_can_be_read_with_its_positions() -> None:
    # Règle vérifiée : cahier, « Exemple de circuit en JSON » ; x et y sont acceptés
    # et ignorés (décision du plan).
    name, circuit = circuit_from_dict(CAHIER_EXAMPLE)
    assert name == "NOT"
    assert _snapshot(circuit) == _snapshot(not_circuit())


@pytest.mark.parametrize(
    "make_circuit",
    [not_circuit, xor_circuit, sr_latch, _circuit_with_gaps_and_a_component],
    ids=["NOT", "XOR", "bascule-SR", "trous-et-composant"],
)
def test_writing_then_reading_gives_back_the_same_circuit(
    make_circuit: Callable[[], Circuit],
) -> None:
    # Règle vérifiée : cahier, « Enregistrement » (sauvegarde puis relecture) : mêmes
    # nœuds, mêmes identifiants, mêmes câbles, dans le même ordre.
    original = make_circuit()
    name, restored = circuit_from_json(circuit_to_json("CIRCUIT", original))
    assert name == "CIRCUIT"
    assert _snapshot(restored) == _snapshot(original)


def test_identifiers_read_from_a_file_are_not_reused() -> None:
    # Règle vérifiée : prompt phase 1, section A (identifiant jamais réutilisé).
    _, circuit = circuit_from_dict(CAHIER_EXAMPLE)
    assert circuit.add_node(NodeKind.NAND) == 3


def test_unknown_extra_keys_are_ignored() -> None:
    # Règle vérifiée : décision du plan (la relecture accepte x et y) ; une clé en plus
    # ne casse pas la lecture.
    data = copy.deepcopy(CAHIER_EXAMPLE)
    data["commentaire"] = "ajouté à la main"
    data["noeuds"][0]["couleur"] = "bleu"
    assert _snapshot(circuit_from_dict(data)[1]) == _snapshot(not_circuit())


# --- Fichiers invalides ------------------------------------------------------------


def _break(change: Callable[[dict[str, Any]], object]) -> dict[str, Any]:
    """Part de l'exemple du cahier et y casse quelque chose."""
    data = copy.deepcopy(CAHIER_EXAMPLE)
    change(data)
    return data


_BROKEN_FILES: dict[str, Callable[[dict[str, Any]], object]] = {
    "nom-manquant": lambda d: d.pop("nom"),
    "nom-pas-du-texte": lambda d: d.update(nom=3),
    "nom-vide": lambda d: d.update(nom=""),
    "nom-dangereux": lambda d: d.update(nom="../evil"),
    "noeuds-manquant": lambda d: d.pop("noeuds"),
    "noeuds-pas-une-liste": lambda d: d.update(noeuds={}),
    "cables-manquant": lambda d: d.pop("cables"),
    "noeud-pas-un-objet": lambda d: d["noeuds"].append(5),
    "id-en-texte": lambda d: d["noeuds"][0].update(id="0"),
    # False vaut 0 : sans contrôle du type, ce serait un identifiant valide.
    "id-booleen": lambda d: d["noeuds"][0].update(id=False),
    "id-manquant": lambda d: d["noeuds"][0].pop("id"),
    "type-manquant": lambda d: d["noeuds"][0].pop("type"),
    "type-inconnu": lambda d: d["noeuds"][1].update(type="PORTE"),
    "identifiants-en-double": lambda d: d["noeuds"][1].update(id=0),
    "composant-sans-ref": lambda d: d["noeuds"].append(
        {"id": 3, "type": "COMPOSANT", "entrees": 1, "sorties": 1}
    ),
    "composant-sans-broches": lambda d: d["noeuds"].append(
        {"id": 3, "type": "COMPOSANT", "ref": "XOR"}
    ),
    "composant-broches-negatives": lambda d: d["noeuds"].append(
        {"id": 3, "type": "COMPOSANT", "ref": "XOR", "entrees": -1, "sorties": 1}
    ),
    "cable-sans-de": lambda d: d["cables"][0].pop("de"),
    "cable-pas-un-objet": lambda d: d["cables"].append([0, 0]),
    "broche-trop-courte": lambda d: d["cables"][0].update(de=[0]),
    "broche-avec-du-texte": lambda d: d["cables"][0].update(vers=[1, "0"]),
    "broche-avec-un-booleen": lambda d: d["cables"][0].update(vers=[True, 0]),
    "cable-vers-un-noeud-inconnu": lambda d: d["cables"][0].update(vers=[9, 0]),
    "cable-vers-un-index-inconnu": lambda d: d["cables"][0].update(vers=[1, 5]),
    "mauvais-genre-de-broche": lambda d: d["cables"][2].update(de=[2, 0]),
    "deux-cables-sur-un-puits": lambda d: d["cables"].append(
        {"de": [0, 0], "vers": [1, 0]}
    ),
}


@pytest.mark.parametrize(
    "change", list(_BROKEN_FILES.values()), ids=list(_BROKEN_FILES)
)
def test_broken_file_is_refused_with_a_dedicated_error(
    change: Callable[[dict[str, Any]], object],
) -> None:
    # Règle vérifiée : cahier, règles de câblage (un câble interdit n'est jamais
    # accepté, même venant d'un fichier) ; CLAUDE.md (erreur dédiée, message clair).
    with pytest.raises(LibraryFormatError):
        circuit_from_dict(_break(change))


@pytest.mark.parametrize(
    "data", [[], "NOT", None, 3], ids=["liste", "texte", "null", "nombre"]
)
def test_file_that_is_not_an_object_is_refused(data: object) -> None:
    # Règle vérifiée : CLAUDE.md (erreur dédiée).
    with pytest.raises(LibraryFormatError):
        circuit_from_dict(data)


@pytest.mark.parametrize("text", ["", "{", "{'nom': 'NOT'}", "NOT"])
def test_text_that_is_not_json_is_refused(text: str) -> None:
    # Règle vérifiée : CLAUDE.md (erreur dédiée, message clair).
    with pytest.raises(LibraryFormatError):
        circuit_from_json(text)


def test_error_message_says_where_the_problem_is() -> None:
    # Règle vérifiée : CLAUDE.md (un message dit ce qui est refusé et pourquoi).
    broken = _break(lambda d: d["noeuds"][1].update(type="PORTE"))
    with pytest.raises(LibraryFormatError, match=r"noeuds\[1\].*PORTE"):
        circuit_from_dict(broken)
