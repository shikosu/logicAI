"""Tests du directeur de l'affichage (cahier : « un essai en direct au ralenti »).

Le rythme est testé avec une fausse horloge : on la fait avancer à la main, aucun test
n'attend vraiment.
"""

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from logicai.errors import InvalidDirectorSettingsError
from logicai.live_director import LiveDirector

# Rythme des tests (en secondes de la fausse horloge).
TRIAL = 10.0
FRAME = 1.0
STATS = 5.0


class FakeClock:
    """Une horloge qui n'avance que quand on le dit."""

    def __init__(self) -> None:
        """Part d'une heure quelconque (100 s)."""
        self.now = 100.0

    def __call__(self) -> float:
        """Donne l'heure."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Fait avancer l'heure."""
        self.now += seconds


def _setup() -> tuple[LiveDirector, FakeClock, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []
    clock = FakeClock()
    director = LiveDirector(
        sent.append,
        clock,
        trial_interval=TRIAL,
        frame_interval=FRAME,
        stats_interval=STATS,
    )
    return director, clock, sent


def _frames(count: int, tag: str = "t") -> list[dict[str, Any]]:
    """Une suite de ``count`` messages numérotés, comme les images d'un essai."""
    return [{"message": "etat", "tag": tag, "numero": n} for n in range(count)]


def _numbers(sent: list[dict[str, Any]], tag: str = "t") -> list[int]:
    return [m["numero"] for m in sent if m.get("tag") == tag]


# --- Les images d'un essai : une par intervalle ------------------------------


def test_first_message_goes_at_once_then_one_per_frame_interval() -> None:
    # Règle : « au ralenti » : le premier message d'un essai part tout de suite, les
    # suivants à raison d'un par ``frame_interval`` (jamais deux d'un coup).
    director, clock, sent = _setup()
    director.offer_trial(_frames(4))
    assert director.pump() == 1
    assert _numbers(sent) == [0]
    clock.advance(FRAME / 2)
    assert director.pump() == 0  # trop tôt
    clock.advance(FRAME / 2)
    assert director.pump() == 1
    assert _numbers(sent) == [0, 1]
    clock.advance(10 * FRAME)  # même en retard : une seule image par appel
    assert director.pump() == 1
    assert _numbers(sent) == [0, 1, 2]


def test_all_frames_arrive_in_order_exactly_once() -> None:
    # Règle : tout l'essai est montré, dans l'ordre, une seule fois.
    director, clock, sent = _setup()
    director.offer_trial(_frames(5))
    for _ in range(20):
        director.pump()
        clock.advance(FRAME)
    assert _numbers(sent) == [0, 1, 2, 3, 4]


def test_empty_trial_is_ignored() -> None:
    # Règle : une suite vide ne montre rien et ne bloque pas la suite.
    director, _, sent = _setup()
    director.offer_trial([])
    assert director.pump() == 0
    assert not sent
    assert director.wants_trial()


def test_empty_offer_does_not_cancel_the_trial_in_progress() -> None:
    # Règle : une suite vide est ignorée, même pendant un essai : celui-ci continue.
    director, clock, sent = _setup()
    director.offer_trial(_frames(3))
    director.pump()
    director.offer_trial([])
    clock.advance(FRAME)
    director.pump()
    clock.advance(FRAME)
    director.pump()
    assert _numbers(sent) == [0, 1, 2]


def test_new_offer_replaces_the_trial_in_progress() -> None:
    # Règle : un nouvel essai proposé remplace celui qui est en cours.
    director, clock, sent = _setup()
    director.offer_trial(_frames(5, "ancien"))
    director.pump()
    clock.advance(FRAME)
    director.offer_trial(_frames(2, "nouveau"))
    for _ in range(5):
        director.pump()
        clock.advance(FRAME)
    assert _numbers(sent, "ancien") == [0]
    assert _numbers(sent, "nouveau") == [0, 1]


# --- Les essais prioritaires (les découvertes) --------------------------------


def _show_all(director: LiveDirector, clock: FakeClock, steps: int = 30) -> None:
    """Laisse passer le temps : ``pump`` puis une image de plus, ``steps`` fois."""
    for _ in range(steps):
        director.pump()
        clock.advance(FRAME)


def test_a_priority_trial_goes_at_once_even_during_the_pause() -> None:
    # Règle (choix de Téo : « découvertes d'abord ») : une découverte est montrée tout
    # de suite, sans attendre la pause entre deux essais.
    director, clock, sent = _setup()
    director.offer_trial(_frames(1, "ordinaire"))
    director.pump()
    assert not director.wants_trial()  # la pause de TRIAL secondes a commencé
    director.offer_trial(_frames(2, "decouverte"), priority=True)
    director.pump()
    assert _numbers(sent, "decouverte") == [0]
    clock.advance(FRAME)
    director.pump()
    assert _numbers(sent, "decouverte") == [0, 1]


def test_a_priority_trial_replaces_an_ordinary_one_in_progress() -> None:
    # Règle : une découverte passe devant un essai ordinaire en cours.
    director, clock, sent = _setup()
    director.offer_trial(_frames(5, "ordinaire"))
    director.pump()
    clock.advance(FRAME)
    director.offer_trial(_frames(2, "decouverte"), priority=True)
    _show_all(director, clock)
    assert _numbers(sent, "ordinaire") == [0]
    assert _numbers(sent, "decouverte") == [0, 1]


def test_a_priority_trial_in_progress_is_not_interrupted_by_another_one() -> None:
    # Règle : une découverte en cours n'est jamais interrompue ; la 2e proposition
    # prioritaire est ignorée (elle reste dans la bibliothèque et se rejoue).
    director, clock, sent = _setup()
    director.offer_trial(_frames(3, "premiere"), priority=True)
    director.pump()
    clock.advance(FRAME)
    director.offer_trial(_frames(3, "seconde"), priority=True)
    _show_all(director, clock)
    assert _numbers(sent, "premiere") == [0, 1, 2]
    assert _numbers(sent, "seconde") == []


def test_a_priority_trial_in_progress_is_not_replaced_by_an_ordinary_one() -> None:
    # Règle : un essai ordinaire proposé pendant une découverte est ignoré.
    director, clock, sent = _setup()
    director.offer_trial(_frames(3, "decouverte"), priority=True)
    director.pump()
    clock.advance(FRAME)
    director.offer_trial(_frames(3, "ordinaire"))
    _show_all(director, clock)
    assert _numbers(sent, "decouverte") == [0, 1, 2]
    assert _numbers(sent, "ordinaire") == []


def test_priority_is_wanted_unless_a_priority_trial_is_in_progress() -> None:
    # Règle : l'entraînement ne prépare une découverte que si elle peut être montrée.
    director, clock, _ = _setup()
    assert director.wants_priority_trial()  # au repos
    director.offer_trial(_frames(3), priority=False)
    director.pump()
    assert director.wants_priority_trial()  # pendant un essai ordinaire
    director.offer_trial(_frames(3), priority=True)
    director.pump()
    assert not director.wants_priority_trial()  # pendant une découverte
    for _ in range(3):
        clock.advance(FRAME)
        director.pump()
    assert director.wants_priority_trial()  # fini : le suivant peut être prioritaire


def test_after_a_priority_trial_the_next_priority_one_is_shown() -> None:
    # Règle : une fois la découverte finie, la suivante est montrée à son tour.
    director, clock, sent = _setup()
    director.offer_trial(_frames(2, "premiere"), priority=True)
    _show_all(director, clock, 5)
    director.offer_trial(_frames(2, "seconde"), priority=True)
    _show_all(director, clock, 5)
    assert _numbers(sent, "premiere") == [0, 1]
    assert _numbers(sent, "seconde") == [0, 1]


def test_after_a_priority_trial_ordinary_trials_replace_each_other_again() -> None:
    # Règle : le caractère « prioritaire » ne survit pas à la fin de l'essai.
    director, clock, sent = _setup()
    director.offer_trial(_frames(1, "decouverte"), priority=True)
    _show_all(director, clock, 3)
    director.offer_trial(_frames(5, "ancien"))
    director.pump()
    clock.advance(FRAME)
    director.offer_trial(_frames(2, "nouveau"))
    _show_all(director, clock)
    assert _numbers(sent, "ancien") == [0]
    assert _numbers(sent, "nouveau") == [0, 1]


def test_a_priority_trial_is_followed_by_the_usual_pause() -> None:
    # Règle : après une découverte montrée, la pause entre deux essais s'applique.
    director, clock, _ = _setup()
    director.offer_trial(_frames(1), priority=True)
    director.pump()
    assert not director.wants_trial()
    clock.advance(TRIAL - 0.5)
    assert not director.wants_trial()
    clock.advance(0.5)
    assert director.wants_trial()


def test_an_empty_priority_offer_is_ignored() -> None:
    # Règle : une suite vide ne montre rien et n'interrompt rien, même prioritaire.
    director, clock, sent = _setup()
    director.offer_trial(_frames(3, "ordinaire"))
    director.pump()
    director.offer_trial([], priority=True)
    _show_all(director, clock)
    assert _numbers(sent, "ordinaire") == [0, 1, 2]


# --- Quand demander un nouvel essai ------------------------------------------


def test_a_trial_is_wanted_at_the_start() -> None:
    # Règle : au départ, un essai peut être montré tout de suite.
    director, _, _ = _setup()
    assert director.wants_trial()


def test_no_new_trial_while_one_is_being_shown_nor_during_the_pause() -> None:
    # Règle : pas de nouvel essai pendant qu'un autre est montré, ni avant la pause
    # ``trial_interval`` qui suit la dernière image.
    director, clock, _ = _setup()
    director.offer_trial(_frames(3))
    assert not director.wants_trial()  # en cours
    director.pump()
    clock.advance(FRAME)
    director.pump()
    clock.advance(FRAME)
    assert not director.wants_trial()  # encore une image à envoyer
    director.pump()  # dernière image envoyée à cet instant
    assert not director.wants_trial()  # la pause commence
    clock.advance(TRIAL - 0.001)
    assert not director.wants_trial()
    clock.advance(0.001)
    assert director.wants_trial()


# --- Découvertes : tout de suite, dans l'ordre -------------------------------


def test_discoveries_go_at_once_in_order_exactly_once() -> None:
    # Règle : une découverte part au prochain ``pump`` sans attendre le rythme des
    # images, dans l'ordre d'annonce, une seule fois.
    director, _, sent = _setup()
    for number in range(3):
        director.announce_discovery({"message": "decouverte", "numero": number})
    assert director.pump() == 3
    assert [m["numero"] for m in sent] == [0, 1, 2]
    assert director.pump() == 0


def test_discoveries_do_not_disturb_the_frame_rhythm() -> None:
    # Règle : une découverte pendant un essai n'avance ni ne retarde ses images.
    director, clock, sent = _setup()
    director.offer_trial(_frames(3))
    director.pump()
    clock.advance(FRAME / 2)
    director.announce_discovery({"message": "decouverte", "numero": 7})
    assert director.pump() == 1  # la découverte seule
    clock.advance(FRAME / 2)
    assert director.pump() == 1  # l'image 1, à l'heure prévue
    assert _numbers(sent) == [0, 1]
    assert [m["numero"] for m in sent if m["message"] == "decouverte"] == [7]


# --- Statistiques : les dernières, pas trop souvent --------------------------


def test_stats_first_goes_at_once_and_only_the_latest_is_kept() -> None:
    # Règle : seules les dernières stats comptent : si plusieurs arrivent avant l'envoi,
    # seule la dernière part ; la première part tout de suite.
    director, clock, sent = _setup()
    director.update_stats({"message": "stats", "numero": 1})
    director.pump()
    director.update_stats({"message": "stats", "numero": 2})
    director.update_stats({"message": "stats", "numero": 3})
    assert director.pump() == 0  # trop tôt : moins de ``stats_interval`` après la 1re
    clock.advance(STATS)
    assert director.pump() == 1
    assert [m["numero"] for m in sent] == [1, 3]


def test_stats_are_not_sent_twice_when_nothing_changed() -> None:
    # Règle : pas de nouvelles stats, pas de message.
    director, clock, sent = _setup()
    director.update_stats({"message": "stats", "numero": 1})
    director.pump()
    clock.advance(10 * STATS)
    assert director.pump() == 0
    assert len(sent) == 1


def test_stats_respect_their_interval_exactly() -> None:
    # Règle : un message de stats au plus toutes les ``stats_interval`` secondes (borne
    # comprise).
    director, clock, sent = _setup()
    director.update_stats({"message": "stats", "numero": 1})
    director.pump()
    director.update_stats({"message": "stats", "numero": 2})
    clock.advance(STATS - 0.001)
    assert director.pump() == 0
    clock.advance(0.001)
    assert director.pump() == 1
    assert [m["numero"] for m in sent] == [1, 2]


# --- Plusieurs sortes de messages au même tour -------------------------------


def test_everything_due_goes_out_in_one_pump() -> None:
    # Règle : un même ``pump`` envoie, dans cet ordre : les découvertes, les stats, puis
    # une image.
    director, _, sent = _setup()
    director.offer_trial(_frames(2))
    director.update_stats({"message": "stats", "numero": 1})
    director.announce_discovery({"message": "decouverte", "numero": 2})
    assert director.pump() == 3
    assert [m["message"] for m in sent] == ["decouverte", "stats", "etat"]


def test_pump_with_nothing_due_sends_nothing() -> None:
    # Règle : rien à envoyer, rien d'envoyé.
    director, _, sent = _setup()
    assert director.pump() == 0
    assert not sent


# --- Réglages ----------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["trial_interval", "frame_interval", "stats_interval"]
)
def test_negative_intervals_are_refused(field: str) -> None:
    # Règle : erreurs dédiées avec un message qui dit ce qui est refusé.
    with pytest.raises(InvalidDirectorSettingsError, match="négatif"):
        LiveDirector(lambda message: None, **{field: -1.0})


