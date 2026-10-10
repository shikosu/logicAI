"""Serveur de la liaison avec Unity : un socket TCP local qui n'attend jamais Unity.

Python **écoute** sur ``127.0.0.1`` (décision de Téo) et Unity s'y connecte.
L'entraînement tourne à pleine vitesse (cahier, « Architecture Python / Unity ») :
``send`` rend donc la main tout de suite, quoi que fasse Unity (absent, lent, qui ne lit
plus rien).

Comment c'est obtenu :

- Un seul fil d'exécution gère tous les échanges avec ``select`` et des sockets **non
  bloquants** : il n'écrit que ce que le système accepte, sans jamais attendre.
- ``send`` dépose le message dans une file **bornée** (``max_pending`` messages). Si la
  file déborde, on jette les plus anciens messages ``circuit``, ``etat`` et ``stats`` :
  seul le dernier état compte pour un affichage en direct.
- Les messages ``decouverte`` ne sont **jamais** jetés. De plus, le serveur les garde
  tous, ainsi que les dernières ``stats`` : un Unity qui se connecte en retard reçoit
  d'abord ce qu'il a manqué (cahier : « mise à jour de la bibliothèque »).
- Sans client, ``circuit`` et ``etat`` sont simplement abandonnés : personne ne les
  regarde.

Un seul client à la fois : une nouvelle connexion remplace la précédente. Ce que Unity
écrit est ignoré (la liaison va de Python vers Unity). ``send`` ne lève jamais d'erreur
à cause du réseau ; il refuse seulement un message mal formé (``InvalidMessageError``).
"""

import select
import socket
import threading
from collections import deque
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

from logicai.errors import LiveServerError
from logicai.protocol import (
    CIRCUIT_MESSAGE,
    DISCOVERY_MESSAGE,
    MESSAGE_KEY,
    STATE_MESSAGE,
    STATS_MESSAGE,
    encode_message,
)

# Le socket n'écoute que sur la machine locale (cahier : « adresse 127.0.0.1 »).
LOCAL_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
# Messages au plus en attente d'un client lent, avant de jeter les plus anciens.
MAX_PENDING_MESSAGES = 200
# Le fil d'E/S se réveille au moins toutes les 20 ms (pour voir les nouveaux messages).
POLL_SECONDS = 0.02
# Taille d'une lecture des octets envoyés par Unity (ignorés).
_READ_SIZE = 4096
# Combien de connexions peuvent attendre d'être acceptées.
_LISTEN_BACKLOG = 4
# Messages que l'on peut jeter quand la file est pleine.
_DROPPABLE = frozenset({CIRCUIT_MESSAGE, STATE_MESSAGE, STATS_MESSAGE})
# Temps d'attente de la fin du fil d'E/S à l'arrêt.
_JOIN_SECONDS = 2.0


