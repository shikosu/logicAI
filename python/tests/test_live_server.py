"""Tests du serveur de la liaison (cahier : « l'entraînement n'attend jamais Unity »).

Ces tests utilisent de vrais sockets sur la machine locale (port choisi par l'OS).
"""

import socket
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from logicai.errors import InvalidMessageError, LiveServerError
from logicai.live_server import LOCAL_HOST, LiveServer
from logicai.protocol import decode_message, stats_message

# Attente maximale d'un événement réseau dans un test (largement assez, sans être long).
TIMEOUT = 5.0
# Une charge qui remplit vite les tampons du système : environ 80 Ko par message.
PADDING = [0] * 20000
# Pour déborder : une petite file (20 messages) et assez d'envois pour remplir aussi
# les tampons du système (environ 300 messages de 80 Ko, soit 24 Mo).
SMALL_QUEUE = 20
FLOOD_COUNT = 300


def _wait_for(condition: Callable[[], bool], timeout: float = TIMEOUT) -> bool:
    """Attend qu'une condition devienne vraie ; dit si elle l'est devenue."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def _numbered(kind: str, number: int, padding: bool = False) -> dict[str, Any]:
    """Un message de type ``kind`` portant un numéro (et de la charge si demandé)."""
    message: dict[str, Any] = {"message": kind, "numero": number}
    if padding:
        message["charge"] = PADDING
    return message


class _Client:
    """Un faux Unity : un socket qui lit des lignes JSON."""

    def __init__(self, server: LiveServer) -> None:
        self.socket = socket.create_connection(
            (LOCAL_HOST, server.port), timeout=TIMEOUT
        )
        self._buffer = b""

    def read_lines(self, count: int) -> list[dict[str, Any]]:
        """Lit exactement ``count`` messages (ou échoue après le délai)."""
        lines = []
        while len(lines) < count:
            while b"\n" not in self._buffer:
                chunk = self.socket.recv(1 << 16)
                assert chunk, "le serveur a fermé la connexion trop tôt"
                self._buffer += chunk
            line, _, self._buffer = self._buffer.partition(b"\n")
            lines.append(decode_message(line))
        return lines

    def read_until_idle(self, quiet: float = 0.3) -> list[dict[str, Any]]:
        """Lit tout ce qui arrive jusqu'à un silence de ``quiet`` secondes."""
        self.socket.settimeout(quiet)
        lines: list[dict[str, Any]] = []
        try:
            while True:
                chunk = self.socket.recv(1 << 16)
                if not chunk:
                    break
                self._buffer += chunk
                while b"\n" in self._buffer:
                    line, _, self._buffer = self._buffer.partition(b"\n")
                    lines.append(decode_message(line))
        except TimeoutError:
            pass
        finally:
            self.socket.settimeout(TIMEOUT)
        return lines

    def closed_by_server(self) -> bool:
        """Dit si le serveur a fermé la connexion (lecture vide)."""
        try:
            return self.socket.recv(1) == b""
        except (ConnectionError, TimeoutError):
            return False

    def reaches_end(self) -> bool:
        """Lit tout jusqu'à la fin de la connexion ; dit si elle a bien eu lieu."""
        try:
            while self.socket.recv(1 << 16):
                pass
        except (ConnectionError, TimeoutError):
            return False
        return True

    def close(self) -> None:
        self.socket.close()


@pytest.fixture
def server() -> Iterator[LiveServer]:
    """Un serveur démarré sur un port libre, arrêté à la fin du test."""
    with LiveServer(port=0) as running:
        yield running


@pytest.fixture
def small_server() -> Iterator[LiveServer]:
    """Un serveur dont la file ne garde que 20 messages : il déborde vite."""
    with LiveServer(port=0, max_pending=SMALL_QUEUE) as running:
        yield running


def _connect(server: LiveServer) -> _Client:
    """Branche un faux Unity et attend que le serveur l'ait accepté."""
    client = _Client(server)
    assert _wait_for(lambda: server.connected), "le serveur n'a pas accepté le client"
    return client


# --- Démarrage et arrêt ------------------------------------------------------


