"""Messages Python vers Unity (cahier, « La liaison ») : une ligne de JSON par message.

Chaque message est un objet JSON écrit sur **une seule ligne** (UTF-8, terminée par
un retour à la ligne). La clé ``"message"`` donne son type. Quatre types servent à la
phase 5 :

=============== ====================================================================
``circuit``     un circuit complet (format des fichiers de la phase 3)
``etat``        les valeurs 0/1 de chaque nœud et de chaque câble à un top
``decouverte``  un nouveau composant, avec son ordre de pose (pour la rediffusion)
``stats``       palier, génération, nombre de découvertes, récompense moyenne
=============== ====================================================================

Le type ``action`` du cahier (poser, câbler, retirer une pièce à la fois) sert à la
construction pas à pas de l'IA 2 : il viendra à la phase 7. L'ordre de pose d'une
découverte utilise déjà son vocabulaire (``poser``, ``cabler``).

Ce module ne fait que construire, écrire et relire des messages : il n'ouvre aucun
socket (voir ``live_server``).
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from logicai.circuit import Circuit
from logicai.errors import InvalidMessageError
from logicai.reward import TrialKind
from logicai.serialization import circuit_to_dict, state_to_dict
from logicai.snapshot import Snapshot

# La clé qui donne le type d'un message, et les quatre types de la phase 5.
MESSAGE_KEY = "message"
CIRCUIT_MESSAGE = "circuit"
STATE_MESSAGE = "etat"
DISCOVERY_MESSAGE = "decouverte"
STATS_MESSAGE = "stats"
MESSAGE_NAMES = frozenset(
    {CIRCUIT_MESSAGE, STATE_MESSAGE, DISCOVERY_MESSAGE, STATS_MESSAGE}
)

# Le genre d'une découverte, tel qu'il est écrit dans le message.
_DISCOVERY_KINDS = {TrialKind.NEW: "nouveaute", TrialKind.RECORD: "record"}

_END_OF_LINE = b"\n"


def circuit_message(
    name: str, circuit: Circuit, snapshot: Snapshot | None = None
) -> dict[str, Any]:
    """Construit le message d'un circuit, avec ses valeurs si un relevé est donné."""
    return {
        MESSAGE_KEY: CIRCUIT_MESSAGE,
        "circuit": circuit_to_dict(name, circuit, snapshot),
    }


def state_message(circuit: Circuit, snapshot: Snapshot) -> dict[str, Any]:
    """Construit le message des valeurs 0/1 d'un circuit à un top.

    Le relevé doit venir de ce circuit : ``state_to_dict`` le vérifie.
    """
    return {MESSAGE_KEY: STATE_MESSAGE, "etat": state_to_dict(circuit, snapshot)}


def discovery_message(
    name: str,
    kind: TrialKind,
    cost: int,
    circuit: Circuit,
    placement: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Construit le message d'une découverte (nouveauté ou record).

    ``circuit`` est la définition du composant (elle peut poser d'autres composants),
    ``cost`` son nombre de NAND après aplatissement, et ``placement`` son ordre de pose.
    """
    if kind not in _DISCOVERY_KINDS:
        raise InvalidMessageError(
            f"Une découverte est une nouveauté ou un record, pas {kind.name}."
        )
    return {
        MESSAGE_KEY: DISCOVERY_MESSAGE,
        "nom": name,
        "genre": _DISCOVERY_KINDS[kind],
        "cout": cost,
        "circuit": circuit_to_dict(name, circuit),
        "ordre_de_pose": [dict(step) for step in placement],
    }


def stats_message(
    stage: int, generation: int, discoveries: int, mean_reward: float
) -> dict[str, Any]:
    """Construit le message des statistiques pour le panneau d'information."""
    return {
        MESSAGE_KEY: STATS_MESSAGE,
        "palier": stage,
        "generation": generation,
        "decouvertes": discoveries,
        "recompense_moyenne": mean_reward,
    }


def encode_message(message: Mapping[str, Any]) -> bytes:
    """Écrit un message en une ligne de JSON UTF-8, terminée par un retour à la ligne.

    Refuse un type inconnu et les valeurs que JSON ne sait pas écrire (NaN, infini).
    Un retour à la ligne dans un texte est échappé : le message reste sur une ligne.
    """
    _check_name(message)
    try:
        text = json.dumps(
            message, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as error:
        raise InvalidMessageError(
            f"Le message {message[MESSAGE_KEY]!r} ne s'écrit pas en JSON : {error}."
        ) from error
    return text.encode("utf-8") + _END_OF_LINE


def decode_message(line: bytes | str) -> dict[str, Any]:
    """Relit une ligne écrite par ``encode_message`` (retour à la ligne facultatif).

    Sert aux tests et à tout client Python. Refuse un texte qui n'est pas un objet JSON
    ou dont le type est inconnu.
    """
    text = line.decode("utf-8") if isinstance(line, bytes) else line
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise InvalidMessageError(f"La ligne n'est pas du JSON : {error}.") from error
    if not isinstance(data, dict):
        raise InvalidMessageError("Un message doit être un objet JSON.")
    _check_name(data)
    return data


def _check_name(message: Mapping[str, Any]) -> None:
    """Refuse un message sans type, ou avec un type que la phase 5 ne connaît pas."""
    name = message.get(MESSAGE_KEY)
    if name not in MESSAGE_NAMES:
        raise InvalidMessageError(
            f"Type de message inconnu : {name!r} (types connus : "
            f"{', '.join(sorted(MESSAGE_NAMES))})."
        )
