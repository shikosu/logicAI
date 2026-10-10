"""Tests des messages Python vers Unity (cahier, « La liaison »)."""

import json
import math

import pytest

from builders import not_circuit, xor_circuit
from logicai.circuit import Circuit, NodeKind, Pin
from logicai.errors import InvalidMessageError, SnapshotError
from logicai.library import Library
from logicai.protocol import (
    CIRCUIT_MESSAGE,
    DISCOVERY_MESSAGE,
    MESSAGE_KEY,
    MESSAGE_NAMES,
    STATE_MESSAGE,
    STATS_MESSAGE,
    circuit_message,
    decode_message,
    discovery_message,
    encode_message,
    state_message,
    stats_message,
)
from logicai.reward import TrialKind
from logicai.serialization import circuit_from_dict, circuit_to_dict, state_to_dict
from logicai.snapshot import settled_snapshot

PLACEMENT = [
    {"action": "poser", "noeud": {"id": 0, "type": "ENTREE", "x": 0, "y": 0}},
    {"action": "cabler", "de": [0, 0], "vers": [1, 0]},
]


def _same_circuit(left: Circuit, right: Circuit) -> bool:
    return (left.nodes(), left.wires()) == (right.nodes(), right.wires())


# --- Les types de messages ---------------------------------------------------


def test_message_names_are_those_of_the_cahier() -> None:
    # Règle : cahier, « La liaison » : circuit, etat, decouverte, stats. Le type
    # « action » (construction pas à pas de l'IA 2) viendra à la phase 7.
    assert {"circuit", "etat", "decouverte", "stats"} == MESSAGE_NAMES
    assert (CIRCUIT_MESSAGE, STATE_MESSAGE) == ("circuit", "etat")
    assert (DISCOVERY_MESSAGE, STATS_MESSAGE) == ("decouverte", "stats")


# --- circuit -----------------------------------------------------------------


def test_circuit_message_carries_a_circuit_that_reads_back() -> None:
    # Règle : message « circuit » = « le circuit complet » (cahier) ; son contenu est le
    # format des fichiers de la phase 3, que Python relit à l'identique.
    circuit = xor_circuit()
    message = decode_message(encode_message(circuit_message("XOR", circuit)))
    assert message[MESSAGE_KEY] == CIRCUIT_MESSAGE
    name, read_back = circuit_from_dict(message["circuit"])
    assert name == "XOR"
    assert _same_circuit(read_back, circuit)
    assert "etat" not in message["circuit"]


def test_circuit_message_can_carry_values() -> None:
    # Règle : la clé « etat » du fichier est facultative : avec un relevé, elle est là.
    circuit = not_circuit()
    snapshot = settled_snapshot(circuit, (0,))
    message = circuit_message("NOT", circuit, snapshot)
    assert message["circuit"]["etat"] == state_to_dict(circuit, snapshot)


# --- etat --------------------------------------------------------------------


def test_state_message_has_the_form_of_the_file_state_key() -> None:
    # Règle : cahier (JSON) : « C'est aussi la forme du message etat » : mêmes clés
    # que la clé « etat » d'un fichier de circuit.
    circuit = not_circuit()
    snapshot = settled_snapshot(circuit, (0,))
    message = state_message(circuit, snapshot)
    assert message == {
        MESSAGE_KEY: STATE_MESSAGE,
        "etat": state_to_dict(circuit, snapshot),
    }
    assert circuit_to_dict("NOT", circuit, snapshot)["etat"] == message["etat"]
    assert set(message["etat"]) == {"top", "stable", "noeuds", "cables"}


def test_state_to_dict_lists_follow_the_circuit_order() -> None:
    # Règle : les listes suivent l'ordre de ``noeuds`` et ``cables`` du circuit. NOT
    # avec A = 0 : entrée 0, NAND 1, sortie 1 ; ses 3 câbles valent 0, 0, 1. Le relevé
    # est au top 2 : au top 1 la NAND passe à 1, le top 2 confirme que rien ne bouge.
    circuit = not_circuit()
    state = state_to_dict(circuit, settled_snapshot(circuit, (0,)))
    assert (state["noeuds"], state["cables"]) == ([0, 1, 1], [0, 0, 1])
    assert (state["top"], state["stable"]) == (2, True)


def test_state_of_another_circuit_is_refused() -> None:
    # Règle : un relevé qui ne correspond pas au circuit est refusé.
    snapshot = settled_snapshot(not_circuit(), (0,))
    with pytest.raises(SnapshotError):
        state_message(xor_circuit(), snapshot)


# --- decouverte --------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "word"),
    [(TrialKind.NEW, "nouveaute"), (TrialKind.RECORD, "record")],
)
def test_discovery_message_fields(kind: TrialKind, word: str) -> None:
    # Règle : cahier : « decouverte : nouveau composant + son ordre de pose ».
    message = discovery_message("NOT", kind, 1, not_circuit(), PLACEMENT)
    assert message[MESSAGE_KEY] == DISCOVERY_MESSAGE
    assert (message["nom"], message["genre"], message["cout"]) == ("NOT", word, 1)
    assert message["ordre_de_pose"] == PLACEMENT
    name, circuit = circuit_from_dict(message["circuit"])
    assert (name, circuit.nand_count()) == ("NOT", 1)