def test_server_listens_on_the_local_machine_only(server: LiveServer) -> None:
    # Règle : cahier : « socket TCP local (adresse 127.0.0.1) ». Le port 0 laisse l'OS
    # choisir un port libre, que ``port`` rend.
    assert server.port > 0
    assert server.address == ("127.0.0.1", server.port)  # (pas 0.0.0.0 : seulement ici)
    probe = socket.create_connection((LOCAL_HOST, server.port), timeout=TIMEOUT)
    assert probe.getpeername()[0] == "127.0.0.1"
    probe.close()


def test_port_and_address_are_unknown_before_start() -> None:
    # Règle : erreur dédiée si on demande le port d'un serveur non démarré.
    idle = LiveServer(port=0)
    with pytest.raises(LiveServerError):
        _ = idle.port
    with pytest.raises(LiveServerError):
        _ = idle.address


def test_second_start_and_busy_port_are_refused(server: LiveServer) -> None:
    # Règle : erreurs dédiées avec un message qui dit ce qui est refusé.
    with pytest.raises(LiveServerError, match="déjà démarré"):
        server.start()
    other = LiveServer(port=server.port)
    with pytest.raises(LiveServerError, match="Impossible d'écouter"):
        other.start()


def test_stop_closes_the_client_and_frees_the_port() -> None:
    # Règle : l'arrêt est propre : le client voit la fin de la connexion, le port est
    # libéré (on peut le rouvrir), et un 2e arrêt ne fait rien.
    running = LiveServer(port=0)
    running.start()
    port = running.port
    client = _connect(running)
    running.stop()
    assert client.closed_by_server()
    running.stop()
    again = LiveServer(port=port)
    again.start()
    again.stop()
    client.close()


def test_nonsense_queue_size_is_refused() -> None:
    # Règle : une file de moins de 1 message n'a pas de sens.
    with pytest.raises(LiveServerError):
        LiveServer(max_pending=0)


# --- Envoyer à Unity ---------------------------------------------------------


def test_client_receives_messages_in_order_as_json_lines(server: LiveServer) -> None:
    # Règle : cahier : « chaque message est une ligne de texte JSON ». Ordre conservé.
    client = _connect(server)
    sent = [_numbered("circuit", 0), _numbered("etat", 1), stats_message(1, 2, 3, 0.5)]
    for message in sent:
        server.send(message)
    assert client.read_lines(3) == sent
    client.close()


def test_malformed_message_is_refused_and_nothing_is_sent(server: LiveServer) -> None:
    # Règle : un message mal formé est refusé (erreur dédiée), le client ne reçoit rien.
    client = _connect(server)
    with pytest.raises(InvalidMessageError):
        server.send({"message": "inconnu"})
    server.send(_numbered("etat", 1))
    assert client.read_lines(1) == [_numbered("etat", 1)]
    client.close()


def test_send_without_client_or_before_start_or_after_stop_never_fails() -> None:
    # Règle : « l'entraînement n'attend jamais Unity » : envoyer sans client, avant le
    # démarrage ou après l'arrêt ne lève jamais d'erreur.
    idle = LiveServer(port=0)
    idle.send(_numbered("etat", 1))
    idle.start()
    idle.send(_numbered("etat", 2))
    idle.stop()
    idle.send(_numbered("etat", 3))
    assert idle.dropped == 0


def test_live_messages_before_connection_are_abandoned(server: LiveServer) -> None:
    # Règle : sans client, circuit et etat sont abandonnés (personne ne les regarde) :
    # un client qui arrive ne reçoit que les messages envoyés après sa connexion.
    server.send(_numbered("circuit", 1))
    server.send(_numbered("etat", 2))
    client = _connect(server)
    server.send(_numbered("etat", 3))
    assert client.read_lines(1) == [_numbered("etat", 3)]
    client.close()


# --- Historique pour un Unity qui arrive en retard ---------------------------