class LiveServer:
    """Envoie des messages à Unity, sans jamais attendre après lui."""

    def __init__(
        self, port: int = DEFAULT_PORT, max_pending: int = MAX_PENDING_MESSAGES
    ) -> None:
        """Prépare le serveur (``start`` l'ouvre). ``port=0`` laisse l'OS choisir."""
        if max_pending < 1:
            raise LiveServerError(
                f"La file doit garder au moins 1 message (reçu : {max_pending})."
            )
        self._requested_port = port
        self._max_pending = max_pending
        self._lock = threading.Lock()
        # État partagé entre le fil de l'appelant et le fil d'E/S (sous verrou).
        self._pending: deque[tuple[str, bytes]] = deque()
        self._discoveries: list[bytes] = []
        self._last_stats: bytes | None = None
        self._connected = False
        self._dropped = 0
        # État du seul fil d'E/S : pas besoin de verrou.
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._listener: socket.socket | None = None
        self._client: socket.socket | None = None
        self._out = bytearray()

    # --- Cycle de vie -------------------------------------------------------

    def start(self) -> None:
        """Ouvre le port et lance le fil d'E/S ; refuse un 2e démarrage."""
        if self._thread is not None:
            raise LiveServerError("Le serveur est déjà démarré.")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((LOCAL_HOST, self._requested_port))
            listener.listen(_LISTEN_BACKLOG)
            listener.setblocking(False)
        except OSError as error:
            listener.close()
            raise LiveServerError(
                f"Impossible d'écouter sur {LOCAL_HOST}:{self._requested_port} : "
                f"{error}."
            ) from error
        self._listener = listener
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._run, name="logicai-live-server", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Arrête le fil d'E/S et ferme les sockets. Sans effet si déjà arrêté."""
        thread, self._thread = self._thread, None
        if thread is None:
            return
        self._stopping.set()
        thread.join(_JOIN_SECONDS)
        self._close_client()
        if self._listener is not None:
            self._listener.close()
            self._listener = None

    def __enter__(self) -> Self:
        """Démarre le serveur (usage avec ``with``)."""
        self.start()
        return self

    def __exit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Arrête le serveur à la sortie du ``with``."""
        self.stop()

    # --- Lecture de l'état --------------------------------------------------

    @property
    def port(self) -> int:
        """Renvoie le port réellement ouvert (utile avec ``port=0``)."""
        if self._listener is None:
            raise LiveServerError("Le serveur n'est pas démarré.")
        return int(self._listener.getsockname()[1])

    @property
    def address(self) -> tuple[str, int]:
        """Renvoie l'adresse et le port sur lesquels le serveur écoute."""
        if self._listener is None:
            raise LiveServerError("Le serveur n'est pas démarré.")
        host, port = self._listener.getsockname()
        return str(host), int(port)

    @property
    def connected(self) -> bool:
        """Dit si Unity est connecté."""
        with self._lock:
            return self._connected

    @property
    def dropped(self) -> int:
        """Renvoie combien de messages ont été jetés parce que Unity ne suivait pas."""
        with self._lock:
            return self._dropped

    # --- Envoi --------------------------------------------------------------

    def send(self, message: Mapping[str, Any]) -> None:
        """Envoie un message à Unity, sans attendre (la main est rendue aussitôt)."""
        data = encode_message(message)
        name = str(message[MESSAGE_KEY])
        with self._lock:
            if name == DISCOVERY_MESSAGE:
                self._discoveries.append(data)
            elif name == STATS_MESSAGE:
                self._last_stats = data
            if not self._connected:
                return
            self._pending.append((name, data))
            while len(self._pending) > self._max_pending and self._drop_oldest():
                self._dropped += 1

    def _drop_oldest(self) -> bool:
        """Jette le plus ancien message jetable ; dit s'il y en avait un."""
        for index, (name, _) in enumerate(self._pending):
            if name in _DROPPABLE:
                del self._pending[index]
                return True
        return False

    # --- Le fil d'E/S -------------------------------------------------------

    def _run(self) -> None:
        """Boucle du fil d'E/S : accepter, lire (pour voir les départs), écrire."""
        while not self._stopping.is_set():
            listener, client = self._listener, self._client
            if listener is None:
                return
            readers = [listener] if client is None else [listener, client]
            writers = [client] if client is not None and self._has_output() else []
            try:
                readable, writable, _ = select.select(
                    readers, writers, [], POLL_SECONDS
                )
            except (OSError, ValueError):
                return  # un socket a été fermé par stop()
            # D'abord le client du début du tour, tant que c'est encore lui ;
            # l'acceptation d'un nouveau client vient en dernier, car elle remplace (et
            # ferme) l'ancien.
            if client is not None and client in readable:
                self._read_client(client)
            if client is not None and client in writable and self._client is client:
                self._write_client(client)
            if listener in readable:
                self._accept(listener)

    def _has_output(self) -> bool:
        """Dit s'il reste quelque chose à écrire au client."""
        if self._out:
            return True
        with self._lock:
            return bool(self._pending)

    def _accept(self, listener: socket.socket) -> None:
        """Remplace le client en cours par le nouveau, qui reçoit l'historique.

        ``_close_client`` a vidé la file : le nouveau client ne reçoit rien de ce qui
        attendait l'ancien. Entre-temps, ``send`` n'a rien mis en file (pas de client),
        et les découvertes sont dans l'historique : rien n'est perdu ni reçu deux fois.
        """
        try:
            connection, _ = listener.accept()
        except (BlockingIOError, InterruptedError, OSError):
            return
        self._close_client()
        connection.setblocking(False)
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        with self._lock:
            history = b"".join(self._discoveries)
            if self._last_stats is not None:
                history += self._last_stats
            self._connected = True
        self._out = bytearray(history)
        self._client = connection

    def _read_client(self, client: socket.socket) -> None:
        """Lit (et ignore) ce que Unity envoie ; une lecture vide veut dire : parti."""
        try:
            data = client.recv(_READ_SIZE)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self._close_client()
            return
        if not data:
            self._close_client()

    def _write_client(self, client: socket.socket) -> None:
        """Écrit au client ce que le système accepte, sans attendre."""
        if not self._out:
            with self._lock:
                if self._pending:
                    self._out.extend(self._pending.popleft()[1])
        if not self._out:
            return
        try:
            written = client.send(self._out)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self._close_client()
            return
        del self._out[:written]

    def _close_client(self) -> None:
        """Ferme la connexion en cours, s'il y en a une, et oublie ses messages."""
        client, self._client = self._client, None
        if client is not None:
            client.close()
        self._out = bytearray()
        with self._lock:
            self._connected = False
            self._pending.clear()
