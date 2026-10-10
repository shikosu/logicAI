"""Tests de la variante « défis » : cible, proximité, choix, parents, parcours.

Cahier, « La variante « défis » » : un module choisit une table de vérité absente de la
bibliothèque, et l'IA essaie de la construire. Décisions de Téo (10 octobre 2026) : le
système choisit la cible au hasard parmi les tables absentes (et acceptées par les
filtres) ; la proximité ne sert qu'à choisir les parents ; la récompense ne change pas.
"""

import random

import pytest

from builders import add_nand, add_not, build_xor, gate, not_circuit, wire, xor_circuit
from logicai.behavior import TruthTable
from logicai.challenge import (
    MAX_DRAWS,
    MIN_CHALLENGE_INPUTS,
    Challenge,
    choose_challenge,
)
from logicai.circuit import Circuit, NodeKind
from logicai.cleanup import remove_useless_nodes
from logicai.errors import InvalidChallengeError
from logicai.evolution import CHALLENGE_PARENT_SHARE, Evolution, GenerationReport
from logicai.filters import rejections_of_table
from logicai.library import Library
from logicai.mutations import MutationRules
from logicai.reward import RewardTracker, TrialKind, TrialResult
from logicai.sequential import SequentialSignature
from logicai.signature import Signature, canonical_form
from logicai.simulation import Status
from logicai.stages import STAGES, STAGES_1_TO_4, ChallengeSettings, Curriculum, Stage

XOR, AND = 0b0110, 0b1000
HALF_ADDER = Challenge(2, (XOR, AND))
AND_NOT = 0b0010  # A ET NON B
NOT_AND = 0b0100  # NON A ET B : même découverte que AND_NOT, entrées échangées


