"""Boucle d'évolution : proposer des circuits, les juger, garder les meilleurs.

Le cahier (« IA 1 : l'algorithme évolutionnaire ») décrit une population de circuits :
on garde les meilleurs, on les modifie au hasard, on recommence. Une **génération**
fait, pour chaque enfant :

::

    choisir un parent  ->  lui appliquer quelques mutations  ->  l'évaluer (récompense)

Qui sont les parents ? (décision Q1 de Téo) Comme la récompense n'est donnée qu'une fois
par signature, un circuit déjà trouvé ne rapporte plus rien ; on ne peut donc pas
choisir les parents d'après leur score. On prend :

- un **circuit vide** (une entrée, une sortie, rien d'autre), toujours disponible, pour
  repartir de zéro ;
- le **plus petit circuit de chaque signature trouvée** : c'est exactement la définition
  de chaque composant de la bibliothèque (un record la remplace par une version plus
  petite) ; c'est l'idée de MAP-Elites, citée par le cahier ;
- **quelques circuits récents** qui ont passé les filtres (même sans récompense),
  nettoyés. Ils servent de marches pour aller plus loin.

Un enfant reçoit **plusieurs mutations d'affilée** : une mutation seule donne presque
toujours un circuit refusé (une NAND non câblée ne fait rien).

Tout le hasard vient d'un générateur créé avec la graine donnée : mêmes réglages et même
graine, même déroulement. Les parents ne sont jamais modifiés (les mutations travaillent
sur des copies).

Le nombre d'enfants, de mutations et de circuits récents sont des réglages dont les
valeurs de départ seront réglées par essais.

**Défi** (variante du cahier, voir ``challenge``). Quand un défi est fixé, l'IA garde
une petite archive des circuits les plus proches de la table cible, et la moitié des
enfants ont un parent tiré dans cette archive. La récompense ne change pas. Sans défi,
aucun tirage de plus n'est fait : le déroulement est exactement celui d'avant.
"""

import random
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from logicai.challenge import Challenge
from logicai.circuit import Circuit, NodeKind
from logicai.cleanup import remove_useless_nodes
from logicai.errors import InvalidEvolutionSettingsError
from logicai.library import Library
from logicai.mutations import MutationRules, mutate
from logicai.reward import RewardSettings, RewardTracker, TrialKind, TrialResult

# Valeurs de départ (à régler par essais).
DEFAULT_CHILDREN_PER_GENERATION = 50
DEFAULT_MIN_MUTATIONS = 1
DEFAULT_MAX_MUTATIONS = 12
DEFAULT_RECENT_SIZE = 100
# Défi (valeurs de départ, mesurées sur un prototype, à régler par essais) : part des
# enfants dont le parent vient de l'archive, et taille de l'archive.
CHALLENGE_PARENT_SHARE = 0.5
CHALLENGE_ARCHIVE_SIZE = 50


@dataclass(frozen=True)
class EvolutionSettings:
    """Réglages d'une génération.

    ``children_per_generation`` : nombre d'enfants essayés par génération.
    ``min_mutations`` et ``max_mutations`` : chaque enfant reçoit un nombre de
    mutations tiré entre les deux (bornes comprises).
    ``recent_size`` : nombre de circuits récents gardés comme parents (0 = aucun).
    """

    children_per_generation: int = DEFAULT_CHILDREN_PER_GENERATION
    min_mutations: int = DEFAULT_MIN_MUTATIONS
    max_mutations: int = DEFAULT_MAX_MUTATIONS
    recent_size: int = DEFAULT_RECENT_SIZE

    def __post_init__(self) -> None:
        """Refuse des réglages qui n'ont pas de sens."""
        if self.children_per_generation < 1:
            raise InvalidEvolutionSettingsError(
                "Une génération doit essayer au moins 1 enfant "
                f"(reçu : {self.children_per_generation})."
            )
        if self.min_mutations < 1 or self.max_mutations < self.min_mutations:
            raise InvalidEvolutionSettingsError(
                "Il faut 1 <= min_mutations <= max_mutations "
                f"(reçu : {self.min_mutations} et {self.max_mutations})."
            )
        if self.recent_size < 0:
            raise InvalidEvolutionSettingsError(
                f"Le nombre de circuits récents ne peut pas être négatif "
                f"(reçu : {self.recent_size})."
            )


@dataclass(frozen=True)
class GenerationReport:
    """Ce qu'une génération a trouvé.

    ``discoveries`` liste, dans l'ordre, les essais qui ont donné une nouveauté ou un
    record. ``total_reward`` est la somme des récompenses de tous les essais.
    """

    generation: int
    trials: int
    discoveries: tuple[TrialResult, ...]
    total_reward: float

    @property
    def new_count(self) -> int:
        """Renvoie le nombre de nouveautés (les records ne comptent pas)."""
        return sum(1 for d in self.discoveries if d.kind is TrialKind.NEW)


