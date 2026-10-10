"""Tests de la récompense (cahier, « Système de récompense »)."""

import pytest

from builders import (
    add_nand,
    bloated,
    build_and,
    build_and_not,
    build_not_and,
    build_xor,
    gate,
    not_circuit,
    pass_through,
    wire,
)
from logicai.circuit import Circuit, NodeKind
from logicai.errors import (
    ComponentTooLargeError,
    FlattenError,
    InvalidRewardSettingsError,
)
from logicai.filters import Rejection
from logicai.library import Library, LibraryLimits
from logicai.reward import (
    DEFAULT_NAND_COST,
    DEFAULT_NOVELTY_REWARD,
    DEFAULT_RECORD_REWARD,
    DEFAULT_REUSE_BONUS,
    RewardSettings,
    RewardTracker,
    TrialKind,
)

# Valeurs par défaut : nouveauté 100, record 30, réutilisation 5, k = 1 par NAND.
DEFAULT = RewardSettings()
# Des poids différents de ceux par défaut, pour vérifier que la formule les utilise.
CUSTOM = RewardSettings(novelty=50.0, record=10.0, reuse=3.0, nand_cost=2.0)


def _tracker(settings: RewardSettings | None = None) -> RewardTracker:
    return RewardTracker(Library(), settings)


def _snapshot(circuit: Circuit) -> tuple[object, object]:
    return circuit.nodes(), circuit.wires()


def _wire_component(
    circuit: Circuit, library: Library, name: str, *sources: int
) -> int:
    """Pose un composant et câble ses puits depuis les sources données, dans l'ordre."""
    node = library.instantiate(circuit, name)
    for index, source in enumerate(sources):
        wire(circuit, source, node, index)
    return node


def _and_from_not_component(library: Library) -> Circuit:
    """AND = NAND suivie du composant NOT : 1 NAND + 1 (coût de NOT) = 2."""
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    not_node = _wire_component(circuit, library, "NOT", add_nand(circuit, a, b))
    wire(circuit, not_node, circuit.add_node(NodeKind.OUTPUT))
    return circuit


# --- Les réglages ------------------------------------------------------------


def test_default_weights_follow_the_orders_of_magnitude() -> None:
    # Règle : tableau de la formule : nouveauté « grand », record « moyen »,
    # réutilisation « petit », et chaque NAND coûte k points (positif).
    assert DEFAULT_NOVELTY_REWARD > DEFAULT_RECORD_REWARD > DEFAULT_REUSE_BONUS > 0
    assert DEFAULT_NAND_COST > 0
    assert (
        RewardSettings(
            DEFAULT_NOVELTY_REWARD,
            DEFAULT_RECORD_REWARD,
            DEFAULT_REUSE_BONUS,
            DEFAULT_NAND_COST,
        )
        == DEFAULT
    )


@pytest.mark.parametrize("field", ["novelty", "record", "reuse", "nand_cost"])
def test_negative_weights_are_refused(field: str) -> None:
    # Règle : un poids négatif n'aurait pas de sens (erreur dédiée, message clair).
    with pytest.raises(InvalidRewardSettingsError, match="négatif"):
        RewardSettings(**{field: -1.0})


def test_zero_weights_are_allowed() -> None:
    # Règle : un poids à zéro est un réglage possible (par exemple sans pénalité).
    RewardSettings(novelty=0.0, record=0.0, reuse=0.0, nand_cost=0.0)


# --- Issue 1 : refusé, 0 point -----------------------------------------------


@pytest.mark.parametrize(
    ("circuit", "reasons"),
    [
        (pass_through(), (Rejection.COPIED_INPUT,)),
        (gate(2, lambda c, i: i[0]), (Rejection.UNUSED_INPUT, Rejection.COPIED_INPUT)),
    ],
    ids=["fil", "entrée inutile"],
)
def test_filtered_circuit_is_rejected_for_zero_points(
    circuit: Circuit, reasons: tuple[Rejection, ...]
) -> None:
    # Règle : schéma du cahier : « Filtres OK ? non -> Rejeté, 0 point ».
    tracker = _tracker()
    result = tracker.evaluate(circuit)
    assert (result.kind, result.reward, result.name) == (TrialKind.REJECTED, 0.0, None)
    assert result.rejections == reasons


