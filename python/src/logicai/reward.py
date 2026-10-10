"""Récompense d'un essai : le chemin « filtres, signature connue, moins de NAND ».

Un essai suit le chemin du cahier (« Système de récompense ») :

::

    circuit proposé
      -> filtres anti-triche ? refusé : 0 point
      -> signature jamais vue ?  oui : nouveauté (le circuit devient un composant)
      -> signature connue, moins de NAND ? oui : record (il remplace l'ancien)
      -> sinon : aucune récompense

La formule du cahier est ``R = R_nouveauté + R_record + R_mémoire + R_réutilisation
- k · N_NAND - P_filtres``. Décisions de Téo pour la phase 4 :

- un circuit refusé, ou ni nouveau ni plus petit, vaut **0** ; la pénalité de taille
  ``k · N_NAND`` ne s'applique que sur une nouveauté ou un record ;
- la réutilisation est un **bonus ajouté à la nouvelle découverte**, avec un compteur de
  réutilisations par composant ; il ne change pas les choix de l'IA (phase 4) ;
- le terme mémoire vaut 0 (il arrive avec la phase 6).

Interprétations (à confirmer par Téo), pour ce que le cahier ne précise pas :

- le bonus de réutilisation ne vaut que pour une **nouveauté** (« une nouvelle
  découverte »), pas pour un record ;
- il se compte **par composant distinct** posé dans le circuit gardé : poser trois fois
  NOT compte une réutilisation de NOT, pas trois ;
- on compte les composants du circuit **après nettoyage** : un composant posé sans
  servir à rien ne rapporte rien ;
- ``N_NAND`` est le nombre de NAND du circuit gardé, après aplatissement (le coût).

Les valeurs par défaut des réglages ne sont que des valeurs de départ, de l'ordre de
grandeur du cahier (grand, moyen, petit) : elles seront réglées par essais.
"""

from dataclasses import dataclass
from enum import Enum, auto

from logicai.circuit import Circuit, NodeKind
from logicai.cleanup import remove_useless_nodes
from logicai.errors import InvalidRewardSettingsError
from logicai.filters import Rejection, find_rejections
from logicai.library import Library, Outcome

# Valeurs de départ (à régler par essais) : nouveauté grande, record moyen,
# réutilisation et taille petites.
DEFAULT_NOVELTY_REWARD = 100.0
DEFAULT_RECORD_REWARD = 30.0
DEFAULT_REUSE_BONUS = 5.0
DEFAULT_NAND_COST = 1.0

# Récompense d'un essai refusé, ou ni nouveau ni plus petit.
NO_REWARD = 0.0


@dataclass(frozen=True)
class RewardSettings:
    """Les poids de la formule : nouveauté, record, réutilisation, et k par NAND."""

    novelty: float = DEFAULT_NOVELTY_REWARD
    record: float = DEFAULT_RECORD_REWARD
    reuse: float = DEFAULT_REUSE_BONUS
    nand_cost: float = DEFAULT_NAND_COST

    def __post_init__(self) -> None:
        """Refuse un poids négatif."""
        weights = {
            "nouveauté": self.novelty,
            "record": self.record,
            "réutilisation": self.reuse,
            "coût d'une NAND": self.nand_cost,
        }
        for label, value in weights.items():
            if value < 0:
                raise InvalidRewardSettingsError(
                    f"Le poids « {label} » ne peut pas être négatif (reçu : {value})."
                )


class TrialKind(Enum):
    """L'issue d'un essai (les quatre issues du schéma du cahier)."""

    REJECTED = auto()  # filtres, ou circuit sans sortie : 0 point
    NEW = auto()  # signature jamais vue : nouveauté
    RECORD = auto()  # signature connue, moins de NAND : record
    NOTHING = auto()  # signature connue, pas moins de NAND : aucune récompense


@dataclass(frozen=True)
class TrialResult:
    """Ce qu'un essai a donné.

    ``name`` est le composant créé ou amélioré (``None`` si l'essai est refusé ou
    sans effet sur la bibliothèque : pour ``NOTHING``, c'est le composant déjà connu).
    ``rejections`` donne les motifs des filtres ; avec ``REJECTED`` et aucun motif,
    c'est un circuit sans sortie. ``reused`` liste les composants réutilisés (une
    nouveauté seulement).
    """

    kind: TrialKind
    reward: float
    name: str | None
    rejections: tuple[Rejection, ...] = ()
    reused: tuple[str, ...] = ()


class RewardTracker:
    """Évalue les essais d'une IA et compte les réutilisations de composants."""

    def __init__(
        self, library: Library, settings: RewardSettings | None = None
    ) -> None:
        """Crée un évaluateur lié à une bibliothèque (qu'il fera grandir)."""
        self._library = library
        self._settings = settings if settings is not None else RewardSettings()
        self._reuse_counts: dict[str, int] = {}

    def evaluate(self, circuit: Circuit) -> TrialResult:
        """Juge un circuit, l'enregistre si c'est une découverte, et donne son score.

        Le circuit donné n'est pas modifié. Seule la bibliothèque change, et seulement
        pour une nouveauté ou un record. Un circuit invalide (composant inconnu...) ou
        plus grand que les limites de la bibliothèque lève l'erreur correspondante :
        ce n'est pas un essai « inutile », c'est une erreur de réglage.
        """
        kept = remove_useless_nodes(circuit)
        rejections = find_rejections(kept, self._library.definitions())
        if rejections or not kept.outputs():
            return TrialResult(TrialKind.REJECTED, NO_REWARD, None, rejections)
        registration = self._library.register(circuit)
        if registration.outcome is Outcome.NEW:
            return self._new_discovery(registration.name)
        if registration.outcome is Outcome.RECORD:
            reward = self._settings.record - self._size_penalty(registration.name)
            return TrialResult(TrialKind.RECORD, reward, registration.name)
        return TrialResult(TrialKind.NOTHING, NO_REWARD, registration.name)

    def reuse_count(self, name: str) -> int:
        """Renvoie combien de nouvelles découvertes ont réutilisé ce composant."""
        return self._reuse_counts.get(name, 0)

    def _new_discovery(self, name: str) -> TrialResult:
        """Renvoie le résultat d'une nouveauté et compte les composants réutilisés."""
        reused = _distinct_components(self._library.component(name).circuit)
        for used in reused:
            self._reuse_counts[used] = self._reuse_counts.get(used, 0) + 1
        reward = (
            self._settings.novelty
            + self._settings.reuse * len(reused)
            - self._size_penalty(name)
        )
        return TrialResult(TrialKind.NEW, reward, name, reused=reused)

    def _size_penalty(self, name: str) -> float:
        """Renvoie ``k · N_NAND`` pour un composant (N_NAND = son coût aplati)."""
        return self._settings.nand_cost * self._library.cost(name)


def _distinct_components(circuit: Circuit) -> tuple[str, ...]:
    """Renvoie les composants posés dans le circuit, chacun une fois, dans l'ordre."""
    refs = (
        node.component_ref
        for node in circuit.nodes()
        if node.kind is NodeKind.COMPONENT and node.component_ref is not None
    )
    return tuple(dict.fromkeys(refs))
