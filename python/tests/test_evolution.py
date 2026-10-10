"""Tests de la boucle d'évolution (cahier, « IA 1 : l'algorithme évolutionnaire »)."""

import random

import pytest

import logicai.evolution as evolution_module
from logicai.circuit import Circuit
from logicai.cleanup import remove_useless_nodes
from logicai.errors import InvalidEvolutionSettingsError
from logicai.evolution import Evolution, EvolutionSettings, GenerationReport
from logicai.filters import find_rejections
from logicai.flatten import flatten
from logicai.library import Library
from logicai.mutations import MutationResult, MutationRules
from logicai.reward import RewardTracker, TrialKind, TrialResult

# Réglages des paliers 1 et 2 : une seule sortie, pas de boucle (décisions Q4 et Q5).
LEVEL_1 = MutationRules(max_inputs=1, max_outputs=1)
LEVEL_2 = MutationRules(max_inputs=2, max_outputs=1)
SMALL = EvolutionSettings(children_per_generation=20)
# Largement assez pour trouver NOT au palier 1 avec les réglages par défaut.
MAX_GENERATIONS_FOR_NOT = 100


def _snapshot(circuit: Circuit) -> tuple[object, object]:
    return circuit.nodes(), circuit.wires()


def _evolution(seed: int = 0, library: Library | None = None) -> Evolution:
    return Evolution(library or Library(), LEVEL_1, SMALL, seed=seed)


def _populated(seed: int, extra_generations: int = 5) -> tuple[Evolution, Library]:
    """Une IA au palier 1 qui a trouvé NOT, puis fait quelques générations de plus."""
    library = Library()
    evolution = Evolution(library, LEVEL_1, seed=seed)  # réglages par défaut
    for _ in range(MAX_GENERATIONS_FOR_NOT):
        if library.names():
            break
        evolution.step()
    assert library.names(), "NOT aurait dû être trouvé"
    for _ in range(extra_generations):
        evolution.step()
    return evolution, library


def _recents(evolution: Evolution, library: Library) -> tuple[Circuit, ...]:
    """Les circuits récents : ce qui suit le circuit vide et les composants."""
    return evolution.parents()[1 + len(library.names()) :]


# --- Les réglages ------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"children_per_generation": 0},
        {"min_mutations": 0},
        {"min_mutations": 5, "max_mutations": 4},
        {"recent_size": -1},
    ],
    ids=["0 enfant", "0 mutation", "min > max", "récents négatifs"],
)
def test_nonsense_settings_are_refused(bad: dict[str, int]) -> None:
    # Règle : erreurs dédiées avec un message qui dit ce qui est refusé.
    with pytest.raises(InvalidEvolutionSettingsError):
        EvolutionSettings(**bad)


def test_edge_settings_are_allowed() -> None:
    # Règle : les bornes permises (1 enfant, min = max, 0 circuit récent) fonctionnent.
    settings = EvolutionSettings(
        children_per_generation=1, min_mutations=3, max_mutations=3, recent_size=0
    )
    Evolution(Library(), LEVEL_1, settings, seed=0).step()


# --- Les parents (décision Q1) -----------------------------------------------


def test_first_parent_is_only_the_blank_circuit() -> None:
    # Décision Q1 : on peut toujours repartir de zéro. Au début, le seul parent est le
    # circuit vide : une entrée, une sortie, aucun câble.
    (blank,) = _evolution().parents()
    assert (len(blank.inputs()), len(blank.outputs()), len(blank.wires())) == (1, 1, 0)
    assert blank.nand_count() == 0


def test_parents_are_blank_then_components_then_recent_circuits() -> None:
    # Décision Q1 : parents = circuit vide, plus petit circuit de chaque signature
    # trouvée (les composants, dans l'ordre), puis circuits récents.
    evolution, library = _populated(seed=0)
    parents = evolution.parents()
    components = [library.definitions()[name] for name in library.names()]
    assert len(components) > 0
    assert parents[0].nand_count() == 0
    assert list(parents[1 : 1 + len(components)]) == components
    assert len(parents) >= 1 + len(components)


def test_component_definition_is_the_parent_itself() -> None:
    # Décision Q1 : le plus petit circuit de la signature est la définition du
    # composant, pas une copie : un record la remplace, et le parent suit.
    evolution, library = _populated(seed=0)
    name = library.names()[0]
    assert any(p is library.definitions()[name] for p in evolution.parents())


def test_recent_circuits_are_bounded_clean_and_accepted() -> None:
    # Décision Q1 : « quelques » circuits récents, qui ont passé les filtres, nettoyés.
    library = Library()
    evolution = Evolution(library, LEVEL_1, EvolutionSettings(recent_size=5), seed=2)
    for _ in range(15):
        evolution.step()
    recents = _recents(evolution, library)
    assert 0 < len(recents) <= 5
    for circuit in recents:
        assert find_rejections(circuit, library.definitions()) == ()
        assert _snapshot(remove_useless_nodes(circuit)) == _snapshot(circuit)