def test_unstable_circuit_is_rejected_for_zero_points() -> None:
    # Règle : « il est instable » est un filtre : 0 point, et pas d'exception de la
    # bibliothèque (qui refuserait un circuit instable).
    circuit = Circuit()
    nand = circuit.add_node(NodeKind.NAND)
    wire(circuit, nand, nand, 0)
    wire(circuit, nand, nand, 1)
    wire(circuit, nand, circuit.add_node(NodeKind.OUTPUT))
    result = _tracker().evaluate(circuit)
    assert (result.kind, result.reward) == (TrialKind.REJECTED, 0.0)
    assert result.rejections == (Rejection.UNSTABLE,)


def test_circuit_without_output_is_rejected_without_reason() -> None:
    # Règle : un circuit sans sortie n'a rien d'observable (la bibliothèque le refuse) :
    # 0 point, sans motif de filtre.
    result = _tracker().evaluate(Circuit())
    assert (result.kind, result.reward, result.rejections) == (
        TrialKind.REJECTED,
        0.0,
        (),
    )


def test_rejected_trial_changes_nothing() -> None:
    # Règle : un essai refusé n'ajoute rien à la bibliothèque et ne compte aucune
    # réutilisation, même s'il pose un composant.
    library = Library()
    tracker = RewardTracker(library)
    tracker.evaluate(not_circuit())
    circuit = Circuit()
    a = circuit.add_node(NodeKind.INPUT)
    wire(circuit, a, circuit.add_node(NodeKind.OUTPUT))  # recopie : refusé
    _wire_component(circuit, library, "NOT", a)
    result = tracker.evaluate(circuit)
    assert result.kind is TrialKind.REJECTED
    assert library.names() == ("NOT",)
    assert tracker.reuse_count("NOT") == 0


# --- Issue 2 : nouveauté -----------------------------------------------------


def test_new_discovery_gets_novelty_minus_size_penalty() -> None:
    # Règle : R = R_nouveauté − k · N_NAND. Un NOT (1 NAND) : 100 − 1 = 99.
    result = _tracker().evaluate(not_circuit())
    assert (result.kind, result.name, result.reward) == (TrialKind.NEW, "NOT", 99.0)
    assert result.reused == ()


def test_bigger_new_discovery_pays_more_for_its_size() -> None:
    # Règle : « chaque NAND coûte k points » : XOR (4 NAND) : 100 − 4 ;
    # le même XOR gonflé (6 NAND) : 100 − 6.
    assert _tracker().evaluate(gate(2, build_xor)).reward == 96.0
    assert _tracker().evaluate(gate(2, bloated(build_xor))).reward == 94.0


def test_formula_uses_the_given_weights() -> None:
    # Règle : la formule utilise les poids du réglage : 50 − 2 × 4 = 42.
    assert _tracker(CUSTOM).evaluate(gate(2, build_xor)).reward == 42.0


def test_cost_is_counted_after_cleaning() -> None:
    # Règle : le coût est celui du circuit gardé (cahier, « Composants et
    # bibliothèque », étape 1 nettoyage) : une NAND qui ne mène à aucune sortie
    # ne coûte rien.
    circuit = not_circuit()
    circuit.add_node(NodeKind.NAND)
    assert _tracker().evaluate(circuit).reward == 99.0


def test_dead_oscillator_next_to_a_good_circuit_is_ignored() -> None:
    # Règle : on juge le circuit gardé. Une NAND rebouclée qui n'alimente aucune
    # sortie serait « instable » dans le circuit brut, mais le nettoyage la retire.
    circuit = not_circuit()
    junk = circuit.add_node(NodeKind.NAND)
    wire(circuit, junk, junk, 0)
    wire(circuit, junk, junk, 1)
    result = _tracker().evaluate(circuit)
    assert (result.kind, result.reward) == (TrialKind.NEW, 99.0)


