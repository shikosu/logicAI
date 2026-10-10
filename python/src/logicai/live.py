"""Branchement de la liaison en direct : l'IA tourne, Unity regarde.

``LiveSession`` relie l'IA évolutionnaire (paliers compris) au directeur d'affichage :

- à **chaque essai** (crochet ``on_trial`` d'``Evolution``) :

  - une nouveauté ou un record devient un message ``decouverte`` (circuit, coût, ordre
    de pose), construit tout de suite, quand la bibliothèque vient de changer ;
  - sinon, si le directeur le demande (pause écoulée), un essai accepté est montré
    (message ``circuit`` puis images ``etat``, voir ``live_show``) ;

- à **chaque génération** : des ``stats`` (palier, génération, nombre de découvertes,
  récompense moyenne).

Tout cela se passe dans le fil d'entraînement avec des appels courts : le directeur
envoie ensuite les messages à son rythme, dans son propre fil. Une erreur dans
l'affichage est journalisée et ne casse jamais l'entraînement.

La commande ``python -m logicai.live`` lance l'IA avec le serveur et le directeur
(depuis le dossier ``python/`` : ``PYTHONPATH=src .venv/bin/python -m logicai.live``).
Elle écoute sur ``127.0.0.1`` ; il suffit ensuite de lancer Unity. Ctrl-C arrête
proprement.
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence

from logicai.circuit import Circuit
from logicai.errors import LiveServerError
from logicai.evolution import Evolution, EvolutionSettings
from logicai.library import Library
from logicai.live_director import LiveDirector
from logicai.live_server import DEFAULT_PORT, LiveServer
from logicai.live_show import trial_messages
from logicai.protocol import discovery_message, stats_message
from logicai.replay import placement_order
from logicai.reward import RewardSettings, TrialKind, TrialResult
from logicai.stages import DEFAULT_STALLED_GENERATIONS, STAGES, Curriculum, StageReport

# Codes de sortie de la commande.
EXIT_OK = 0
EXIT_CANNOT_LISTEN = 2

_log = logging.getLogger(__name__)


class LiveSession:
    """Fait tourner l'IA et alimente le directeur de l'affichage."""

    def __init__(
        self,
        director: LiveDirector,
        seed: int = 0,
        stalled_generations: int = DEFAULT_STALLED_GENERATIONS,
        evolution_settings: EvolutionSettings | None = None,
        reward_settings: RewardSettings | None = None,
    ) -> None:
        """Crée l'IA (bibliothèque vide, palier 1) liée au directeur donné."""
        self._director = director
        self._library = Library()
        evolution = Evolution(
            self._library,
            STAGES[0].rules,
            evolution_settings,
            reward_settings,
            seed,
            on_trial=self._on_trial,
        )
        self._curriculum = Curriculum(evolution, stalled_generations)

    @property
    def library(self) -> Library:
        """Renvoie la bibliothèque des composants découverts."""
        return self._library

    def step(self) -> StageReport:
        """Joue une génération, puis met à jour les statistiques affichées."""
        report = self._curriculum.step()
        generation = report.generation
        self._director.update_stats(
            stats_message(
                report.stage,
                generation.generation,
                len(self._library.names()),
                generation.total_reward / generation.trials,
            )
        )
        if report.advanced_to is not None:
            _log.info("Palier %d débloqué.", report.advanced_to)
        return report

    def run(
        self,
        generations: int | None = None,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> int:
        """Joue des générations (sans fin si ``None``) et les compte."""
        played = 0
        while (generations is None or played < generations) and not should_stop():
            self.step()
            played += 1
        return played

    # --- Le crochet appelé après chaque essai (fil d'entraînement) ----------

    def _on_trial(self, circuit: Circuit, result: TrialResult) -> None:
        """Annonce une découverte, ou montre un essai accepté si le directeur veut."""
        try:
            if result.kind in (TrialKind.NEW, TrialKind.RECORD):
                self._announce(result)
            elif result.kind is not TrialKind.REJECTED and self._director.wants_trial():
                messages = trial_messages(circuit, self._library.definitions())
                self._director.offer_trial(messages)
        except Exception:
            _log.exception("Échec de la préparation de l'affichage (ignoré).")

    def _announce(self, result: TrialResult) -> None:
        """Construit et annonce le message d'une nouveauté ou d'un record."""
        name = result.name
        if name is None:  # (impossible pour une découverte ; rassure mypy)
            return
        definition = self._library.component(name).circuit
        cost = self._library.cost(name)
        self._director.announce_discovery(
            discovery_message(
                name, result.kind, cost, definition, placement_order(definition)
            )
        )
        _log.info("Découverte (%s) : %s, %d NAND", result.kind.name, name, cost)


def main(arguments: Sequence[str]) -> int:
    """Lance l'IA avec le serveur et le directeur ; renvoie le code de sortie."""
    options = _parse(arguments)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    server = LiveServer(port=options.port)
    try:
        server.start()
    except LiveServerError as error:
        _log.error("%s", error)
        return EXIT_CANNOT_LISTEN
    director = LiveDirector(server.send)
    session = LiveSession(director, seed=options.seed)
    director.start()
    host, port = server.address
    _log.info(
        "En écoute sur %s:%d : lance Unity (Play). Ctrl-C pour arrêter.", host, port
    )
    try:
        played = session.run(options.generations)
        _log.info("%d générations jouées.", played)
    except KeyboardInterrupt:
        _log.info("Arrêt demandé.")
    finally:
        director.stop()
        server.stop()
    return EXIT_OK


def _parse(arguments: Sequence[str]) -> argparse.Namespace:
    """Lit les options de la commande."""
    parser = argparse.ArgumentParser(
        prog="python -m logicai.live",
        description="Lance l'IA évolutionnaire et l'envoie en direct à Unity.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="port local (défaut : %(default)s)",
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="graine du hasard (défaut : %(default)s)"
    )
    parser.add_argument(
        "--generations",
        type=int,
        default=None,
        help="nombre de générations (défaut : sans fin, jusqu'à Ctrl-C)",
    )
    return parser.parse_args(arguments)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
