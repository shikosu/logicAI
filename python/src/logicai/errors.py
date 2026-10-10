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
