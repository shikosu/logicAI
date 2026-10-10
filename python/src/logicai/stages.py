"""Paliers : la progression NAND, portes classiques, circuits plus complexes.

Le cahier (« Les paliers ») fait grandir le problème avec le nombre d'entrées autorisé :
palier 1 = 1 entrée, palier 2 = 2 entrées, palier 3 = 3 entrées, toujours avec une seule
sortie. Les paliers 4 et 5 (plusieurs sorties, horloge) viennent à la phase 6.

« L'IA débloque un palier quand elle ne trouve plus rien de nouveau dans le précédent. »
Critère retenu (décision de Téo) : **aucune nouveauté pendant N générations d'affilée**.
Une nouveauté qui arrive remet le compte à zéro ; un record n'est pas une nouveauté.
N est un réglage, dont la valeur de départ vient d'essais. Le compte repart de zéro à
l'arrivée dans un nouveau palier. Le dernier palier est gardé : il n'y a pas de suivant.

Un palier plus grand contient les précédents (le circuit vide a une entrée et le
palier 3 permet « jusqu'à » 3 entrées) : passer au palier suivant élargit la recherche
sans rien interdire.

Les paliers 1 à 3 imposent une sortie et aucune boucle (décisions Q4 et Q5) : ces
réglages sont ceux de ``MutationRules``.

**Palier 4 et défis.** Dès le palier 4 (4 entrées, plusieurs sorties), chaque paire de
fonctions déjà connues est une « nouveauté » : le demi-additionneur devient une
aiguille dans des dizaines de milliers de paires (mesuré : 0 graine sur 8 par le
parcours normal). Avec ``ChallengeSettings``, le parcours fixe un **défi** à l'arrivée
dans ce palier (voir ``challenge``), en change quand il est atteint ou quand la
proximité ne progresse plus pendant ``patience`` générations.
"""

import random
from dataclasses import dataclass

from logicai.challenge import choose_challenge
from logicai.errors import InvalidChallengeError, InvalidStageSettingsError
from logicai.evolution import Evolution, GenerationReport
from logicai.mutations import MutationRules

# Valeur de départ de N (à régler par essais).
DEFAULT_STALLED_GENERATIONS = 400

# Palier 4 du cahier : « 4 entrées et plusieurs sorties ». Le cahier ne donne pas le
# nombre de sorties : 3 couvre ses exemples à 4 entrées (additionneur 2 bits,
# comparateur). Valeur de départ, à régler par essais.
STAGE_4_MAX_INPUTS = 4
STAGE_4_MAX_OUTPUTS = 3

# Défis : générations sans progrès de la proximité avant d'abandonner un défi (valeur de
# départ, à régler par essais), et palier où les défis commencent.
DEFAULT_CHALLENGE_PATIENCE = 300
FIRST_CHALLENGE_STAGE = 4


@dataclass(frozen=True)
class Stage:
    """Un palier : son numéro, ses maximums d'entrées et de sorties, ses boucles.

    Les paliers 1 à 3 n'ont pas de boucle. Un palier qui en permet (``allow_loops``)
    laisse l'IA construire des circuits à mémoire.
    """

    number: int
    max_inputs: int
    max_outputs: int
    allow_loops: bool = False

    @property
    def rules(self) -> MutationRules:
        """Renvoie les réglages de mutation de ce palier."""
        return MutationRules(self.max_inputs, self.max_outputs, self.allow_loops)


# Cahier, « Les paliers » : 1, 2 et 3 entrées, une seule sortie.
STAGES = (Stage(1, 1, 1), Stage(2, 2, 1), Stage(3, 3, 1))

# Palier 4, à jouer avec les défis (voir l'en-tête). ``STAGES`` ne change pas.
STAGE_4 = Stage(4, STAGE_4_MAX_INPUTS, STAGE_4_MAX_OUTPUTS)
STAGES_1_TO_4 = (*STAGES, STAGE_4)


@dataclass(frozen=True)
class ChallengeSettings:
    """Réglages des défis : graine du choix, patience, premier palier concerné.

    ``patience`` : nombre de générations sans progrès de la proximité après lesquelles
    un défi est abandonné. ``first_stage`` : numéro du premier palier où l'on fixe des
    défis.
    """

    seed: int = 0
    patience: int = DEFAULT_CHALLENGE_PATIENCE
    first_stage: int = FIRST_CHALLENGE_STAGE

    def __post_init__(self) -> None:
        """Refuse une patience qui ne laisse aucune génération à l'IA."""
        if self.patience < 1:
            raise InvalidChallengeError(
                "La patience doit valoir au moins 1 génération "
                f"(reçu : {self.patience})."
            )


