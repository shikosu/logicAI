"""Tests du branchement de la liaison en direct (cahier, phase 5).

La plupart des tests n'utilisent ni socket ni fil d'exécution : le directeur reçoit une
fausse horloge et on appelle ``pump`` à la main. Un test relie la pile réelle (serveur,
fil de présentation, client TCP).
"""

import logging
import socket
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pytest

import logicai.live as live_module
from builders import add_not, bloated, build_xor, gate, wire, xor_circuit
from logicai.circuit import Circuit, NodeKind
from logicai.cleanup import remove_useless_nodes
from logicai.filters import find_rejections
from logicai.live import EXIT_CANNOT_LISTEN, EXIT_OK, LiveSession, main
from logicai.live_director import LiveDirector
from logicai.live_server import LiveServer
from logicai.protocol import (
    CIRCUIT_MESSAGE,
    DISCOVERY_MESSAGE,
    STATE_MESSAGE,
    STATS_MESSAGE,
    decode_message,
    stats_message,
)
from logicai.replay import circuit_from_placement
from logicai.reward import TrialKind, TrialResult
from logicai.serialization import circuit_from_dict

Message = dict[str, Any]
# N, le nombre de générations sans nouveauté qui débloque le palier suivant : petit,
# pour voir le palier 2 dans des essais courts.
SMALL_STALL = 5


class FakeClock:
    """Une horloge qui n'avance que quand on le dit."""

    def __init__(self) -> None:
        """Part d'une heure quelconque (100 s)."""
        self.now = 100.0

    def __call__(self) -> float:
        """Donne l'heure."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Fait avancer l'heure."""
        self.now += seconds


def _session(
    sent: list[Message],
    clock: FakeClock | None = None,
    trial_interval: float = 0.0,
    stalled: int = SMALL_STALL,
    seed: int = 0,
) -> tuple[LiveSession, LiveDirector]:
    """Une session dont le directeur écrit dans ``sent`` (sans socket ni fil)."""
    director = LiveDirector(
        sent.append,
        clock or FakeClock(),
        trial_interval=trial_interval,
        frame_interval=0.0,
        stats_interval=0.0,
    )
    return LiveSession(director, seed=seed, stalled_generations=stalled), director


def _of_kind(sent: Sequence[Mapping[str, Any]], kind: str) -> list[Message]:
    return [dict(m) for m in sent if m["message"] == kind]


# --- Les découvertes ---------------------------------------------------------


def test_every_discovery_is_announced_once_in_order_and_can_be_replayed() -> None:
    # Règle : cahier : « decouverte : nouveau composant + son ordre de pose ». Chaque
    # nouveauté ou record de l'IA devient exactement un message, dans l'ordre, et
    # l'ordre de pose rejoué redonne le circuit du message.
    sent: list[Message] = []
    session, director = _session(sent)
    expected: list[tuple[str, str]] = []
    for _ in range(100):
        report = session.step()
        director.pump()
        expected += [
            ("nouveaute" if d.kind is TrialKind.NEW else "record", str(d.name))
            for d in report.generation.discoveries
        ]
    announced = _of_kind(sent, DISCOVERY_MESSAGE)
    assert [(m["genre"], m["nom"]) for m in announced] == expected
    assert announced[0]["nom"] == "NOT"
    assert announced[0]["genre"] == "nouveaute"
    assert len(announced) >= 3
    for message in announced:
        _, circuit = circuit_from_dict(message["circuit"])
        replayed = circuit_from_placement(message["ordre_de_pose"])
        assert replayed.nodes() == circuit.nodes()
        assert set(replayed.wires()) == set(circuit.wires())
        assert message["cout"] >= 1


def test_a_record_is_announced_as_a_record_after_its_novelty() -> None:
    # Règle : un record (même signature, moins de NAND) est annoncé comme tel, après la
    # nouveauté qu'il améliore, avec un coût plus petit. Avec la graine 5, un NOT est
    # d'abord trouvé avec plusieurs NAND, puis réduit.
    sent: list[Message] = []
    session, director = _session(sent, seed=5)
    for _ in range(10):
        session.step()
        director.pump()
    announced = _of_kind(sent, DISCOVERY_MESSAGE)
    records = [m for m in announced if m["genre"] == "record"]
    assert records
    record = records[0]
    novelty = next(
        m
        for m in announced[: announced.index(record)]
        if m["nom"] == record["nom"] and m["genre"] == "nouveaute"
    )
    assert record["cout"] < novelty["cout"]


