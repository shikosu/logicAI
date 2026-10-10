"""Circuits à mémoire : batterie de séquences, mémoire et signature séquentielle.

Cahier, « Circuits séquentiels » : avec une boucle, la sortie peut dépendre du passé,
donc la table de vérité ne suffit plus. Le testeur envoie une **batterie fixe de
séquences d'entrées**, la même pour tous les circuits ; la signature est la suite des
sorties lues pendant ces séquences. Chaque séquence part du même état : toutes les
sorties à 0.

Le cahier ne dit pas quelles séquences. Décision de Téo (10 octobre 2026) : **un seul
changement à la fois**. Une séquence (une « marche ») part de toutes les entrées à 0,
puis change **une seule entrée par pas**, pendant ``BATTERY_LENGTH`` pas. La batterie
contient toutes les marches possibles. Pourquoi : si deux entrées passent à 1 en même
temps, une bascule SR en NAND oscille (métastabilité simulée, cahier, « Piège à
connaître »). Une batterie qui ferait ces changements simultanés rejetterait toute
bascule ; ici, elle passe. Le cahier reste intact : toute oscillation dans la
batterie rejette le circuit.

Un circuit sans boucle n'a pas de mémoire : sa batterie n'est pas jouée (``None``). Les
circuits avec CLK ne sont pas encore pris en charge : le protocole de l'horloge reste à
fixer, et la simulation refuse de les jouer sans valeur d'horloge.

**Signature séquentielle.** C'est la réponse du circuit à toute la batterie. Comme pour
les circuits combinatoires, deux circuits dont les entrées sont seulement échangées ne
font qu'une seule découverte (cahier, « Composants équivalents ») : on garde la plus
petite réponse parmi les ordres d'entrées essayés. Les sorties ne sont jamais permutées.
"""

import itertools
from collections.abc import Mapping
from dataclasses import dataclass

from logicai.behavior import has_memory, run_sequence
from logicai.circuit import Circuit
from logicai.errors import SignatureError, SimulationError
from logicai.simulation import Status

# Nombre de changements d'entrée par marche (réglable ; 4 suffit à une bascule SR : elle
# atteint (1, 1) deux fois, avec deux sorties différentes).
BATTERY_LENGTH = 4

# Au-delà, on n'essaie pas tous les ordres d'entrées (n! ordres) : la signature garde
# alors l'ordre d'origine, comme pour les tables de vérité (5! = 120 ordres au plus).
MAX_CANONICAL_INPUTS = 5

# Une marche : les indices des entrées changées, dans l'ordre. Les sorties de chaque pas
# sont un vecteur ; une réponse donne ces vecteurs du pas 0 (avant tout changement) au
# dernier pas.
Walk = tuple[int, ...]
Outputs = tuple[int, ...]
Responses = Mapping[Walk, tuple[Outputs, ...]]

_NO_RESPONSE: Responses = {}


@dataclass(frozen=True)
class BatteryResult:
    """Le résultat de la batterie sur un circuit à boucle.

    ``responses`` donne, pour chaque marche, les sorties à chaque pas. Si le statut est
    ``UNSTABLE`` (une marche oscille), elle est vide : rien n'est significatif.
    ``memory`` dit si une marche a révélé une mémoire (cahier, « Les trois cas
    détectés »).
    """

    status: Status
    memory: bool
    responses: Responses


@dataclass(frozen=True)
class SequentialSignature:
    """La réponse d'un circuit à la batterie, en forme canonique.

    ``responses`` est la liste des marches (triées) avec leurs sorties à chaque pas.
    """

    input_count: int
    output_count: int
    responses: tuple[tuple[Walk, tuple[Outputs, ...]], ...]


@dataclass(frozen=True)
class SequentialForm:
    """La signature séquentielle d'un circuit, et comment y arriver.

    ``input_order`` a le même sens que pour ``CanonicalForm`` : ``input_order[j]`` est
    l'indice, dans le circuit d'origine, de l'entrée qui devient l'entrée j de la forme
    canonique. ``exact`` vaut ``False`` quand il y avait trop d'entrées pour essayer
    tous les ordres : la signature garde alors l'ordre d'origine.
    """

    signature: SequentialSignature
    input_order: tuple[int, ...]
    exact: bool


