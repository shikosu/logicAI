"""Tests des paliers 4 et 5 (cahier, « Les paliers »).

Palier 4 : 4 entrées et plusieurs sorties. Palier 5 : avec CLK (bascules, registres,
compteurs). Un palier plus grand contient les précédents.
"""

import itertools

import pytest

from logicai.errors import InvalidStageSettingsError
from logicai.evolution import Evolution, GenerationReport
from logicai.library import Library
from logicai.reward import TrialKind, TrialResult
from logicai.stages import (
    STAGE_4,
    STAGE_4_GENERATIONS,
    STAGE_5,
    STAGES,
    STAGES_1_TO_4,
    STAGES_1_TO_5,
    Curriculum,
    Stage,
)


def test_the_stages_are_numbered_from_one_to_five() -> None:
    assert [stage.number for stage in STAGES_1_TO_5] == [1, 2, 3, 4, 5]
    assert STAGES_1_TO_5[:4] == STAGES_1_TO_4
    assert STAGES_1_TO_4[:3] == STAGES


def test_each_stage_contains_the_previous_one() -> None:
    # Un palier plus grand permet « jusqu'à » n entrées et m sorties : monter ne retire
    # rien (voir l'en-tête de ``stages``).
    for before, after in itertools.pairwise(STAGES_1_TO_5):
        assert after.max_inputs >= before.max_inputs
        assert after.max_outputs >= before.max_outputs


def test_stage_4_has_four_inputs_and_several_outputs_without_loops() -> None:
    assert STAGE_4.max_inputs == 4
    assert STAGE_4.max_outputs > 1
    assert (STAGE_4.allow_loops, STAGE_4.allow_clock) == (False, False)


def test_only_stage_5_has_loops_and_the_clock() -> None:
    assert (STAGE_5.allow_loops, STAGE_5.allow_clock) == (True, True)
    for stage in STAGES_1_TO_4:
        assert (stage.allow_loops, stage.allow_clock) == (False, False)


def test_stage_5_rules_reach_the_mutations() -> None:
    rules = STAGE_5.rules
    assert (rules.allow_loops, rules.allow_clock) == (True, True)
    assert (rules.max_inputs, rules.max_outputs) == (
        STAGE_5.max_inputs,
        STAGE_5.max_outputs,
    )


# --- Durée fixe d'un palier ----------------------------------------------------------


class _AlwaysNew(Evolution):
    """Une évolution qui trouve une nouveauté à chaque génération (jamais calme)."""

    def __init__(self) -> None:
        super().__init__(Library(), STAGES[0].rules)
        self._turn = 0

    def step(self) -> GenerationReport:
        self._turn += 1
        found = (TrialResult(TrialKind.NEW, 1.0, f"C-{self._turn}"),)
        return GenerationReport(self._turn, 1, found, 1.0)


class _NeverNew(_AlwaysNew):
    """Une évolution qui ne trouve rien."""

    def step(self) -> GenerationReport:
        self._turn += 1
        return GenerationReport(self._turn, 1, (), 0.0)


def _advances(curriculum: Curriculum, generations: int) -> list[int | None]:
    return [curriculum.step().advanced_to for _ in range(generations)]


def test_stage_4_lasts_a_fixed_number_of_generations() -> None:
    # Décision de Téo : le critère « N générations sans nouveauté » ne se déclenche
    # jamais au palier 4 ; il dure un nombre fixe de générations (2 000 au départ).
    assert STAGE_4.max_generations == STAGE_4_GENERATIONS == 2000
    for stage in (*STAGES, STAGE_5):
        assert stage.max_generations is None


def test_a_stage_must_last_at_least_one_generation() -> None:
    with pytest.raises(InvalidStageSettingsError, match="génération"):
        Stage(1, 1, 1, max_generations=0)


def test_a_stage_is_left_when_its_duration_is_reached_even_with_discoveries() -> None:
    stages = (Stage(1, 1, 1, max_generations=3), Stage(2, 2, 1))
    curriculum = Curriculum(_AlwaysNew(), 400, stages)
    assert _advances(curriculum, 4) == [None, None, 2, None]


def test_the_duration_counts_from_the_arrival_in_each_stage() -> None:
    stages = (
        Stage(1, 1, 1, max_generations=2),
        Stage(2, 2, 1, max_generations=3),
        Stage(3, 3, 1),
    )
    curriculum = Curriculum(_AlwaysNew(), 400, stages)
    assert _advances(curriculum, 6) == [None, 2, None, None, 3, None]


def test_the_quiet_generations_still_end_a_stage_earlier() -> None:
    stages = (Stage(1, 1, 1, max_generations=50), Stage(2, 2, 1))
    curriculum = Curriculum(_NeverNew(), 2, stages)
    assert _advances(curriculum, 3) == [None, 2, None]


def test_the_last_stage_is_kept_whatever_its_duration() -> None:
    curriculum = Curriculum(_AlwaysNew(), 400, (Stage(1, 1, 1, max_generations=2),))
    assert _advances(curriculum, 5) == [None] * 5
    assert curriculum.is_last_stage


def test_a_stage_without_a_duration_is_not_limited() -> None:
    curriculum = Curriculum(_AlwaysNew(), 400, (Stage(1, 1, 1), Stage(2, 2, 1)))
    assert _advances(curriculum, 30) == [None] * 30