def test_discovery_cost_is_the_flattened_nand_count() -> None:
    # Règle : cahier : « Coût : on compte les NAND après aplatissement ». Pour une
    # définition sans sous-composant, c'est le nombre de NAND du circuit du message.
    sent: list[Message] = []
    session, director = _session(sent)
    for _ in range(40):
        session.step()
        director.pump()
    flat = [
        m
        for m in _of_kind(sent, DISCOVERY_MESSAGE)
        if all(n["type"] != "COMPOSANT" for n in m["circuit"]["noeuds"])
    ]
    assert flat
    for message in flat:
        _, circuit = circuit_from_dict(message["circuit"])
        assert message["cout"] == circuit.nand_count()


def _stats_rewards(seed: int) -> list[float]:
    """Les récompenses moyennes annoncées pendant 10 générations d'une graine."""
    sent: list[Message] = []
    session, director = _session(sent, seed=seed)
    for _ in range(10):
        session.step()
        director.pump()
    return [m["recompense_moyenne"] for m in _of_kind(sent, STATS_MESSAGE)]


def test_the_seed_changes_the_run_and_makes_it_reproducible() -> None:
    # Règle (CLAUDE.md) : tout le hasard vient d'une graine : même graine, même
    # déroulement ; une autre graine, un autre déroulement.
    assert _stats_rewards(1) == _stats_rewards(1)
    assert _stats_rewards(1) != _stats_rewards(2)


# --- Les statistiques --------------------------------------------------------


def test_stats_are_sent_after_every_generation() -> None:
    # Règle : cahier : « stats : palier, nombre de découvertes, récompense moyenne ».
    sent: list[Message] = []
    session, director = _session(sent)
    for _ in range(8):
        report = session.step()
        director.pump()
        generation = report.generation
        assert _of_kind(sent, STATS_MESSAGE)[-1] == stats_message(
            report.stage,
            generation.generation,
            len(session.library.names()),
            generation.total_reward / generation.trials,
        )
    assert [m["generation"] for m in _of_kind(sent, STATS_MESSAGE)] == list(range(1, 9))


def test_stats_show_the_stage_change(caplog: pytest.LogCaptureFixture) -> None:
    # Règle : le palier affiché suit les paliers de l'IA (N = 5 générations sans
    # nouveauté), et le passage est journalisé.
    sent: list[Message] = []
    session, director = _session(sent)
    with caplog.at_level(logging.INFO, logger="logicai.live"):
        for _ in range(40):
            session.step()
            director.pump()
    stages = [m["palier"] for m in _of_kind(sent, STATS_MESSAGE)]
    assert stages == sorted(stages)
    assert 1 in stages and 2 in stages
    assert "Palier 2 débloqué." in caplog.messages


# --- Les essais montrés ------------------------------------------------------


def test_a_trial_is_shown_as_a_circuit_then_state_frames() -> None:
    # Règle : l'essai en direct est un message « circuit » suivi d'images « etat »
    # cohérentes avec ce circuit.
    sent: list[Message] = []
    session, director = _session(sent)
    for _ in range(6):
        session.step()
        for _ in range(40):
            director.pump()
    first = next(i for i, m in enumerate(sent) if m["message"] == CIRCUIT_MESSAGE)
    assert sent[first]["circuit"]["nom"] == "essai"
    frames = [m["etat"] for m in sent[first + 1 :] if m["message"] == STATE_MESSAGE]
    assert frames
    _, circuit = circuit_from_dict(sent[first]["circuit"])
    assert len(frames[0]["noeuds"]) == len(circuit.nodes())
    assert len(frames[0]["cables"]) == len(circuit.wires())