def test_late_client_gets_every_discovery_and_the_last_stats(
    server: LiveServer,
) -> None:
    # Règle : cahier : « decouverte : mise à jour de la bibliothèque ». Un Unity qui se
    # connecte en retard reçoit toutes les découvertes, dans l'ordre, et les dernières
    # stats (pas les anciennes), puis les messages en direct, chacun une seule fois.
    for number in range(5):
        server.send(_numbered("decouverte", number))
        server.send(_numbered("stats", 100 + number))
    client = _connect(server)
    server.send(_numbered("decouverte", 5))
    server.send(_numbered("decouverte", 6))
    received = client.read_lines(8)
    assert [m["numero"] for m in received if m["message"] == "decouverte"] == list(
        range(7)
    )
    assert [m["numero"] for m in received if m["message"] == "stats"] == [104]
    assert received[0]["message"] == "decouverte"  # l'historique arrive d'abord
    assert not client.read_until_idle(0.2)  # rien de plus : pas de doublon
    client.close()


def test_new_client_replaces_the_old_one(server: LiveServer) -> None:
    # Règle : un seul client à la fois : la nouvelle connexion remplace l'ancienne, qui
    # est fermée ; le nouveau reçoit l'historique.
    server.send(_numbered("decouverte", 1))
    first = _connect(server)
    assert first.read_lines(1) == [_numbered("decouverte", 1)]
    second = _Client(server)
    assert first.closed_by_server()
    assert second.read_lines(1) == [_numbered("decouverte", 1)]
    first.close()
    second.close()


def test_client_can_leave_and_come_back(server: LiveServer) -> None:
    # Règle : Unity peut se fermer et se rouvrir (il réessaie tout seul) : le serveur
    # continue, et le client qui revient reçoit à nouveau l'historique.
    server.send(_numbered("decouverte", 1))
    first = _connect(server)
    first.read_lines(1)
    first.close()
    assert _wait_for(lambda: not server.connected)
    server.send(_numbered("etat", 2))  # personne : abandonné, sans erreur
    second = _connect(server)
    server.send(_numbered("etat", 3))
    assert second.read_lines(2) == [_numbered("decouverte", 1), _numbered("etat", 3)]
    second.close()


def test_what_unity_writes_is_ignored(server: LiveServer) -> None:
    # Règle : la liaison va de Python vers Unity ; ce que Unity écrit est ignoré.
    client = _connect(server)
    client.socket.sendall(b"du bruit\n" * 100)
    server.send(_numbered("etat", 1))
    assert client.read_lines(1) == [_numbered("etat", 1)]
    client.close()


# --- L'entraînement n'attend jamais Unity ------------------------------------


def test_sending_never_waits_for_a_client_that_does_not_read(
    small_server: LiveServer,
) -> None:
    # Règle (le point central) : un Unity connecté qui ne lit jamais ne ralentit pas
    # l'appelant. 300 messages de 80 Ko (24 Mo) sont envoyés sans lecture : les plus
    # anciens sont jetés, et l'envoi reste rapide (jamais bloqué).
    client = _connect(small_server)
    started = time.monotonic()
    for number in range(FLOOD_COUNT):
        small_server.send(_numbered("etat", number, padding=True))
    elapsed = time.monotonic() - started
    assert elapsed < 10.0  # (un appel bloquant dépasserait le délai du socket, 5 s)
    assert small_server.dropped > 0
    client.close()


def test_slow_client_gets_the_freshest_messages_in_order(
    small_server: LiveServer,
) -> None:
    # Règle : si Unity ne suit pas, on jette les plus anciens : à la reprise de la
    # lecture, les numéros reçus sont croissants, il en manque (jetés), et le dernier
    # envoyé est bien là.
    client = _connect(small_server)
    for number in range(FLOOD_COUNT):
        small_server.send(_numbered("etat", number, padding=True))
    received = [m["numero"] for m in client.read_until_idle(0.5)]
    assert received == sorted(received)
    assert received[-1] == FLOOD_COUNT - 1
    assert 0 < len(received) < FLOOD_COUNT
    # Chaque message est reçu ou compté jeté (un seul peut être en cours d'écriture).
    assert small_server.dropped >= FLOOD_COUNT - len(received) - 1
    client.close()


