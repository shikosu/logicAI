"""Exceptions du paquet logicai.

Chaque refus a sa propre classe, pour que l'appelant sache pourquoi une action
a été refusée. Une action refusée laisse toujours le circuit inchangé.
"""


class CircuitError(Exception):
    """Base de tous les refus d'une opération sur un circuit."""


class UnknownNodeError(CircuitError):
    """Le nœud demandé n'existe pas dans le circuit."""


class UnknownPinError(CircuitError):
    """Le nœud existe, mais il n'a aucune broche à cet index."""


class WrongPinKindError(CircuitError):
    """La broche est donnée comme source alors que c'est un puits, ou l'inverse."""


class SinkAlreadyConnectedError(CircuitError):
    """Le puits reçoit déjà un câble : un puits n'en accepte qu'un seul."""


class SinkNotConnectedError(CircuitError):
    """Le puits n'a pas de câble, il n'y a donc rien à déconnecter."""


class InvalidNodeError(CircuitError):
    """Le nœud demandé n'est pas valide (type, nombre de broches, référence...)."""


class InvalidInputOrderError(CircuitError):
    """L'ordre donné pour les entrées n'est pas une permutation des entrées."""


class FlattenError(Exception):
    """Base des refus de l'aplatissement d'un circuit qui contient des composants."""


class UnknownComponentError(FlattenError):
    """Le circuit pose un composant dont la définition est introuvable."""


class ComponentPinMismatchError(FlattenError):
    """Le nombre de broches du nœud ne correspond pas à la définition du composant."""


class ComponentCycleError(FlattenError):
    """Un composant se contient lui-même, directement ou par d'autres composants."""


class WireLoopError(FlattenError):
    """Une boucle de fils sans aucune NAND : sa valeur n'est pas définie."""


class ComponentNestingError(FlattenError):
    """Des composants sont imbriqués trop profondément pour la pile de Python."""


class SimulationError(Exception):
    """La simulation ne peut pas tourner avec ces données (entrées, état, masque)."""


class SignatureError(Exception):
    """La signature ne peut pas être calculée avec ces données."""


class SnapshotError(Exception):
    """Les valeurs d'un circuit ne peuvent pas être relevées avec ces données."""


class LibraryError(Exception):
    """Base des refus de la bibliothèque de composants."""


class InvalidLimitsError(LibraryError):
    """Les limites demandées pour la bibliothèque ne sont pas valides."""


class NoOutputError(LibraryError):
    """Un circuit sans sortie n'a rien d'observable : pas de composant possible."""


class ComponentTooLargeError(LibraryError):
    """Le circuit a plus d'entrées ou de sorties que la bibliothèque ne l'autorise."""


class UnstableCircuitError(LibraryError):
    """Le circuit est instable : sa signature n'est pas définie (cahier : rejeté)."""


class UnknownComponentNameError(LibraryError):
    """Aucun composant de la bibliothèque ne porte ce nom."""


class LibraryFormatError(LibraryError):
    """Un fichier de bibliothèque est illisible, incomplet ou incohérent."""


class InvalidMutationRulesError(Exception):
    """Les réglages demandés pour les mutations ne sont pas valides."""


class InvalidRewardSettingsError(Exception):
    """Les réglages demandés pour la récompense ne sont pas valides."""


class InvalidEvolutionSettingsError(Exception):
    """Les réglages demandés pour la boucle d'évolution ne sont pas valides."""


class InvalidStageSettingsError(Exception):
    """Les réglages demandés pour les paliers ne sont pas valides."""