def test_no_recent_circuits_when_recent_size_is_zero() -> None:
    # Règle : avec recent_size = 0, les parents sont le circuit vide et les composants.
    library = Library()
    evolution = Evolution(library, LEVEL_1, EvolutionSettings(recent_size=0), seed=2)
    for _ in range(15):
        evolution.step()
    assert len(library.names()) > 0
    assert len(evolution.parents()) == 1 + len(library.names())


def test_parents_are_never_modified() -> None:
    # Règle : les mutations travaillent sur des copies ; un parent choisi reste intact
    # (on garde les anciens circuits : un record en met un nouveau à la place, sans
    # toucher à l'ancien).
    evolution, _ = _populated(seed=3)
    before = [(circuit, _snapshot(circuit)) for circuit in evolution.parents()]
    assert len(before) > 1
    for _ in range(15):
        evolution.step()
    for circuit, snapshot in before:
        assert _snapshot(circuit) == snapshot


# --- Les enfants -------------------------------------------------------------


def test_child_gets_at_least_one_change_and_at_most_max_mutations() -> None:
    # Règle : chaque mutation ajoute ou retire un nœud ou un câble. Avec 1 mutation,
    # le circuit vide (2 nœuds, 0 câble) devient un circuit différent ; avec au plus
    # k, il a au plus 2 + k nœuds et câbles au total.
    single = EvolutionSettings(children_per_generation=1, max_mutations=1)
    one = Evolution(Library(), LEVEL_1, single, seed=0)
    for _ in range(30):
        assert _snapshot(one.propose_child()) != _snapshot(one.parents()[0])
    settings = EvolutionSettings(children_per_generation=1, max_mutations=4)
    many = Evolution(Library(), LEVEL_1, settings, seed=0)
    for _ in range(30):
        child = many.propose_child()
        assert len(child.nodes()) + len(child.wires()) <= 2 + 4


def test_mutation_count_covers_min_to_max_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Règle : un enfant reçoit un nombre de mutations tiré entre ``min_mutations`` et
    # ``max_mutations``, bornes comprises (ni toujours le minimum, ni le maximum).
    calls = {"count": 0}
    real_mutate = evolution_module.mutate

    def counting_mutate(
        circuit: Circuit, rng: random.Random, rules: MutationRules, library: Library
    ) -> MutationResult:
        calls["count"] += 1
        return real_mutate(circuit, rng, rules, library)

    monkeypatch.setattr(evolution_module, "mutate", counting_mutate)
    settings = EvolutionSettings(
        children_per_generation=1, min_mutations=2, max_mutations=5
    )
    evolution = Evolution(Library(), LEVEL_1, settings, seed=0)
    seen = set()
    for _ in range(200):
        calls["count"] = 0
        evolution.propose_child()
        seen.add(calls["count"])
    assert seen == {2, 3, 4, 5}


def test_children_respect_the_level_rules() -> None:
    # Décisions Q4 et Q5 : au palier 1, un enfant a au plus 1 entrée et 1 sortie ; et
    # tous les circuits récents restent dans ces limites.
    library = Library()
    evolution = _evolution(seed=1, library=library)
    for _ in range(20):
        evolution.step()
        for circuit in evolution.parents():
            assert len(circuit.inputs()) <= 1
            assert len(circuit.outputs()) == 1


def test_changing_the_rules_changes_what_can_be_found() -> None:
    # Règle : les réglages du palier (``rules``) peuvent changer entre deux générations.
    # Au palier 2, des fonctions à 2 entrées (NAND...) entrent dans la bibliothèque.
    library = Library()
    evolution = _evolution(seed=0, library=library)
    for _ in range(20):
        evolution.step()
    assert all(len(library.definitions()[n].inputs()) == 1 for n in library.names())
    evolution.rules = LEVEL_2
    for _ in range(150):
        evolution.step()
    two_inputs = [
        n for n in library.names() if len(library.definitions()[n].inputs()) == 2
    ]
    assert len(two_inputs) > 0


# --- Les rapports ------------------------------------------------------------


def test_first_generations_find_not_at_level_1() -> None:
    # Règle : palier 1 : l'IA découvre seule le NOT (cahier, plan de la phase 4). Avec
    # 5 graines différentes, c'est fait en peu de générations, avec la taille minimale.
    for seed in range(5):
        library = Library()
        evolution = _evolution(seed=seed, library=library)
        for _ in range(60):
            evolution.step()
        assert library.names()[0] == "NOT", f"graine {seed}"
        assert library.cost("NOT") == 1


def test_reports_count_trials_and_sum_rewards() -> None:
    # Règle : un rapport donne le numéro de la génération, le nombre d'essais, les
    # découvertes (nouveautés et records seulement) et la somme des récompenses.
    evolution = _evolution(seed=0)
    reports: list[GenerationReport] = [evolution.step() for _ in range(12)]
    assert [r.generation for r in reports] == list(range(1, 13))
    assert all(r.trials == SMALL.children_per_generation for r in reports)
    for report in reports:
        assert all(
            d.kind in (TrialKind.NEW, TrialKind.RECORD) for d in report.discoveries
        )
        # Les autres essais valent 0 : la somme est celle des découvertes.
        assert report.total_reward == sum(d.reward for d in report.discoveries)
    assert sum(r.new_count for r in reports) > 0
    assert sum(len(r.discoveries) for r in reports) >= sum(r.new_count for r in reports)


