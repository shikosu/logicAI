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
"""

from dataclasses import dataclass

from logicai.errors import InvalidStageSettingsError
from logicai.evolution import Evolution, GenerationReport
from logicai.mutations import MutationRules

# Valeur de départ de N (à régler par essais).
DEFAULT_STALLED_GENERATIONS = 400


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
    ) -> None:
        """Prend la main sur l'évolution : elle repart du premier palier.

        ``stalled_generations`` est N : le nombre de générations sans nouveauté qui
        débloque le palier suivant.
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

    def step(self) -> StageReport:
        """Joue une génération, puis monte d'un palier si le critère est atteint."""
        played = self.stage
        report = self._evolution.step()
        self._quiet = 0 if report.new_count > 0 else self._quiet + 1
        advanced_to = None
        if self._quiet >= self._stalled and not self.is_last_stage:
            advanced_to = self._advance()
        return StageReport(played.number, report, advanced_to)

    def _advance(self) -> int:
        """Monte au palier suivant : nouveaux réglages, compte remis à zéro."""
        self._index += 1
        self._quiet = 0
        self._evolution.rules = self.stage.rules
        return self.stage.number