def _record_shown_trials(
    monkeypatch: pytest.MonkeyPatch,
) -> list[Circuit]:
    """Remplace ``trial_messages`` par un espion qui note les circuits montrés."""
    shown: list[Circuit] = []
    real = live_module.trial_messages

    def spy(
        circuit: Circuit, definitions: Mapping[str, Circuit]
    ) -> tuple[dict[str, Any], ...]:
        shown.append(circuit)
        return real(circuit, definitions)

    monkeypatch.setattr(live_module, "trial_messages", spy)
    return shown


def test_only_accepted_trials_are_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    # Règle : l'essai en direct est un circuit accepté par les filtres : jamais un
    # circuit refusé (fil, constante, instable...).
    shown = _record_shown_trials(monkeypatch)
    sent: list[Message] = []
    session, director = _session(sent)
    for _ in range(30):
        session.step()
        for _ in range(40):
            director.pump()
    assert len(shown) >= 3
    for circuit in shown:
        kept = remove_useless_nodes(circuit)
        assert kept.outputs()
        assert find_rejections(kept, session.library.definitions()) == ()


def test_display_work_is_done_only_when_the_director_asks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Règle : l'entraînement ne fait le travail d'affichage que lorsque le directeur le
    # demande : avec une longue pause et sans ``pump``, un seul essai est préparé
    # pendant 20 générations de 50 essais.
    shown = _record_shown_trials(monkeypatch)
    sent: list[Message] = []
    session, _ = _session(sent, trial_interval=1000.0)
    for _ in range(20):
        session.step()
    assert len(shown) == 1


# --- Découvertes d'abord, et seulement des essais ordinaires assez petits ----


def test_the_first_discovery_is_announced_then_shown_live() -> None:
    # Règle (choix de Téo : « découvertes d'abord ») : la découverte de NOT est annoncée
    # puis montrée en direct : c'est le premier essai que voit l'écran.
    sent: list[Message] = []
    session, director = _session(sent)
    for _ in range(30):
        session.step()
        if "NOT" in session.library.names():
            break
    assert "NOT" in session.library.names()
    for _ in range(60):
        director.pump()
    kinds = [m["message"] for m in sent]
    assert kinds.index(DISCOVERY_MESSAGE) < kinds.index(CIRCUIT_MESSAGE)
    first = next(m for m in sent if m["message"] == CIRCUIT_MESSAGE)
    _, shown = circuit_from_dict(first["circuit"])
    assert (len(shown.inputs()), len(shown.outputs()), shown.nand_count()) == (1, 1, 1)


def test_a_discovery_is_shown_even_during_the_pause_between_trials() -> None:
    # Règle : une découverte n'attend pas la pause entre deux essais. Avec une pause
    # énorme (sans que l'horloge avance), un seul essai ordinaire pourrait passer ; ici
    # chaque découverte, finie d'afficher avant la suivante, est montrée une fois.
    sent: list[Message] = []
    session, director = _session(sent, trial_interval=1000.0)
    for _ in range(60):
        session.step()
        for _ in range(40):
            director.pump()
    circuits = _of_kind(sent, CIRCUIT_MESSAGE)
    discoveries = _of_kind(sent, DISCOVERY_MESSAGE)
    assert len(discoveries) >= 3
    assert len(circuits) == len(discoveries)


