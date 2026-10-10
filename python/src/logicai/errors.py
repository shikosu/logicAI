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


class SimulationError(Exception):
    """La simulation ne peut pas tourner avec ces données (entrées, état, masque)."""