def test_zero_intervals_are_allowed() -> None:
    # Règle : un intervalle nul est permis (tout part d'un coup, image par image).
    director = LiveDirector(
        lambda message: None, trial_interval=0.0, frame_interval=0.0, stats_interval=0.0
    )
    director.offer_trial(_frames(2))
    assert director.pump() == 1
    assert director.pump() == 1
    assert director.wants_trial()


# --- Le fil de présentation (horloge réelle, intervalles minuscules) ---------


def _wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return bool(condition())


def test_presentation_thread_sends_the_trial_in_order_then_stops() -> None:
    # Règle : le fil de présentation appelle ``pump`` tout seul ; l'arrêt est propre,
    # un 2e arrêt ne fait rien, un 2e démarrage est refusé.
    sent: list[dict[str, Any]] = []
    director = LiveDirector(
        sent.append, trial_interval=0.0, frame_interval=0.001, stats_interval=0.0
    )
    director.start()
    with pytest.raises(InvalidDirectorSettingsError, match="déjà démarré"):
        director.start()
    director.offer_trial(_frames(10))
    assert _wait_for(lambda: len(sent) == 10)
    assert _numbers(sent) == list(range(10))
    director.stop()
    director.stop()
    count = len(sent)
    director.offer_trial(_frames(3))
    time.sleep(0.1)
    assert len(sent) == count  # arrêté : plus rien ne part


def test_presentation_thread_survives_a_failing_send() -> None:
    # Règle : une erreur d'envoi est enregistrée et ignorée, le fil continue : le
    # message fautif est perdu, les suivants partent.
    sent: list[dict[str, Any]] = []
    failed = threading.Event()

    def flaky(message: dict[str, Any]) -> None:
        if message["numero"] == 1 and not failed.is_set():
            failed.set()
            raise OSError("envoi impossible")
        sent.append(message)

    director = LiveDirector(
        flaky, trial_interval=0.0, frame_interval=0.001, stats_interval=0.0
    )
    director.start()
    director.offer_trial(_frames(5))
    assert _wait_for(lambda: len(sent) == 4)
    director.stop()
    assert [m["numero"] for m in sent] == [0, 2, 3, 4]