def _half_adder() -> Circuit:
    """SOMME = XOR (4 NAND) puis RETENUE = AND (un NOT de plus) : 5 NAND."""
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    shared = add_nand(circuit, a, b)
    left, right = add_nand(circuit, a, shared), add_nand(circuit, b, shared)
    wire(circuit, add_nand(circuit, left, right), circuit.add_node(NodeKind.OUTPUT))
    wire(circuit, add_not(circuit, shared), circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _two_xors() -> Circuit:
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    for _ in range(2):
        wire(circuit, build_xor(circuit, [a, b]), circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _two_outputs_from_an_oscillator() -> Circuit:
    circuit = Circuit()
    circuit.add_node(NodeKind.INPUT)
    circuit.add_node(NodeKind.INPUT)
    nand = circuit.add_node(NodeKind.NAND)
    wire(circuit, nand, nand, 0)
    wire(circuit, nand, nand, 1)
    for _ in range(2):
        wire(circuit, nand, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _half_adder_with_a_clock() -> Circuit:
    circuit = _half_adder()
    clock = circuit.add_node(NodeKind.CLK)
    add_nand(circuit, clock, clock)
    return circuit


# --- La cible ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("input_count", "outputs"),
    [(0, (1,)), (2, ()), (2, (16,)), (2, (-1,)), (1, (0b100,))],
    ids=[
        "sans entrée",
        "sans sortie",
        "table trop grande",
        "table négative",
        "1 entrée",
    ],
)
def test_a_challenge_must_make_sense(
    input_count: int, outputs: tuple[int, ...]
) -> None:
    with pytest.raises(InvalidChallengeError):
        Challenge(input_count, outputs)


def test_a_challenge_has_a_maximum_closeness() -> None:
    # Une proximité maximale = tous les bits de toutes les tables : sorties × 2^entrées.
    assert HALF_ADDER.max_closeness == 8
    assert Challenge(3, (0b11101000,)).max_closeness == 8
    assert Challenge(3, (1, 2, 4)).max_closeness == 24


def test_swapped_inputs_give_the_same_target_signature() -> None:
    # Cahier, « Composants équivalents » : la cible est reconnue à l'arrivée même avec
    # ses entrées échangées.
    assert Challenge(2, (AND_NOT,)).signature == Challenge(2, (NOT_AND,)).signature
    assert Challenge(2, (AND,)).signature != Challenge(2, (0b0001,)).signature  # NOR


def test_target_signature_is_the_one_the_library_would_give() -> None:
    table = TruthTable(Status.STABLE, (XOR, AND))
    assert HALF_ADDER.signature == canonical_form(table, 2).signature


# --- La proximité ------------------------------------------------------------------


def test_the_exact_circuit_has_the_maximum_closeness() -> None:
    assert HALF_ADDER.closeness(_half_adder(), {}) == HALF_ADDER.max_closeness


def test_closeness_counts_the_equal_bits_with_the_outputs_in_order() -> None:
    # (XOR, XOR) contre (XOR, AND) : la 1re sortie est exacte (4 bits), la 2e compare
    # XOR = 0110 à AND = 1000 : un seul bit égal (celui de la combinaison 0) : 4 + 1.
    assert HALF_ADDER.closeness(_two_xors(), {}) == 4 + 1


def test_the_order_of_the_outputs_counts() -> None:
    # (AND, XOR) contre (XOR, AND) : 0110 contre 1000 puis 1000 contre 0110.
    swapped = Challenge(2, (AND, XOR))
    assert swapped.closeness(_half_adder(), {}) == 1 + 1


@pytest.mark.parametrize(
    "circuit",
    [
        gate(2, build_xor),
        not_circuit(),
        _two_outputs_from_an_oscillator(),
        _half_adder_with_a_clock(),
    ],
    ids=["1 sortie", "1 entrée", "instable", "avec CLK"],
)
def test_a_circuit_that_cannot_be_compared_has_no_closeness(circuit: Circuit) -> None:
    assert HALF_ADDER.closeness(circuit, {}) is None


def test_closeness_looks_inside_components() -> None:
    # Cahier, « Simulation d'un composant » : on aplatit avant de comparer.
    library = Library()
    library.register(not_circuit())
    circuit = Circuit()
    box = library.instantiate(circuit, "NOT")
    wire(circuit, circuit.add_node(NodeKind.INPUT), box)
    wire(circuit, box, circuit.add_node(NodeKind.OUTPUT))
    assert Challenge(1, (0b01,)).closeness(circuit, library.definitions()) == 2


# --- Le choix du défi --------------------------------------------------------------


def test_a_chosen_challenge_is_reachable_and_inside_the_bounds() -> None:
    # Décision de Téo : une table absente de la bibliothèque, acceptée par les filtres.
    library = Library()
    library.register(xor_circuit())
    rng = random.Random(0)
    for _ in range(100):
        challenge = choose_challenge(library, rng, max_inputs=3, max_outputs=2)
        assert challenge is not None
        assert MIN_CHALLENGE_INPUTS <= challenge.input_count <= 3
        assert 1 <= len(challenge.outputs) <= 2
        table = TruthTable(Status.STABLE, challenge.outputs)
        assert rejections_of_table(table, challenge.input_count) == ()
        assert not library.has_signature(challenge.signature)


def test_the_choice_covers_every_size_the_bounds_allow() -> None:
    # Le nombre d'entrées (de 2 à 4) et de sorties (de 1 à 3) est tiré au hasard : on
    # doit les voir tous, pas seulement le maximum ou le minimum.
    rng = random.Random(2)
    chosen = [choose_challenge(Library(), rng, 4, 3) for _ in range(400)]
    assert {c.input_count for c in chosen if c is not None} == {2, 3, 4}
    assert {len(c.outputs) for c in chosen if c is not None} == {1, 2, 3}


def test_known_functions_are_never_chosen() -> None:
    # Sans XOR ni AND dans la bibliothèque, ils peuvent sortir ; avec, jamais.
    library = Library()
    library.register(xor_circuit())
    library.register(gate(2, lambda c, i: add_not(c, add_nand(c, i[0], i[1]))))
    rng = random.Random(1)
    known = {Challenge(2, (XOR,)).signature, Challenge(2, (AND,)).signature}
    chosen = [choose_challenge(library, rng, 2, 1) for _ in range(300)]
    assert all(c is not None and c.signature not in known for c in chosen)
    # 8 découvertes à 2 entrées, 2 déjà connues : les 6 autres sortent toutes.
    assert len({c.signature for c in chosen if c is not None}) == 6


def test_the_choice_is_reproducible_with_a_seed() -> None:
    # CLAUDE.md : tout tirage aléatoire passe par un générateur avec une graine.
    library = Library()
    first = [choose_challenge(library, random.Random(7), 4, 3) for _ in range(1)]
    second = [choose_challenge(library, random.Random(7), 4, 3) for _ in range(1)]
    assert first == second
    other = choose_challenge(library, random.Random(8), 4, 3)
    assert other != first[0]


@pytest.mark.parametrize(("max_inputs", "max_outputs"), [(1, 3), (4, 0)])
def test_no_challenge_when_the_bounds_allow_nothing(
    max_inputs: int, max_outputs: int
) -> None:
    assert (
        choose_challenge(Library(), random.Random(0), max_inputs, max_outputs) is None
    )


def test_the_number_of_draws_is_bounded() -> None:
    # Une cible refusée par les filtres ne sort jamais : à 2 entrées et 1 sortie, seuls
    # 10 tables sur 16 passent, mais on ne boucle pas indéfiniment.
    assert MAX_DRAWS >= 1


# --- Les parents dans l'archive ----------------------------------------------------


def _challenged(seed: int = 3) -> Evolution:
    evolution = Evolution(Library(), MutationRules(2, 2), seed=seed)
    evolution.challenge = HALF_ADDER
    return evolution


def test_there_is_no_challenge_by_default() -> None:
    evolution = Evolution(Library(), STAGES[0].rules)
    assert evolution.challenge is None
    assert evolution.best_closeness is None


def test_the_ai_records_how_close_it_gets() -> None:
    # La meilleure proximité est le vrai maximum de celles de tous les enfants essayés
    # (recalculé ici, indépendamment de l'archive).
    tried: list[Circuit] = []
    evolution = Evolution(
        Library(),
        MutationRules(2, 2),
        seed=3,
        on_trial=lambda child, _result: tried.append(child),
    )
    evolution.challenge = HALF_ADDER
    assert evolution.best_closeness is None
    for _ in range(5):
        evolution.step()
    definitions = evolution.library.definitions()
    closeness = [
        HALF_ADDER.closeness(remove_useless_nodes(child), definitions)
        for child in tried
    ]
    best = max(c for c in closeness if c is not None)
    assert evolution.best_closeness == best
    assert 0 < best <= HALF_ADDER.max_closeness


def test_a_new_challenge_empties_the_archive() -> None:
    evolution = _challenged()
    for _ in range(5):
        evolution.step()
    evolution.challenge = Challenge(2, (XOR, AND))
    assert evolution.best_closeness is None
    evolution.challenge = None
    assert evolution.challenge is None


def test_half_of_the_parents_come_from_the_archive() -> None:
    # Valeur de départ mesurée : CHALLENGE_PARENT_SHARE = 0,5. On remplace le tirage de
    # l'IA par un autre pour compter les parents venus de l'archive.
    evolution = _challenged()
    for _ in range(5):
        evolution.step()
    archive = [circuit for _, circuit in evolution._close]
    assert archive
    evolution._rng = random.Random(0)
    picks = [evolution._choose_parent() for _ in range(2000)]
    from_archive = sum(1 for parent in picks if any(parent is c for c in archive))
    assert abs(from_archive / len(picks) - CHALLENGE_PARENT_SHARE) < 0.05


def test_without_a_challenge_the_parents_are_the_usual_ones() -> None:
    # Le circuit vide est recréé à chaque appel : on compare les nœuds et les câbles.
    evolution = Evolution(Library(), MutationRules(2, 1), seed=3)
    for _ in range(5):
        evolution.step()
    usual = [(p.nodes(), p.wires()) for p in evolution.parents()]
    evolution._rng = random.Random(0)
    for _ in range(100):
        parent = evolution._choose_parent()
        assert (parent.nodes(), parent.wires()) in usual


def test_a_challenge_changes_nothing_in_the_reward() -> None:
    # Décision de Téo : la formule du cahier ne change pas. On rejoue, sur une
    # bibliothèque neuve et sans défi, les enfants essayés pendant un défi : chaque
    # essai a la même issue et la même récompense.
    tried: list[tuple[Circuit, TrialResult]] = []
    evolution = Evolution(
        Library(),
        MutationRules(2, 2),
        seed=3,
        on_trial=lambda child, result: tried.append((child, result)),
    )
    evolution.challenge = HALF_ADDER
    for _ in range(10):
        evolution.step()
    replay = RewardTracker(Library())
    assert len(tried) == 10 * 50
    for child, result in tried:
        again = replay.evaluate(child)
        assert (again.kind, again.reward, again.name) == (
            result.kind,
            result.reward,
            result.name,
        )
    assert any(result.kind is TrialKind.NEW for _, result in tried)


# --- Le parcours -------------------------------------------------------------------


class _ScriptedEvolution(Evolution):
    """Une évolution qui ne joue rien : les rapports sont vides (aucune nouveauté).

    ``closeness`` donne, génération après génération, la valeur de ``best_closeness``.
    """

    def __init__(self, closeness: list[int | None] | None = None) -> None:
        super().__init__(Library(), STAGES[0].rules)
        self._script = list(closeness or [])
        self._turn = 0

    def step(self) -> GenerationReport:
        self._turn += 1
        return GenerationReport(self._turn, 0, (), 0.0)

    @property
    def best_closeness(self) -> int | None:
        index = min(self._turn, len(self._script)) - 1
        return self._script[index] if index >= 0 else None


# Le palier 1 autoriserait un défi (2 entrées, 2 sorties) : seul ``first_stage``
# l'empêche.
TWO_STAGES = (Stage(1, 2, 2), Stage(2, 2, 2))


def test_challenge_settings_must_make_sense() -> None:
    with pytest.raises(InvalidChallengeError, match="patience"):
        ChallengeSettings(patience=0)


def test_the_course_fixes_no_challenge_without_settings() -> None:
    evolution = _ScriptedEvolution()
    curriculum = Curriculum(evolution, 1, TWO_STAGES)
    for _ in range(5):
        curriculum.step()
    assert evolution.challenge is None
    assert curriculum.reached_challenges == 0


def test_the_course_fixes_a_challenge_on_arrival_in_the_stage() -> None:
    evolution = _ScriptedEvolution()
    curriculum = Curriculum(
        evolution, 2, TWO_STAGES, ChallengeSettings(seed=1, patience=50, first_stage=2)
    )
    curriculum.step()
    assert evolution.challenge is None  # palier 1 : pas de défi
    curriculum.step()  # N = 2 générations calmes : on arrive au palier 2
    assert curriculum.stage.number == 2
    challenge = evolution.challenge
    assert challenge is not None
    assert 2 <= challenge.input_count <= 2
    assert 1 <= len(challenge.outputs) <= 2


def test_a_stalled_challenge_is_replaced_after_the_patience() -> None:
    evolution = _ScriptedEvolution()
    curriculum = Curriculum(
        evolution, 1, TWO_STAGES, ChallengeSettings(seed=1, patience=3, first_stage=2)
    )
    curriculum.step()  # arrivée au palier 2 : 1er défi
    first = evolution.challenge
    assert first is not None
    for _ in range(2):
        curriculum.step()
        assert evolution.challenge is first  # moins de 3 générations sans progrès
    curriculum.step()
    assert evolution.challenge is not first
    assert curriculum.reached_challenges == 0


def test_progress_resets_the_patience() -> None:
    # Patience 3. La proximité monte aux générations 2 et 4, puis stagne. Le défi du
    # palier tient jusqu'à la génération 6 (2 générations sans progrès depuis la 4) et
    # n'est remplacé qu'à la 7 (3 générations sans progrès).
    evolution = _ScriptedEvolution([0, 1, 1, 2, 2, 2, 2])
    curriculum = Curriculum(
        evolution, 1, TWO_STAGES, ChallengeSettings(seed=1, patience=3, first_stage=2)
    )
    curriculum.step()  # génération 1 : arrivée au palier 2, 1er défi
    first = evolution.challenge
    assert first is not None
    for _ in range(5):  # générations 2 à 6
        curriculum.step()
        assert evolution.challenge is first
    curriculum.step()  # génération 7
    assert evolution.challenge is not first


def test_a_reached_challenge_is_counted_and_replaced() -> None:
    library = _ReachableLibrary()
    evolution = _ScriptedEvolution()
    evolution._library = library
    curriculum = Curriculum(
        evolution, 1, TWO_STAGES, ChallengeSettings(seed=1, patience=50, first_stage=2)
    )
    curriculum.step()
    first = evolution.challenge
    assert first is not None
    library.reached = first.signature
    curriculum.step()
    assert curriculum.reached_challenges == 1
    assert evolution.challenge is not first


class _ReachableLibrary(Library):
    """Une bibliothèque qui dit « connue » pour une signature choisie."""

    reached: Signature | None = None

    def has_signature(self, signature: Signature | SequentialSignature) -> bool:
        return signature == self.reached or super().has_signature(signature)


def test_stage_4_is_the_cahier_stage_with_several_outputs() -> None:
    # Cahier, « Les paliers » : palier 4 = 4 entrées et plusieurs sorties.
    assert STAGES_1_TO_4[:3] == STAGES
    stage = STAGES_1_TO_4[3]
    assert (stage.number, stage.max_inputs) == (4, 4)
    assert stage.max_outputs > 1
    assert stage.allow_loops is False