def test_records_are_discoveries_but_not_novelties() -> None:
    # Règle : un record (même signature, moins de NAND) est une découverte, mais pas
    # une nouveauté : « aucune nouveauté pendant N générations » (palier) l'ignore.
    # On prend une exécution où des records ont lieu (graine 3, palier 2).
    evolution, _ = _populated(seed=3, extra_generations=0)
    evolution.rules = LEVEL_2
    reports = [evolution.step() for _ in range(20)]
    with_record = [
        r for r in reports if any(d.kind is TrialKind.RECORD for d in r.discoveries)
    ]
    assert with_record, "cette graine devrait produire au moins un record"
    for report in with_record:
        records = [d for d in report.discoveries if d.kind is TrialKind.RECORD]
        assert report.new_count == len(report.discoveries) - len(records)
        assert report.total_reward == sum(d.reward for d in report.discoveries)


# --- Graine et cohérence de la bibliothèque ----------------------------------


def _run(seed: int, generations: int) -> tuple[list[GenerationReport], Library]:
    library = Library()
    evolution = Evolution(library, LEVEL_2, SMALL, seed=seed)
    return [evolution.step() for _ in range(generations)], library


def test_same_seed_gives_the_same_run() -> None:
    # Règle (CLAUDE.md) : tout tirage aléatoire passe par un générateur avec une
    # graine : même graine, mêmes rapports et même bibliothèque.
    first, library_a = _run(5, 25)
    second, library_b = _run(5, 25)
    assert first == second
    assert {n: library_a.cost(n) for n in library_a.names()} == {
        n: library_b.cost(n) for n in library_b.names()
    }


def test_different_seeds_give_different_runs() -> None:
    # Règle : la graine compte vraiment (sinon le test précédent ne prouverait rien).
    runs = [repr(_run(seed, 10)[0]) for seed in range(5)]
    assert len(set(runs)) > 1


def test_global_random_state_is_never_used() -> None:
    # Règle : seul le générateur de l'IA compte, pas l'état global de ``random``.
    random.seed(1)
    first, _ = _run(7, 15)
    random.seed(2)
    assert _run(7, 15)[0] == first


def test_library_stays_consistent_after_a_run() -> None:
    # Règle : tout ce qui est dans la bibliothèque est utilisable : chaque composant
    # s'aplatit sans erreur (pas de cycle de composants), passe encore les filtres, et
    # le re-proposer ne rapporte rien (même signature, pas moins de NAND).
    evolution, library = _populated(seed=1)
    evolution.rules = LEVEL_2
    for _ in range(120):
        evolution.step()
    assert len(library.names()) >= 3
    checker = RewardTracker(library)
    for name in library.names():
        definition = library.definitions()[name]
        flatten(definition, library.definitions())
        assert find_rejections(definition, library.definitions()) == ()
        result = checker.evaluate(definition.copy())
        assert (result.kind, result.name, result.reward) == (
            TrialKind.NOTHING,
            name,
            0.0,
        )


# --- Le crochet « un essai vient d'être jugé » -------------------------------


def test_on_trial_is_called_for_every_child_with_its_result() -> None:
    # Règle : le crochet ``on_trial`` reçoit chaque enfant et son résultat, une fois par
    # essai ; la somme des récompenses reçues est celle du rapport ; et pour une
    # découverte, le composant est déjà dans la bibliothèque au moment de l'appel.
    library = Library()
    seen: list[tuple[Circuit, TrialResult]] = []

    def hook(circuit: Circuit, result: TrialResult) -> None:
        if result.kind in (TrialKind.NEW, TrialKind.RECORD):
            assert result.name in library.names()
        seen.append((circuit, result))

    evolution = Evolution(library, LEVEL_1, SMALL, seed=0, on_trial=hook)
    reports = [evolution.step() for _ in range(5)]
    assert len(seen) == 5 * SMALL.children_per_generation
    assert all(isinstance(circuit, Circuit) for circuit, _ in seen)
    assert sum(result.reward for _, result in seen) == sum(
        report.total_reward for report in reports
    )
    assert any(result.kind is TrialKind.REJECTED for _, result in seen)
    assert any(result.kind is TrialKind.NEW for _, result in seen)
    # L'enfant arrive tel qu'il a été essayé, nœuds inutiles compris (pas nettoyé).
    assert any(
        _snapshot(circuit) != _snapshot(remove_useless_nodes(circuit))
        for circuit, _ in seen
    )


def test_an_error_in_on_trial_is_not_hidden() -> None:
    # Règle : le crochet s'exécute dans la boucle d'entraînement et ses erreurs ne sont
    # pas cachées (c'est à l'appelant de les traiter ; voir ``LiveSession``).
    def hook(circuit: Circuit, result: TrialResult) -> None:
        raise RuntimeError("crochet en panne")

    evolution = Evolution(Library(), LEVEL_1, SMALL, seed=0, on_trial=hook)
    with pytest.raises(RuntimeError, match="crochet en panne"):
        evolution.step()
