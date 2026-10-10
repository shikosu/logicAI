"""Test de la phase 5, côté Python (cahier, plan de développement).

Test du cahier : « on regarde l'IA construire pendant que l'entraînement continue à
pleine vitesse ». Ici, avec la vraie IA, le vrai serveur, le vrai fil de présentation et
un faux Unity (un client TCP), on vérifie ce que Python garantit :

- Unity ne change jamais ce que fait l'IA (même graine, mêmes rapports de génération) ;
- l'entraînement n'est pas ralenti, même si Unity ne lit rien (débit mesuré) ;
- Unity peut arriver en retard, partir et revenir pendant que l'IA continue.

La partie Unity (C#) ne peut pas être testée ici : elle est vérifiée sur le Mac de Téo.
"""

import socket
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from typing import Any

from logicai.evolution import Evolution
from logicai.library import Library
from logicai.live import LiveSession
from logicai.live_director import LiveDirector
from logicai.live_server import LiveServer
from logicai.protocol import DISCOVERY_MESSAGE, STATS_MESSAGE, decode_message
from logicai.reward import TrialKind
from logicai.stages import STAGES, Curriculum, StageReport

# Une exécution : assez longue pour passer au palier 2 et faire plusieurs découvertes.
GENERATIONS = 60
STALL = 5
SEED = 0
# Chaque condition est mesurée plusieurs fois : la plus rapide est gardée.
REPEATS = 2
# Marge de tolérance sur le temps : jamais plus de 1,5 fois le temps de l'IA nue, plus
# une marge fixe pour les petites durées (mesuré : écarts de 6 % au plus, du bruit).
SLOWDOWN_FACTOR = 1.5
SLOWDOWN_MARGIN = 0.3
TIMEOUT = 10.0


def _director(send: Callable[[Mapping[str, Any]], None]) -> LiveDirector:
    """Un directeur à pleine cadence (aucune pause) : le maximum d'affichage."""
    return LiveDirector(
        send, trial_interval=0.0, frame_interval=0.0, stats_interval=0.0
    )