def _hook_session(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[LiveSession, LiveDirector, list[Circuit]]:
    """Une session dont la bibliothèque connaît le XOR (4 NAND), et un espion."""
    shown = _record_shown_trials(monkeypatch)
    session, director = _session([])
    session.library.register(xor_circuit())
    return session, director, shown


def _nothing(name: str | None) -> TrialResult:
    """Un essai accepté qui n'apporte rien : la fonction ``name`` est déjà connue."""
    return TrialResult(TrialKind.NOTHING, 0.0, name)


def test_an_ordinary_trial_of_the_best_size_is_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _, shown = _hook_session(monkeypatch)
    session._on_trial(xor_circuit(), _nothing("XOR"))
    assert len(shown) == 1


def test_an_ordinary_trial_of_one_and_a_half_times_the_best_size_is_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Règle (choix de Téo) : jusqu'à 1,5 fois les NAND de la meilleure version connue :
    # le XOR coûte 4, donc 6 NAND passent (la limite elle-même est acceptée).
    session, _, shown = _hook_session(monkeypatch)
    six_nand = gate(2, bloated(build_xor))
    assert six_nand.nand_count() == 6
    session._on_trial(six_nand, _nothing("XOR"))
    assert len(shown) == 1


def test_an_ordinary_trial_bigger_than_that_is_not_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Règle : au-delà de 1,5 fois (8 NAND pour un XOR de 4), l'essai n'est pas montré ;
    # le directeur reste preneur : un autre essai pourra l'être.
    session, director, shown = _hook_session(monkeypatch)
    eight_nand = gate(2, bloated(bloated(build_xor)))
    assert eight_nand.nand_count() == 8
    session._on_trial(eight_nand, _nothing("XOR"))
    assert not shown
    assert director.wants_trial()


def test_the_size_is_the_one_shown_not_the_one_tried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Règle : l'écran montre le circuit nettoyé ; c'est sa taille qui compte. Un XOR
    # suivi de 4 NAND qui n'influencent aucune sortie a 8 NAND essayées, 4 montrées.
    def xor_with_dead_end(circuit: Circuit, inputs: list[int]) -> int:
        out = build_xor(circuit, inputs)
        add_not(circuit, add_not(circuit, add_not(circuit, add_not(circuit, out))))
        return out

    session, _, shown = _hook_session(monkeypatch)
    tried = gate(2, xor_with_dead_end)
    assert tried.nand_count() == 8
    session._on_trial(tried, _nothing("XOR"))
    assert len(shown) == 1


def _xor_component_then_nots(library_session: LiveSession, extra_nots: int) -> Circuit:
    """Le composant XOR de la bibliothèque, suivi de ``extra_nots`` NOT en série."""
    circuit = Circuit()
    a, b = circuit.add_node(NodeKind.INPUT), circuit.add_node(NodeKind.INPUT)
    node = library_session.library.instantiate(circuit, "XOR")
    wire(circuit, a, node, 0)
    wire(circuit, b, node, 1)
    for _ in range(extra_nots):
        node = add_not(circuit, node)
    wire(circuit, node, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def test_a_component_is_counted_by_the_nand_it_contains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Règle : un composant compte pour ses NAND (l'écran montre le circuit aplati) :
    # le XOR (4) plus 2 NOT font 6 et passent ; plus 4 NOT font 8 et ne passent pas,
    # alors que le circuit essayé ne contient que 4 NAND « visibles ».
    session, _, shown = _hook_session(monkeypatch)
    session._on_trial(_xor_component_then_nots(session, 2), _nothing("XOR"))
    assert len(shown) == 1
    session._on_trial(_xor_component_then_nots(session, 4), _nothing("XOR"))
    assert len(shown) == 1


def test_an_ordinary_trial_without_a_known_name_is_ignored(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Règle : ignoré proprement, pas par une erreur avalée et journalisée.
    session, _, shown = _hook_session(monkeypatch)
    with caplog.at_level(logging.ERROR, logger="logicai.live"):
        session._on_trial(xor_circuit(), _nothing(None))
    assert not shown
    assert not caplog.records


def test_a_rejected_trial_is_never_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    session, director, shown = _hook_session(monkeypatch)
    assert director.wants_trial()
    session._on_trial(xor_circuit(), TrialResult(TrialKind.REJECTED, 0.0, None))
    assert not shown


def test_display_errors_never_break_the_training(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Règle : « l'entraînement n'attend jamais Unity » : une erreur dans l'affichage est
    # journalisée et ignorée ; l'IA continue de découvrir.
    def broken(circuit: Circuit, definitions: Mapping[str, Circuit]) -> tuple[Any, ...]:
        raise RuntimeError("affichage cassé")

    monkeypatch.setattr(live_module, "trial_messages", broken)
    sent: list[Message] = []
    session, director = _session(sent)
    with caplog.at_level(logging.ERROR, logger="logicai.live"):
        for _ in range(10):
            session.step()
            director.pump()
    assert "NOT" in session.library.names()
    assert any("Échec de la préparation" in m for m in caplog.messages)
    assert _of_kind(sent, DISCOVERY_MESSAGE)  # les découvertes passent quand même


def test_run_counts_generations_and_can_be_stopped() -> None:
    # Règle : ``run`` joue le nombre de générations demandé, ou s'arrête quand
    # ``should_stop`` le dit.
    sent: list[Message] = []
    session, _ = _session(sent)
    assert session.run(3) == 3
    counter = {"n": 0}

    def stop_after_two() -> bool:
        counter["n"] += 1
        return counter["n"] > 2

    assert session.run(None, stop_after_two) == 2


# --- Avec de vrais sockets ---------------------------------------------------


def _wait_for(condition: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_real_stack_delivers_valid_messages_to_a_tcp_client() -> None:
    # Règle (phase 5) : serveur, fil de présentation et IA ensemble : un client TCP
    # (faux Unity) reçoit des lignes JSON valides : les découvertes (NOT en premier),
    # des stats, et des essais montrés.
    with LiveServer(port=0) as server:
        director = LiveDirector(
            server.send, trial_interval=0.0, frame_interval=0.0, stats_interval=0.0
        )
        client = socket.create_connection(("127.0.0.1", server.port), timeout=10)
        assert _wait_for(lambda: server.connected)
        session = LiveSession(director, seed=0, stalled_generations=SMALL_STALL)
        director.start()
        try:
            session.run(40)
            kinds: list[str] = []
            buffer = b""
            client.settimeout(0.5)
            first_discovery: Message | None = None
            while True:
                try:
                    chunk = client.recv(1 << 16)
                except TimeoutError:
                    break
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, _, buffer = buffer.partition(b"\n")
                    message = decode_message(line)
                    kinds.append(message["message"])
                    if message["message"] == DISCOVERY_MESSAGE and not first_discovery:
                        first_discovery = message
        finally:
            director.stop()
            client.close()
    assert first_discovery is not None and first_discovery["nom"] == "NOT"
    assert {DISCOVERY_MESSAGE, STATS_MESSAGE, CIRCUIT_MESSAGE, STATE_MESSAGE} <= set(
        kinds
    )


# --- La commande -------------------------------------------------------------


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = int(probe.getsockname()[1])
    probe.close()
    return port


def test_command_runs_the_requested_generations_and_exits_cleanly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Règle : ``python -m logicai.live --generations 3`` joue 3 générations, annonce le
    # port, puis s'arrête proprement (code 0).
    with caplog.at_level(logging.INFO, logger="logicai.live"):
        code = main(["--port", str(_free_port()), "--generations", "3", "--seed", "1"])
    assert code == EXIT_OK
    assert "3 générations jouées." in caplog.messages
    assert any("En écoute sur 127.0.0.1" in m for m in caplog.messages)


def test_command_stops_its_server_and_threads_when_it_ends() -> None:
    # Règle : en sortant, la commande libère le port et arrête ses fils d'exécution
    # (serveur et directeur) : rien ne reste en route.
    port = _free_port()
    assert main(["--port", str(port), "--generations", "2"]) == EXIT_OK
    running = [
        t.name
        for t in threading.enumerate()
        if t.name.startswith("logicai-live") and t.is_alive()
    ]
    assert not running
    probe = socket.socket()
    probe.bind(("127.0.0.1", port))  # le port est libre : sinon, erreur
    probe.close()


def test_command_reports_a_busy_port_without_a_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Règle : port déjà pris : message clair et code de sortie dédié, pas de plantage.
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    try:
        with caplog.at_level(logging.ERROR, logger="logicai.live"):
            code = main(["--port", str(busy.getsockname()[1]), "--generations", "1"])
    finally:
        busy.close()
    assert code == EXIT_CANNOT_LISTEN
    assert any("Impossible d'écouter" in m for m in caplog.messages)


def test_command_refuses_unknown_options() -> None:
    # Règle : une option inconnue ou mal écrite est refusée par la commande (code 2).
    with pytest.raises(SystemExit) as stopped:
        main(["--port", "pas-un-nombre"])
    assert stopped.value.code == 2
