"""Tests des paliers (cahier, « Les paliers »)."""

from collections.abc import Sequence

import pytest

from logicai.errors import InvalidStageSettingsError
from logicai.evolution import Evolution, GenerationReport
from logicai.library import Library
from logicai.mutations import MutationRules
from logicai.reward import TrialKind, TrialResult
from logicai.stages import STAGES, Curriculum, Stage, StageReport

NEW = (TrialKind.NEW,)
RECORD = (TrialKind.RECORD,)
QUIET: tuple[TrialKind, ...] = ()


class _Scripted(Evolution):
    """Une évolution dont chaque génération rend un rapport écrit d'avance."""

    def __init__(self, script: Sequence[tuple[TrialKind, ...]]) -> None:
        super().__init__(Library(), MutationRules(max_inputs=9, max_outputs=9))
        self._script = list(script)
        self._played = 0

    def step(self) -> GenerationReport:
        kinds = self._script[self._played]
        self._played += 1
        found = tuple(TrialResult(kind, 1.0, "X") for kind in kinds)
        return GenerationReport(self._played, 1, found, 0.0)


def _play(
    script: Sequence[tuple[TrialKind, ...]], stalled: int, **kwargs: tuple[Stage, ...]
) -> tuple[Curriculum, _Scripted, list[StageReport]]:
    evolution = _Scripted(script)
    curriculum = Curriculum(evolution, stalled, **kwargs)
    return curriculum, evolution, [curriculum.step() for _ in script]


# --- Le tableau des paliers --------------------------------------------------


def test_stages_follow_the_levels_table() -> None:
    # Règle : cahier, « Les paliers » : palier 1 = 1 entrée, 2 = 2 entrées, 3 = 3
    # entrées, une seule sortie ; décision Q5 : aucune boucle créée par les mutations.
    assert [(s.number, s.max_inputs, s.max_outputs) for s in STAGES] == [
        (1, 1, 1),
        (2, 2, 1),
        (3, 3, 1),
    ]
    assert all(not s.rules.allow_loops for s in STAGES)
    assert all(s.rules.max_inputs == s.max_inputs for s in STAGES)
    assert all(s.rules.max_outputs == 1 for s in STAGES)


def test_curriculum_starts_at_stage_1_with_its_rules() -> None:
    # Règle : l'IA commence au palier 1, quels que soient les réglages reçus.
    curriculum, evolution, _ = _play([], stalled=3)
    assert curriculum.stage == STAGES[0]
    assert evolution.rules == STAGES[0].rules
    assert (curriculum.quiet_generations, curriculum.is_last_stage) == (0, False)


# --- Le critère : N générations sans nouveauté -------------------------------


def test_stage_advances_after_n_generations_without_novelty() -> None:
    # Règle (décision de Téo) : on débloque le palier suivant après N générations
    # d'affilée sans nouveauté. N = 3 : 1 nouveauté puis 3 générations calmes.
    evolution = _Scripted([NEW, QUIET, QUIET, QUIET])
    curriculum = Curriculum(evolution, stalled_generations=3)
    reports = [curriculum.step() for _ in range(3)]
    assert [r.advanced_to for r in reports] == [None, None, None]
    assert evolution.rules == STAGES[0].rules  # pas encore
    last = curriculum.step()
    assert last.advanced_to == 2
    assert last.stage == 1  # cette génération a été jouée au palier 1
    assert curriculum.stage == STAGES[1]
    assert evolution.rules == STAGES[1].rules  # les prochaines générations, au palier 2
    assert curriculum.quiet_generations == 0


def test_one_quiet_generation_is_enough_when_n_is_one() -> None:
    # Règle : borne du réglage : N = 1 débloque dès la première génération calme.
    _, _, reports = _play([QUIET], stalled=1)
    assert reports[0].advanced_to == 2