class Evolution:
    """L'IA évolutionnaire : fait grandir une bibliothèque, génération après génération.

    ``rules`` (réglages du palier) peut être changée entre deux générations, par
    exemple pour passer au palier suivant.

    ``on_trial``, facultatif, est appelé après chaque essai avec l'enfant et son
    résultat (par exemple pour l'afficher). Il doit être court : il s'exécute dans la
    boucle d'entraînement. Une erreur qu'il lève n'est pas cachée.
    """

    def __init__(
        self,
        library: Library,
        rules: MutationRules,
        settings: EvolutionSettings | None = None,
        reward_settings: RewardSettings | None = None,
        seed: int = 0,
        on_trial: Callable[[Circuit, TrialResult], None] | None = None,
    ) -> None:
        """Crée l'IA : sa bibliothèque (qu'elle fait grandir), son palier, sa graine."""
        self._library = library
        self.rules = rules
        self._settings = settings if settings is not None else EvolutionSettings()
        self._tracker = RewardTracker(library, reward_settings)
        self._rng = random.Random(seed)
        self._on_trial = on_trial
        self._recent: deque[Circuit] = deque(maxlen=self._settings.recent_size)
        self._generation = 0
        self._challenge: Challenge | None = None
        # Les circuits les plus proches du défi : (proximité, circuit), du plus proche.
        self._close: list[tuple[int, Circuit]] = []

    @property
    def tracker(self) -> RewardTracker:
        """Renvoie l'évaluateur (pour lire les compteurs de réutilisation)."""
        return self._tracker

    @property
    def library(self) -> Library:
        """Renvoie la bibliothèque que l'IA fait grandir."""
        return self._library

    @property
    def challenge(self) -> Challenge | None:
        """Renvoie le défi en cours, ou ``None``."""
        return self._challenge

    @challenge.setter
    def challenge(self, challenge: Challenge | None) -> None:
        """Remplace le défi (ou l'enlève) : l'archive repart de zéro."""
        self._challenge = challenge
        self._close = []

    @property
    def best_closeness(self) -> int | None:
        """Renvoie la meilleure proximité trouvée pour le défi, ou ``None``."""
        return self._close[0][0] if self._close else None

    def parents(self) -> tuple[Circuit, ...]:
        """Renvoie les circuits qui peuvent être choisis comme parents.

        Dans l'ordre : le circuit vide, le plus petit circuit de chaque signature
        trouvée (les composants), puis les circuits récents, du plus ancien au plus
        récent. Ces circuits ne doivent pas être modifiés.
        """
        definitions = self._library.definitions()
        found = tuple(definitions[name] for name in self._library.names())
        return (_blank_circuit(), *found, *self._recent)

    def propose_child(self) -> Circuit:
        """Choisit un parent au hasard et lui applique plusieurs mutations d'affilée."""
        child = self._choose_parent()
        count = self._rng.randint(
            self._settings.min_mutations, self._settings.max_mutations
        )
        for _ in range(count):
            child = mutate(child, self._rng, self.rules, self._library).circuit
        return child

    def step(self) -> GenerationReport:
        """Fait une génération : essaie chaque enfant et rend le rapport."""
        self._generation += 1
        results = [
            self._try_child() for _ in range(self._settings.children_per_generation)
        ]
        discoveries = tuple(
            r for r in results if r.kind in (TrialKind.NEW, TrialKind.RECORD)
        )
        return GenerationReport(
            generation=self._generation,
            trials=len(results),
            discoveries=discoveries,
            total_reward=sum(r.reward for r in results),
        )

    def _choose_parent(self) -> Circuit:
        """Tire un parent : dans l'archive du défi une fois sur deux, ou comme avant."""
        if self._close and self._rng.random() < CHALLENGE_PARENT_SHARE:
            return self._rng.choice(self._close)[1]
        return self._rng.choice(self.parents())

    def _try_child(self) -> TrialResult:
        """Propose un enfant, l'évalue, et le garde comme récent s'il est accepté."""
        child = self.propose_child()
        result = self._tracker.evaluate(child)
        if result.kind is not TrialKind.REJECTED:
            self._recent.append(remove_useless_nodes(child))
        if self._challenge is not None:
            self._remember_if_close(remove_useless_nodes(child), self._challenge)
        if self._on_trial is not None:
            self._on_trial(child, result)
        return result

    def _remember_if_close(self, kept: Circuit, challenge: Challenge) -> None:
        """Range le circuit dans l'archive s'il a la forme du défi (même refusé)."""
        closeness = challenge.closeness(kept, self._library.definitions())
        if closeness is None:
            return
        self._close.append((closeness, kept))
        self._close.sort(key=lambda item: (-item[0], item[1].nand_count()))
        del self._close[CHALLENGE_ARCHIVE_SIZE:]


def _blank_circuit() -> Circuit:
    """Crée le circuit vide de départ : une entrée, une sortie, aucun câble."""
    circuit = Circuit()
    circuit.add_node(NodeKind.INPUT)
    circuit.add_node(NodeKind.OUTPUT)
    return circuit
