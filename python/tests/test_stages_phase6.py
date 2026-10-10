"""Tests des paliers 4 et 5 (cahier, « Les paliers »).

Palier 4 : 4 entrées et plusieurs sorties. Palier 5 : avec CLK (bascules, registres,
compteurs). Un palier plus grand contient les précédents.
"""

import itertools

from logicai.stages import STAGE_4, STAGE_5, STAGES, STAGES_1_TO_4, STAGES_1_TO_5


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
