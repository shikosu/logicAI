"""Variante « défis » : le système se fixe lui-même une table à construire.

Cahier, « La variante « défis », pour plus tard » : un module choisit une table de
vérité absente de la bibliothèque, et l'IA essaie de la construire. Ce n'est pas Téo qui
donne la table : c'est le système qui se fixe un défi. Cette variante est faite pour les
paliers où il y a trop de fonctions possibles pour les découvrir par hasard.

Décisions de Téo (10 octobre 2026), après une mesure (demi-additionneur trouvé par 1
graine sur 8 sans défi, 7 sur 8 avec) :

- **le système choisit la cible au hasard** parmi les tables absentes de la bibliothèque
  et acceptées par les filtres (une table refusée ne pourrait jamais devenir un
  composant) ;
- la **proximité** sert uniquement à **choisir les parents** : ``Challenge.closeness``
  compte les bits de la table égaux à ceux de la cible, sorties dans l'ordre ; la
  formule de récompense du cahier ne change pas : atteindre la cible est une nouveauté
  comme une autre.

**Petites cibles d'abord** (décision de Téo, après une mesure : les cibles tirées
uniformément jusqu'à 4 entrées et 3 sorties sont presque toujours trop dures, 3 défis
atteints sur environ 40). La taille des cibles dépend d'un « niveau » : il part de
2 entrées et 2 sorties (le demi-additionneur en fait partie), et grandit d'un cran à
chaque défi atteint, une entrée puis une sortie en alternance, jusqu'aux limites du
palier. Le choix reste au hasard et fait par le système.

La proximité se mesure sur l'ordre d'origine des entrées : un circuit qui construit la
cible avec ses entrées échangées est reconnu à l'arrivée (la signature est canonique),
mais pas par la proximité.
"""

import random
from collections.abc import Mapping
from dataclasses import dataclass

from logicai.behavior import TruthTable, full_mask, truth_table
from logicai.circuit import Circuit
from logicai.errors import InvalidChallengeError
from logicai.filters import rejections_of_table
from logicai.flatten import flatten
from logicai.library import Library
from logicai.signature import Signature, canonical_form
from logicai.simulation import Status

# Une cible a au moins 2 entrées : à 1 entrée, il n'y a que NOT à trouver.
MIN_CHALLENGE_INPUTS = 2

# Nombre de tables tirées avant de renoncer à choisir un défi (valeur de départ).
MAX_DRAWS = 1000

# Taille des premières cibles : 2 entrées et 2 sorties.
FIRST_OUTPUTS = 2


@dataclass(frozen=True)
class Challenge:
    """La table à construire : un entier par sortie, dans l'ordre des sorties.

    Le bit k de chaque entier est la sortie pour la combinaison k (voir ``behavior``).
    """

    input_count: int
    outputs: tuple[int, ...]

    def __post_init__(self) -> None:
        """Refuse un défi sans entrée, sans sortie, ou dont une table ne tient pas."""
        if self.input_count < 1:
            raise InvalidChallengeError(
                f"Un défi a au moins 1 entrée (reçu : {self.input_count})."
            )
        if not self.outputs:
            raise InvalidChallengeError("Un défi a au moins 1 sortie.")
        full = full_mask(self.input_count)
        for value in self.outputs:
            if not 0 <= value <= full:
                raise InvalidChallengeError(
                    f"La table {value} ne tient pas dans {1 << self.input_count} bits "
                    f"({self.input_count} entrées)."
                )

    @property
    def max_closeness(self) -> int:
        """Renvoie la proximité d'un circuit qui a exactement la table du défi."""
        return len(self.outputs) << self.input_count

    @property
    def signature(self) -> Signature:
        """Renvoie la signature canonique de la cible (celle qu'aura son composant)."""
        table = TruthTable(Status.STABLE, self.outputs)
        return canonical_form(table, self.input_count).signature

    def closeness(
        self, circuit: Circuit, definitions: Mapping[str, Circuit]
    ) -> int | None:
        """Compte les bits de table égaux à ceux de la cible ; ``None`` si inutilisable.

        Un circuit est inutilisable s'il n'a pas le bon nombre d'entrées et de sorties,
        s'il est instable, ou s'il a une CLK (sa table n'est pas définie).
        """
        if (len(circuit.inputs()), len(circuit.outputs())) != (
            self.input_count,
            len(self.outputs),
        ):
            return None
        flat = flatten(circuit, definitions)
        if flat.clocks():
            return None
        table = truth_table(flat)
        if table.status is not Status.STABLE:
            return None
        bits = 1 << self.input_count
        return sum(
            bits - (found ^ wanted).bit_count()
            for found, wanted in zip(table.outputs, self.outputs, strict=True)
        )


def challenge_size(level: int, max_inputs: int, max_outputs: int) -> tuple[int, int]:
    """Renvoie les entrées et sorties au plus d'une cible, au niveau donné.

    Le niveau 0 donne 2 entrées et 2 sorties ; chaque niveau ajoute une entrée, puis
    une sortie, en alternance (3 et 2, puis 3 et 3, puis 4 et 3...), sans dépasser les
    limites du palier.
    """
    inputs = MIN_CHALLENGE_INPUTS + (level + 1) // 2
    outputs = FIRST_OUTPUTS + level // 2
    return min(inputs, max_inputs), min(outputs, max_outputs)


def choose_challenge(
    library: Library,
    rng: random.Random,
    max_inputs: int,
    max_outputs: int,
    min_inputs: int = MIN_CHALLENGE_INPUTS,
) -> Challenge | None:
    """Tire un défi au hasard : une table absente de la bibliothèque et non filtrée.

    Le nombre d'entrées est tiré entre ``min_inputs`` et ``max_inputs``, le nombre de
    sorties entre 1 et ``max_outputs``, puis chaque sortie est une table au hasard.
    Renvoie ``None`` si les bornes ne permettent rien, ou si ``MAX_DRAWS`` tirages
    n'ont rien donné. Tout le hasard vient de ``rng``.
    """
    if max_inputs < min_inputs or max_outputs < 1:
        return None
    for _ in range(MAX_DRAWS):
        input_count = rng.randint(min_inputs, max_inputs)
        output_count = rng.randint(1, max_outputs)
        outputs = tuple(rng.getrandbits(1 << input_count) for _ in range(output_count))
        challenge = Challenge(input_count, outputs)
        if _is_reachable(challenge, library):
            return challenge
    return None


def _is_reachable(challenge: Challenge, library: Library) -> bool:
    """Dit si la cible peut devenir un composant (filtres OK, signature libre)."""
    table = TruthTable(Status.STABLE, challenge.outputs)
    if rejections_of_table(table, challenge.input_count):
        return False
    return not library.has_signature(challenge.signature)