# --- Issue 3 : record --------------------------------------------------------


def test_record_gets_record_minus_size_penalty() -> None:
    # Règle : R = R_record − k · N_NAND quand la signature est connue mais le nouveau
    # circuit a moins de NAND : XOR gonflé (6) puis XOR (4) : 30 − 4 = 26.
    tracker = _tracker()
    tracker.evaluate(gate(2, bloated(build_xor)))
    result = tracker.evaluate(gate(2, build_xor))
    assert (result.kind, result.name, result.reward) == (TrialKind.RECORD, "XOR", 26.0)


# --- Issue 4 : aucune récompense ---------------------------------------------


def test_known_signature_without_fewer_nand_gets_nothing() -> None:
    # Règle : « Moins de NAND ? non -> Aucune récompense », et décision Q2 : le
    # score est 0, pas négatif, même pour un circuit plus gros que le composant connu.
    tracker = _tracker()
    tracker.evaluate(gate(2, build_xor))
    same_size = tracker.evaluate(gate(2, build_xor))
    bigger = tracker.evaluate(gate(2, bloated(build_xor)))
    for result in (same_size, bigger):
        assert (result.kind, result.name, result.reward) == (
            TrialKind.NOTHING,
            "XOR",
            0.0,
        )


def test_swapped_inputs_are_the_same_discovery() -> None:
    # Règle : cahier, « Composants équivalents » (décision de Téo) : A ET NON B et
    # NON A ET B (entrées échangées) sont une seule découverte : la 2e ne rapporte rien.
    tracker = _tracker()
    first = tracker.evaluate(gate(2, build_and_not))
    second = tracker.evaluate(gate(2, build_not_and))
    assert (first.kind, first.name) == (TrialKind.NEW, "ANDNOT")
    assert (second.kind, second.name, second.reward) == (
        TrialKind.NOTHING,
        "ANDNOT",
        0.0,
    )


# --- Réutilisation (décision Q3) ---------------------------------------------


def test_reusing_a_component_gives_a_bonus_and_counts() -> None:
    # Décision Q3 : bonus ajouté à la nouvelle découverte + compteur par composant.
    # AND = NAND + composant NOT : 100 + 5 − 1 × 2 = 103.
    library = Library()
    tracker = RewardTracker(library)
    tracker.evaluate(not_circuit())
    result = tracker.evaluate(_and_from_not_component(library))
    assert (result.kind, result.name, result.reward) == (TrialKind.NEW, "AND", 103.0)
    assert result.reused == ("NOT",)
    assert tracker.reuse_count("NOT") == 1


def test_bonus_is_per_distinct_component_not_per_use() -> None:
    # Interprétation : poser deux fois NOT dans une découverte compte une seule
    # réutilisation de NOT. OR = NAND(NON A, NON B) avec 2 composants NOT :
    # coût 1 + 1 + 1 = 3, bonus 5 une fois : 100 + 5 − 3 = 102 ; le compteur passe à 2.
    library = Library()
    tracker = RewardTracker(library)
    tracker.evaluate(not_circuit())
    tracker.evaluate(_and_from_not_component(library))  # 1re réutilisation de NOT
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    not_a = _wire_component(circuit, library, "NOT", a)
    not_b = _wire_component(circuit, library, "NOT", b)
    wire(circuit, add_nand(circuit, not_a, not_b), circuit.add_node(NodeKind.OUTPUT))
    result = tracker.evaluate(circuit)
    assert (result.name, result.reward, result.reused) == ("OR", 102.0, ("NOT",))
    assert tracker.reuse_count("NOT") == 2