def _wait_for(condition: Callable[[], bool], timeout: float = TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


class _Reader(threading.Thread):
    """Un Unity qui lit et jette tout ce qu'il reçoit."""

    def __init__(self, client: socket.socket) -> None:
        """Prépare le fil de lecture (démon)."""
        super().__init__(daemon=True)
        self._client = client
        self.received = 0

    def run(self) -> None:
        """Lit jusqu'à la fermeture de la connexion."""
        try:
            while chunk := self._client.recv(1 << 16):
                self.received += len(chunk)
        except OSError:
            pass


def _run_condition(condition: str) -> tuple[float, list[StageReport]]:
    """Fait jouer l'IA dans une condition d'affichage ; rend durée et rapports."""
    if condition == "bare":
        # L'IA seule : ni directeur, ni crochet, ni réseau (la référence).
        curriculum = Curriculum(Evolution(Library(), STAGES[0].rules, seed=SEED), STALL)
        started = time.perf_counter()
        bare_reports = [curriculum.step() for _ in range(GENERATIONS)]
        return time.perf_counter() - started, bare_reports
    with ExitStack() as stack:
        if condition == "silent":
            director = _director(lambda message: None)
        else:
            server = stack.enter_context(LiveServer(port=0))
            director = _director(server.send)
            if condition in ("idle_client", "reading_client"):
                client = socket.create_connection(
                    ("127.0.0.1", server.port), timeout=TIMEOUT
                )
                stack.callback(client.close)
                assert _wait_for(lambda: server.connected)
                if condition == "reading_client":
                    _Reader(client).start()
        director.start()
        stack.callback(director.stop)
        session = LiveSession(director, seed=SEED, stalled_generations=STALL)
        started = time.perf_counter()
        reports = [session.step() for _ in range(GENERATIONS)]
        return time.perf_counter() - started, reports


def test_unity_never_changes_what_the_ai_does_nor_slows_it_down() -> None:
    # Règle (phase 5) : « l'entraînement continue à pleine vitesse » et « n'attend
    # jamais Unity ». Cinq conditions, même graine : l'IA nue (référence), l'affichage
    # sans réseau, sans client, avec un client qui ne lit jamais, avec un client qui
    # lit. L'IA fait exactement la même chose dans les cinq (mêmes rapports), et n'est
    # pas plus lente (marge : 1,5 fois le temps de l'IA nue, plus 0,3 s).
    results = {}
    for condition in ("bare", "silent", "no_client", "idle_client", "reading_client"):
        runs = [_run_condition(condition) for _ in range(REPEATS)]
        results[condition] = (min(seconds for seconds, _ in runs), runs[0][1])
    reference_seconds, reference_reports = results["bare"]
    timings = {name: round(seconds, 2) for name, (seconds, _) in results.items()}
    for name, (seconds, reports) in results.items():
        assert reports == reference_reports, f"Unity a changé l'IA ({name})"
        limit = SLOWDOWN_FACTOR * reference_seconds + SLOWDOWN_MARGIN
        assert seconds <= limit, f"{name} trop lent : {timings} (limite {limit:.2f} s)"
    assert sum(len(r.generation.discoveries) for r in reference_reports) >= 3


def _expected_discoveries(reports: list[StageReport]) -> list[tuple[str, str]]:
    """Les (genre, nom) des découvertes d'une exécution, dans l'ordre."""
    return [
        ("nouveaute" if d.kind is TrialKind.NEW else "record", str(d.name))
        for report in reports
        for d in report.generation.discoveries
    ]


def _read_for(client: socket.socket, seconds: float) -> list[dict[str, Any]]:
    """Lit les messages reçus pendant ``seconds`` secondes (l'IA en envoie sans fin)."""
    messages: list[dict[str, Any]] = []
    buffer = b""
    deadline = time.monotonic() + seconds
    while (remaining := deadline - time.monotonic()) > 0:
        client.settimeout(remaining)
        try:
            chunk = client.recv(1 << 16)
        except TimeoutError:
            break
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            line, _, buffer = buffer.partition(b"\n")
            messages.append(decode_message(line))
    return messages


def test_late_unity_gets_the_whole_history_of_a_real_run() -> None:
    # Règle : un Unity lancé après l'IA ne manque rien : il reçoit toutes les
    # découvertes déjà faites, chacune une seule fois, dans l'ordre, et les dernières
    # stats.
    with LiveServer(port=0) as server:
        director = _director(server.send)
        director.start()
        try:
            session = LiveSession(director, seed=SEED, stalled_generations=STALL)
            reports = [session.step() for _ in range(GENERATIONS)]
            with socket.create_connection(
                ("127.0.0.1", server.port), timeout=TIMEOUT
            ) as client:
                messages = _read_for(client, 1.0)
        finally:
            director.stop()
    announced = [
        (m["genre"], m["nom"]) for m in messages if m["message"] == DISCOVERY_MESSAGE
    ]
    assert announced == _expected_discoveries(reports)
    generations = [m["generation"] for m in messages if m["message"] == STATS_MESSAGE]
    assert generations == sorted(generations)
    assert generations[-1] == GENERATIONS  # les dernières stats sont bien arrivées


def test_unity_can_leave_and_come_back_while_the_ai_keeps_going() -> None:
    # Règle : Unity peut se fermer et se rouvrir (il réessaie tout seul) : l'IA ne
    # s'arrête pas, et le Unity qui revient reçoit l'historique puis le direct.
    stop = threading.Event()
    played: list[int] = []
    errors: list[Exception] = []
    with LiveServer(port=0) as server:
        director = _director(server.send)
        director.start()
        session = LiveSession(director, seed=SEED, stalled_generations=STALL)

        def train() -> None:
            try:
                played.append(session.run(None, stop.is_set))
            except Exception as error:
                errors.append(error)

        trainer = threading.Thread(target=train, daemon=True)
        trainer.start()
        try:
            first = socket.create_connection(
                ("127.0.0.1", server.port), timeout=TIMEOUT
            )
            first_messages = _read_for(first, 0.5)
            first.close()
            assert _wait_for(lambda: not server.connected)
            second = socket.create_connection(
                ("127.0.0.1", server.port), timeout=TIMEOUT
            )
            second_messages = _read_for(second, 0.5)
            second.close()
        finally:
            stop.set()
            trainer.join(TIMEOUT)
            director.stop()
    assert not errors
    assert not trainer.is_alive()
    assert played and played[0] > 0
    for messages in (first_messages, second_messages):
        assert messages[0]["message"] == DISCOVERY_MESSAGE  # l'historique d'abord
        assert messages[0]["nom"] == "NOT"
    last_generation = max(
        m["generation"] for m in first_messages if m["message"] == STATS_MESSAGE
    )
    later = [m["generation"] for m in second_messages if m["message"] == STATS_MESSAGE]
    assert max(later) > last_generation  # l'IA a continué pendant l'absence