def test_discoveries_are_never_dropped_even_when_overloaded(
    small_server: LiveServer,
) -> None:
    # Règle : les découvertes ne sont jamais jetées, même si Unity ne suit pas : toutes
    # sont reçues, dans l'ordre, au milieu des messages jetables.
    client = _connect(small_server)
    for number in range(50):
        small_server.send(_numbered("decouverte", number))
        for filler in range(6):
            small_server.send(_numbered("etat", filler, padding=True))
    received = client.read_until_idle(0.5)
    found = [m["numero"] for m in received if m["message"] == "decouverte"]
    assert found == list(range(50))
    assert small_server.dropped > 0
    client.close()


def test_messages_are_kept_when_the_client_keeps_up(server: LiveServer) -> None:
    # Règle : si Unity suit, rien n'est jeté.
    client = _connect(server)
    for number in range(100):
        server.send(_numbered("etat", number))
    assert [m["numero"] for m in client.read_lines(100)] == list(range(100))
    assert server.dropped == 0
    client.close()


def test_messages_without_a_client_are_not_counted_as_dropped() -> None:
    # Règle : « dropped » compte les messages jetés parce qu'Unity ne suivait pas. Sans
    # client, rien n'est mis en file (ni gardé) : même avec une petite file, aucun
    # message n'est compté comme jeté.
    with LiveServer(port=0, max_pending=5) as small:
        for number in range(100):
            small.send(_numbered("etat", number))
        assert small.dropped == 0


@pytest.mark.parametrize("kind", ["circuit", "etat", "stats"])
def test_every_droppable_kind_is_dropped_when_overloaded(
    kind: str, small_server: LiveServer
) -> None:
    # Règle : circuit, etat et stats peuvent être jetés quand Unity ne suit pas (seul le
    # dernier compte) ; le plus récent est toujours conservé.
    client = _connect(small_server)
    for number in range(FLOOD_COUNT):
        small_server.send(_numbered(kind, number, padding=True))
    received = [m["numero"] for m in client.read_until_idle(0.5)]
    assert received[-1] == FLOOD_COUNT - 1
    assert small_server.dropped > 0
    assert len(received) < FLOOD_COUNT
    client.close()


def _flood_without_reading(server: LiveServer) -> None:
    """Inonde un client qui ne lit pas : la file garde des messages en attente."""
    for number in range(FLOOD_COUNT):
        server.send(_numbered("etat", number, padding=True))
    assert server.dropped > 0  # la file est pleine de messages destinés à ce client


def test_new_client_does_not_receive_what_waited_for_the_old_one(
    small_server: LiveServer,
) -> None:
    # Règle : les messages en attente appartiennent au client qui les attendait : le
    # client qui le remplace ne reçoit que l'historique puis les nouveaux messages.
    small_server.send(_numbered("decouverte", 1))
    old = _connect(small_server)
    _flood_without_reading(small_server)
    new = _Client(small_server)
    assert old.reaches_end()  # l'ancien client est fermé par le serveur
    # L'historique n'est écrit qu'une fois le nouveau client installé : le lire sert de
    # point de synchronisation (un message envoyé pendant le remplacement serait
    # abandonné, comme tout message en direct sans client).
    assert new.read_lines(1) == [_numbered("decouverte", 1)]
    small_server.send(_numbered("etat", 1000))
    assert [m["numero"] for m in new.read_until_idle(0.5)] == [1000]
    old.close()
    new.close()


def test_returning_client_does_not_receive_what_waited_for_the_old_one(
    small_server: LiveServer,
) -> None:
    # Règle : même chose quand le client part puis revient : les messages en attente de
    # l'ancienne connexion ne lui sont pas renvoyés.
    small_server.send(_numbered("decouverte", 1))
    old = _connect(small_server)
    _flood_without_reading(small_server)
    old.close()
    assert _wait_for(lambda: not small_server.connected)
    new = _connect(small_server)
    assert new.read_lines(1) == [_numbered("decouverte", 1)]
    small_server.send(_numbered("etat", 1000))
    assert [m["numero"] for m in new.read_until_idle(0.5)] == [1000]
    new.close()