def test_discovery_keeps_component_nodes() -> None:
    # Règle : la définition d'un composant garde ses sous-composants (cahier : les
    # composants sont rangés par référence) ; le message ne les aplatit pas.
    library = Library()
    library.register(not_circuit())
    circuit = Circuit()
    a = circuit.add_node(NodeKind.INPUT)
    node = library.instantiate(circuit, "NOT")
    circuit.connect(Pin(a, 0), Pin(node, 0))
    message = discovery_message("X", TrialKind.NEW, 1, circuit, [])
    kinds = {n["type"] for n in message["circuit"]["noeuds"]}
    assert "COMPOSANT" in kinds
    assert [
        n["ref"] for n in message["circuit"]["noeuds"] if n["type"] == "COMPOSANT"
    ] == ["NOT"]


@pytest.mark.parametrize("kind", [TrialKind.REJECTED, TrialKind.NOTHING])
def test_only_new_or_record_is_a_discovery(kind: TrialKind) -> None:
    # Règle : une découverte est une nouveauté ou un record (cahier, schéma d'un essai).
    with pytest.raises(InvalidMessageError):
        discovery_message("NOT", kind, 1, not_circuit(), [])


def test_discovery_placement_is_copied() -> None:
    # Règle : le message garde sa propre copie de l'ordre de pose (une modification
    # ultérieure de la liste d'origine ne change pas un message déjà construit).
    steps = [dict(step) for step in PLACEMENT]
    message = discovery_message("NOT", TrialKind.NEW, 1, not_circuit(), steps)
    steps[0]["action"] = "retirer"
    assert message["ordre_de_pose"][0]["action"] == "poser"


# --- stats -------------------------------------------------------------------


def test_stats_message_fields() -> None:
    # Règle : cahier : « stats : palier, nombre de découvertes, récompense moyenne ».
    message = stats_message(stage=2, generation=40, discoveries=5, mean_reward=3.5)
    assert message == {
        MESSAGE_KEY: STATS_MESSAGE,
        "palier": 2,
        "generation": 40,
        "decouvertes": 5,
        "recompense_moyenne": 3.5,
    }


# --- Écriture et lecture d'une ligne -----------------------------------------


def test_encoded_message_is_one_utf8_line() -> None:
    # Règle : cahier : « Chaque message est une ligne de texte JSON ». Un retour à la
    # ligne dans un texte est échappé, les accents sont écrits tels quels (UTF-8).
    line = encode_message(circuit_message("é\nà", not_circuit()))
    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1
    text = line.decode("utf-8")
    assert "é\\nà" in text
    assert json.loads(text)["circuit"]["nom"] == "é\nà"
    assert ", " not in text  # écriture compacte


def test_decode_accepts_bytes_str_and_optional_newline() -> None:
    # Règle : le décodeur relit ce que l'encodeur écrit, avec ou sans retour à la ligne.
    message = stats_message(1, 2, 3, 0.5)
    line = encode_message(message)
    assert decode_message(line) == message
    assert decode_message(line.decode("utf-8")) == message
    assert decode_message(line.rstrip(b"\n")) == message


@pytest.mark.parametrize(
    "bad",
    [b"pas du json", b"[1, 2]", b'"texte"', b"{}", b'{"message": "inconnu"}'],
    ids=["texte", "liste", "chaîne", "sans type", "type inconnu"],
)
def test_decode_refuses_malformed_lines(bad: bytes) -> None:
    # Règle : erreur dédiée qui dit ce qui est refusé.
    with pytest.raises(InvalidMessageError):
        decode_message(bad)


def test_encode_refuses_unknown_type_and_non_json_values() -> None:
    # Règle : on n'envoie jamais un type inconnu, ni NaN ou l'infini (JSON ne sait pas
    # les écrire : Unity ne pourrait pas relire la ligne).
    with pytest.raises(InvalidMessageError):
        encode_message({MESSAGE_KEY: "action"})
    with pytest.raises(InvalidMessageError):
        encode_message({"sans": "type"})
    for bad in (math.nan, math.inf):
        with pytest.raises(InvalidMessageError):
            encode_message(stats_message(1, 1, 1, bad))
    with pytest.raises(InvalidMessageError):
        encode_message({MESSAGE_KEY: STATS_MESSAGE, "x": object()})


def test_every_message_type_round_trips() -> None:
    # Règle : tous les messages construits à partir d'un même circuit se relisent.
    circuit = not_circuit()
    for message in (
        circuit_message("NOT", circuit),
        discovery_message("NOT", TrialKind.NEW, 1, circuit, PLACEMENT),
        stats_message(1, 1, 1, 0.0),
    ):
        assert decode_message(encode_message(message)) == message