def test_each_distinct_component_gets_its_own_bonus() -> None:
    # Règle : deux composants différents réutilisés valent deux bonus.
    # A ET NON B avec les composants NOT puis AND : coût 1 + 2 = 3,
    # bonus 2 × 5 : 100 + 10 − 3 = 107.
    library = Library()
    tracker = RewardTracker(library)
    tracker.evaluate(not_circuit())
    tracker.evaluate(_and_from_not_component(library))
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    not_b = _wire_component(circuit, library, "NOT", b)
    and_node = _wire_component(circuit, library, "AND", a, not_b)
    wire(circuit, and_node, circuit.add_node(NodeKind.OUTPUT))
    result = tracker.evaluate(circuit)
    assert (result.name, result.reward) == ("ANDNOT", 107.0)
    assert result.reused == ("NOT", "AND")
    assert (tracker.reuse_count("NOT"), tracker.reuse_count("AND")) == (2, 1)


def test_useless_component_earns_no_bonus() -> None:
    # Règle anti-triche : on compte les composants du circuit gardé. Un composant NOT
    # posé sans rien alimenter est retiré au nettoyage : ni bonus, ni compteur.
    library = Library()
    tracker = RewardTracker(library)
    tracker.evaluate(not_circuit())
    circuit = gate(2, build_and)
    _wire_component(circuit, library, "NOT", circuit.inputs()[0])  # ne mène nulle part
    result = tracker.evaluate(circuit)
    assert (result.kind, result.name, result.reward) == (TrialKind.NEW, "AND", 98.0)
    assert result.reused == ()
    assert tracker.reuse_count("NOT") == 0


def test_record_gets_no_reuse_bonus() -> None:
    # Interprétation : le bonus est pour « une nouvelle découverte » seulement.
    # AND gonflé (4 NAND) existe ; le refaire avec NAND + composant NOT (coût 2) est un
    # record : 30 − 2 = 28, sans bonus, et le compteur de NOT ne bouge pas.
    library = Library()
    tracker = RewardTracker(library)
    tracker.evaluate(not_circuit())
    tracker.evaluate(gate(2, bloated(build_and)))
    result = tracker.evaluate(_and_from_not_component(library))
    assert (result.kind, result.name, result.reward) == (TrialKind.RECORD, "AND", 28.0)
    assert result.reused == ()
    assert tracker.reuse_count("NOT") == 0


def test_reuse_count_of_unknown_name_is_zero() -> None:
    # Règle : un composant jamais réutilisé a un compteur à 0.
    assert _tracker().reuse_count("INCONNU") == 0


def test_bonus_uses_the_given_weight() -> None:
    # Règle : le bonus utilise le poids de réutilisation du réglage :
    # 50 + 3 − 2 × 2 = 49.
    library = Library()
    tracker = RewardTracker(library, CUSTOM)
    tracker.evaluate(not_circuit())
    assert tracker.evaluate(_and_from_not_component(library)).reward == 49.0


# --- Circuit intact, erreurs de réglage --------------------------------------


def test_evaluation_does_not_change_the_circuit() -> None:
    # Règle : un contrôle ne modifie jamais l'objet contrôlé.
    circuit = gate(2, build_xor)
    before = _snapshot(circuit)
    tracker = _tracker()
    tracker.evaluate(circuit)
    tracker.evaluate(circuit)
    assert _snapshot(circuit) == before


def test_unknown_component_is_an_error_not_a_rejection() -> None:
    # Règle : un circuit invalide n'est pas un essai « inutile » : l'erreur est levée.
    circuit = Circuit()
    node = circuit.add_component_node("INCONNU", 1, 1)
    wire(circuit, node, circuit.add_node(NodeKind.OUTPUT))
    with pytest.raises(FlattenError):
        _tracker().evaluate(circuit)


def test_circuit_above_library_limits_is_an_error() -> None:
    # Règle : un circuit plus grand que les limites de la bibliothèque est une erreur
    # de réglage (les limites du palier doivent rester dans celles de la bibliothèque).
    tracker = RewardTracker(Library(LibraryLimits(max_inputs=1, max_outputs=1)))
    with pytest.raises(ComponentTooLargeError):
        tracker.evaluate(gate(2, build_and))