def battery_walks(input_count: int, length: int = BATTERY_LENGTH) -> tuple[Walk, ...]:
    """Renvoie toutes les marches de la batterie : ``length`` changements d'entrée.

    Sans entrée, il n'y a rien à changer : la batterie est vide.
    """
    if length < 1:
        raise SimulationError(
            f"Une marche doit changer au moins une entrée (longueur reçue : {length})."
        )
    if input_count < 1:
        return ()
    return tuple(itertools.product(range(input_count), repeat=length))


def walk_vectors(input_count: int, walk: Walk) -> tuple[tuple[int, ...], ...]:
    """Renvoie les vecteurs d'une marche : tout à 0, puis un changement par pas."""
    vector = [0] * input_count
    vectors = [tuple(vector)]
    for index in walk:
        vector[index] ^= 1
        vectors.append(tuple(vector))
    return tuple(vectors)


def has_loop(circuit: Circuit) -> bool:
    """Dit si les câbles du circuit forment une boucle (y compris sur un seul nœud).

    On retire peu à peu les nœuds dont tous les câbles entrants viennent de nœuds déjà
    retirés : s'il en reste, ils sont pris dans une boucle (ou en aval d'une boucle).
    """
    successors: dict[int, list[int]] = {}
    waiting = dict.fromkeys((node.node_id for node in circuit.nodes()), 0)
    for wire in circuit.wires():
        successors.setdefault(wire.source.node_id, []).append(wire.sink.node_id)
        waiting[wire.sink.node_id] += 1
    ready = [node_id for node_id, count in waiting.items() if count == 0]
    removed = 0
    while ready:
        node_id = ready.pop()
        removed += 1
        for target in successors.get(node_id, ()):
            waiting[target] -= 1
            if waiting[target] == 0:
                ready.append(target)
    return removed < len(waiting)


def run_battery(circuit: Circuit, length: int = BATTERY_LENGTH) -> BatteryResult | None:
    """Joue la batterie sur un circuit aplati ; ``None`` si elle est inutile.

    Elle est inutile pour un circuit sans boucle (pas de mémoire possible) et pour un
    circuit sans entrée (rien à changer). Dès qu'une marche oscille, le circuit est
    ``UNSTABLE`` : on s'arrête là. Le circuit ne doit pas contenir de composant.
    """
    input_count = len(circuit.inputs())
    walks = battery_walks(input_count, length)
    if not walks or not has_loop(circuit):
        return None
    responses: dict[Walk, tuple[Outputs, ...]] = {}
    memory = False
    for walk in walks:
        result = run_sequence(circuit, walk_vectors(input_count, walk))
        if result.status is Status.UNSTABLE:
            return BatteryResult(Status.UNSTABLE, False, _NO_RESPONSE)
        responses[walk] = tuple(step.outputs for step in result.steps)
        memory = memory or has_memory(result)
    return BatteryResult(Status.STABLE, memory, responses)


def sequential_form(battery: BatteryResult, input_count: int) -> SequentialForm:
    """Renvoie la signature séquentielle canonique d'une batterie stable."""
    if battery.status is not Status.STABLE or not battery.responses:
        raise SignatureError("Un circuit instable n'a pas de signature.")
    output_count = len(next(iter(battery.responses.values()))[0])
    identity = tuple(range(input_count))
    exact = input_count <= MAX_CANONICAL_INPUTS
    order = identity
    if exact:
        # Sur une égalité, ``min`` garde le premier ordre essayé : le déroulement est
        # déterministe.
        order = min(
            itertools.permutations(identity),
            key=lambda candidate: _relabeled(battery.responses, candidate),
        )
    signature = SequentialSignature(
        input_count, output_count, _relabeled(battery.responses, order)
    )
    return SequentialForm(signature, order, exact)


def _relabeled(
    responses: Responses, order: tuple[int, ...]
) -> tuple[tuple[Walk, tuple[Outputs, ...]], ...]:
    """Renumérote les entrées (l'entrée ``order[j]`` devient j) et trie les marches."""
    new_index = {old: new for new, old in enumerate(order)}
    items = [
        (tuple(new_index[i] for i in walk), steps) for walk, steps in responses.items()
    ]
    items.sort()
    return tuple(items)
