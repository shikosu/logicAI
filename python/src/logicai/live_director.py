"""Directeur de l'affichage en direct : quand envoyer quoi à Unity, « au ralenti ».

L'entraînement va à pleine vitesse ; ce que voit Unity doit être lent et lisible
(cahier : « un essai en direct au ralenti, plus la rediffusion de chaque découverte »).
Le directeur règle le **rythme**, sans jamais faire attendre l'entraînement :

- le fil d'entraînement ne fait que des appels courts (``wants_trial``, ``offer_trial``,
  ``announce_discovery``, ``update_stats``) ; il construit lui-même les messages, donc
  il est le seul à toucher à la bibliothèque (pas de course) ;
- un autre fil, le **fil de présentation**, appelle ``pump`` régulièrement : ``pump``
  envoie ce qui est dû, d'après une horloge.

Le rythme :

- un essai montré (voir ``live_show``) est une suite de messages envoyés **un par
  image**, toutes les ``frame_interval`` secondes ; le premier part tout de suite ;
- un nouvel essai n'est demandé que ``trial_interval`` secondes après la fin du
  précédent ;
- les ``stats`` partent au plus toutes les ``stats_interval`` secondes, et seulement
  s'il y en a de nouvelles (seules les dernières comptent) ;
- les découvertes partent à la prochaine occasion, dans l'ordre, sans attendre le
  rythme des images : elles sont rares et ne doivent pas être retardées.

``pump`` n'envoie jamais plus d'une image à la fois. L'horloge est donnée
(``time.monotonic`` par défaut) : les tests la remplacent par une fausse, sans attente
réelle. Les valeurs par défaut sont des valeurs de départ, à régler par essais. Un
message dont l'envoi échoue est perdu (les messages construits ici sont bien formés).
"""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from logicai.errors import InvalidDirectorSettingsError

# Valeurs de départ (à régler par essais), en secondes.
TRIAL_INTERVAL = 3.0  # pause entre la fin d'un essai montré et le suivant
FRAME_INTERVAL = 0.5  # temps entre deux images d'un même essai
STATS_INTERVAL = 1.0  # temps minimal entre deux messages de statistiques
# Le fil de présentation se réveille toutes les 20 ms.
PRESENTATION_POLL = 0.02
# Temps d'attente de la fin du fil de présentation à l'arrêt.
_JOIN_SECONDS = 2.0

_log = logging.getLogger(__name__)

Message = Mapping[str, Any]


class LiveDirector:
    """Règle le rythme des messages envoyés à Unity."""

    def __init__(
        self,
        send: Callable[[Message], None],
        clock: Callable[[], float] = time.monotonic,
        trial_interval: float = TRIAL_INTERVAL,
        frame_interval: float = FRAME_INTERVAL,
        stats_interval: float = STATS_INTERVAL,
    ) -> None:
        """Prépare le directeur : ``send`` envoie un message, ``clock`` l'heure."""
        for label, value in (
            ("entre deux essais", trial_interval),
            ("entre deux images", frame_interval),
            ("entre deux messages de statistiques", stats_interval),
        ):
            if value < 0:
                raise InvalidDirectorSettingsError(
                    f"Le temps {label} ne peut pas être négatif (reçu : {value})."
                )
        self._send = send
        self._clock = clock
        self._trial_interval = trial_interval
        self._frame_interval = frame_interval
        self._stats_interval = stats_interval
        self._lock = threading.Lock()
        # État partagé entre le fil d'entraînement et le fil de présentation.
        self._frames: deque[Message] = deque()
        self._next_frame_time = 0.0
        self._next_trial_time = 0.0
        self._discoveries: deque[Message] = deque()
        self._stats: Message | None = None
        self._next_stats_time = 0.0
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    # --- Appelés par le fil d'entraînement (courts, sans attente) -----------

    def wants_trial(self) -> bool:
        """Dit si un nouvel essai peut être montré (aucun en cours, pause faite)."""
        with self._lock:
            return not self._frames and self._clock() >= self._next_trial_time

    def offer_trial(self, messages: Sequence[Message]) -> None:
        """Propose un essai à montrer (suite de messages) ; remplace l'essai en cours.

        Le premier message part dès le prochain ``pump``, les suivants à raison d'un
        par ``frame_interval``. Une suite vide est ignorée.
        """
        if not messages:
            return
        with self._lock:
            self._frames = deque(messages)
            self._next_frame_time = self._clock()

    def announce_discovery(self, message: Message) -> None:
        """Annonce une découverte : elle part au prochain ``pump``, dans l'ordre."""
        with self._lock:
            self._discoveries.append(message)

    def update_stats(self, message: Message) -> None:
        """Garde les dernières statistiques : seules les plus récentes comptent."""
        with self._lock:
            self._stats = message

    # --- Appelé par le fil de présentation ----------------------------------

    def pump(self) -> int:
        """Envoie ce qui est dû selon l'horloge ; rend le nombre de messages envoyés."""
        due = self._take_due()
        for message in due:
            self._send(message)
        return len(due)

    def _take_due(self) -> list[Message]:
        """Retire, sous verrou, les messages à envoyer maintenant."""
        with self._lock:
            now = self._clock()
            due: list[Message] = list(self._discoveries)
            self._discoveries.clear()
            if self._stats is not None and now >= self._next_stats_time:
                due.append(self._stats)
                self._stats = None
                self._next_stats_time = now + self._stats_interval
            if self._frames and now >= self._next_frame_time:
                due.append(self._frames.popleft())
                self._next_frame_time = now + self._frame_interval
                if not self._frames:
                    self._next_trial_time = now + self._trial_interval
            return due

    # --- Le fil de présentation ---------------------------------------------

    def start(self) -> None:
        """Lance le fil de présentation, qui appelle ``pump`` régulièrement."""
        if self._thread is not None:
            raise InvalidDirectorSettingsError("Le directeur est déjà démarré.")
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._run, name="logicai-live-director", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Arrête le fil de présentation. Sans effet s'il n'est pas démarré."""
        thread, self._thread = self._thread, None
        if thread is None:
            return
        self._stopping.set()
        thread.join(_JOIN_SECONDS)

    def _run(self) -> None:
        """Boucle du fil de présentation : une erreur d'envoi ne l'arrête pas."""
        while not self._stopping.wait(PRESENTATION_POLL):
            try:
                self.pump()
            except Exception:
                _log.exception("Échec de l'envoi d'un message à Unity (ignoré).")