def test_a_novelty_resets_the_count() -> None:
    # Règle : « aucune nouveauté pendant N générations d'AFFILÉE » : une nouveauté
    # qui arrive remet le compte à zéro. N = 3 : calme, calme, NOUVEAUTÉ, calme x3.
    _, _, reports = _play([QUIET, QUIET, NEW, QUIET, QUIET, QUIET], stalled=3)
    assert [r.advanced_to for r in reports] == [None] * 5 + [2]


def test_a_record_is_not_a_novelty() -> None:
    # Règle : un record (même signature, moins de NAND) n'est pas une nouveauté : il ne
    # remet pas le compte à zéro. N = 2 : nouveauté, puis deux générations avec records.
    _, _, reports = _play([NEW, RECORD, RECORD], stalled=2)
    assert [r.advanced_to for r in reports] == [None, None, 2]


def test_count_restarts_in_the_new_stage() -> None:
    # Règle : à l'arrivée dans un palier, le compte repart de zéro : il faut N
    # générations calmes de plus pour passer du palier 2 au palier 3.
    _, _, reports = _play([QUIET] * 4, stalled=2)
    assert [r.advanced_to for r in reports] == [None, 2, None, 3]
    assert [r.stage for r in reports] == [1, 1, 2, 2]


def test_last_stage_is_kept() -> None:
    # Règle : les paliers 4 et 5 viennent à la phase 6 : après le palier 3, on y reste,
    # même après beaucoup de générations calmes.
    curriculum, evolution, reports = _play([QUIET] * 10, stalled=2)
    assert [r.advanced_to for r in reports[:4]] == [None, 2, None, 3]
    assert all(r.advanced_to is None for r in reports[4:])
    assert (curriculum.stage, curriculum.is_last_stage) == (STAGES[2], True)
    assert evolution.rules == STAGES[2].rules
    assert curriculum.quiet_generations == 6  # le compte continue, sans effet


def test_single_stage_never_advances() -> None:
    # Règle : avec un seul palier, il n'y a pas de suivant.
    only = (Stage(1, 1, 1),)
    curriculum, _, reports = _play([QUIET] * 5, stalled=1, stages=only)
    assert all(r.advanced_to is None for r in reports)
    assert curriculum.is_last_stage


# --- Réglages refusés --------------------------------------------------------


def test_nonsense_settings_are_refused() -> None:
    # Règle : erreurs dédiées avec un message qui dit ce qui est refusé.
    evolution = _Scripted([])
    with pytest.raises(InvalidStageSettingsError):
        Curriculum(evolution, stalled_generations=0)
    with pytest.raises(InvalidStageSettingsError):
        Curriculum(evolution, stalled_generations=5, stages=())


# --- Avec une vraie évolution ------------------------------------------------


def _real_run(seed: int, generations: int, stalled: int) -> list[StageReport]:
    library = Library()
    curriculum = Curriculum(Evolution(library, STAGES[0].rules, seed=seed), stalled)
    reports = []
    for _ in range(generations):
        reports.append(curriculum.step())
        stage = curriculum.stage
        for name in library.names():
            # Aucun composant n'a plus d'entrées que le palier en cours ne le permet.
            assert len(library.definitions()[name].inputs()) <= stage.max_inputs
    return reports


def test_real_run_finds_not_then_unlocks_stage_2_and_then_3() -> None:
    # Règle : l'IA découvre NOT au palier 1, puis passe au palier 2 quand plus rien de
    # nouveau n'arrive, et ainsi de suite jusqu'au palier 3.
    reports = _real_run(seed=0, generations=250, stalled=10)
    assert [r.advanced_to for r in reports if r.advanced_to] == [2, 3]
    first = next(r for r in reports if r.generation.discoveries)
    assert first.stage == 1
    assert first.generation.discoveries[0].name == "NOT"


def test_real_run_is_reproducible() -> None:
    # Règle (CLAUDE.md) : même graine, même déroulement, paliers compris.
    assert _real_run(1, 60, 5) == _real_run(1, 60, 5)