@dataclass(frozen=True)
class StageReport:
    """Une génération jouée, avec le palier où elle a eu lieu.

    ``advanced_to`` donne le numéro du nouveau palier si cette génération vient de
    débloquer le suivant (elle a, elle, été jouée dans ``stage``), sinon ``None``.
    """

    stage: int
    generation: GenerationReport
    advanced_to: int | None


class Curriculum:
    """Mène une ``Evolution`` palier après palier."""

    def __init__(
        self,
        evolution: Evolution,
        stalled_generations: int = DEFAULT_STALLED_GENERATIONS,
        stages: tuple[Stage, ...] = STAGES,
        challenges: ChallengeSettings | None = None,
    ) -> None:
        """Prend la main sur l'évolution : elle repart du premier palier.

        ``stalled_generations`` est N : le nombre de générations sans nouveauté qui
        débloque le palier suivant. Avec ``challenges``, le parcours fixe des défis à
        partir du palier ``challenges.first_stage``.
        """
        if stalled_generations < 1:
            raise InvalidStageSettingsError(
                "N, le nombre de générations sans nouveauté, doit valoir au moins 1 "
                f"(reçu : {stalled_generations})."
            )
        if not stages:
            raise InvalidStageSettingsError("Il faut au moins un palier.")
        self._evolution = evolution
        self._stalled = stalled_generations
        self._stages = stages
        self._index = 0
        self._quiet = 0
        evolution.rules = stages[0].rules
        self._challenges = challenges
        self._challenge_rng = random.Random(challenges.seed if challenges else 0)
        self._reached = 0
        self._best_closeness: int | None = None
        self._stale = 0

    @property
    def stage(self) -> Stage:
        """Renvoie le palier en cours."""
        return self._stages[self._index]

    @property
    def quiet_generations(self) -> int:
        """Renvoie le nombre de générations d'affilée sans nouveauté, dans ce palier."""
        return self._quiet

    @property
    def is_last_stage(self) -> bool:
        """Dit si le palier en cours est le dernier."""
        return self._index == len(self._stages) - 1

    @property
    def reached_challenges(self) -> int:
        """Renvoie le nombre de défis atteints depuis le début."""
        return self._reached

    def step(self) -> StageReport:
        """Joue une génération, puis monte d'un palier si le critère est atteint."""
        played = self.stage
        report = self._evolution.step()
        self._quiet = 0 if report.new_count > 0 else self._quiet + 1
        advanced_to = None
        if self._quiet >= self._stalled and not self.is_last_stage:
            advanced_to = self._advance()
        if self._challenges is not None:
            self._manage_challenge(self._challenges)
        return StageReport(played.number, report, advanced_to)

    def _manage_challenge(self, settings: ChallengeSettings) -> None:
        """Gère les défis : en choisit un dans les paliers concernés, puis en change.

        Un défi est remplacé quand sa cible est devenue un composant, ou quand la
        meilleure proximité n'a pas progressé depuis ``settings.patience`` générations.
        """
        if self.stage.number < settings.first_stage:
            return
        evolution = self._evolution
        current = evolution.challenge
        if current is not None and evolution.library.has_signature(current.signature):
            self._reached += 1
            current = None
        elif current is not None and self._is_stalled(settings.patience):
            current = None
        if current is None:
            evolution.challenge = choose_challenge(
                evolution.library,
                self._challenge_rng,
                self.stage.max_inputs,
                self.stage.max_outputs,
            )
            self._best_closeness, self._stale = None, 0

    def _is_stalled(self, patience: int) -> bool:
        """Dit si la proximité n'a pas progressé depuis ``patience`` générations."""
        best = self._evolution.best_closeness
        if best is not None and (
            self._best_closeness is None or best > self._best_closeness
        ):
            self._best_closeness, self._stale = best, 0
            return False
        self._stale += 1
        return self._stale >= patience

    def _advance(self) -> int:
        """Monte au palier suivant : nouveaux réglages, compte remis à zéro."""
        self._index += 1
        self._quiet = 0
        self._evolution.rules = self.stage.rules
        return self.stage.number
