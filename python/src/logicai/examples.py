"""Fichiers d'exemples pour l'affichage Unity : les circuits de la phase 1.

Chaque fichier est un circuit au format JSON du cahier (voir ``serialization``), avec
ses positions x et y et un ``etat`` : les valeurs 0/1 de chaque nœud et de chaque
câble à un top. Unity lit ces fichiers et colore les câbles (phase 3).

Pour les écrire dans un dossier, depuis ``python/`` :

    PYTHONPATH=src .venv/bin/python -m logicai.examples ../circuits
"""

import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from logicai.circuit import Circuit, NodeKind, Pin
from logicai.serialization import circuit_to_json
from logicai.snapshot import (
    Snapshot,
    sequence_snapshots,
    settled_snapshot,
    snapshot_at_tick,
)

# Un constructeur câble des portes à partir des entrées et renvoie le nœud dont la
# valeur
# sort du circuit.
_Builder = Callable[[Circuit, list[int]], int]

# Les tops montrés pour un circuit qui oscille : de 0 à 3.
_OSCILLATION_TICKS = range(4)

# La séquence de la bascule SR (S̄, R̄) du cahier : mise à 1, repos, mise à 0, repos.
_SR_STEPS = ((0, 1), (1, 1), (1, 0), (1, 1))


@dataclass(frozen=True)
class _Example:
    """Un fichier à écrire : son nom, le circuit, et les valeurs à montrer."""

    stem: str
    circuit: Circuit
    snapshot: Snapshot


def write_phase1_examples(directory: Path) -> tuple[Path, ...]:
    """Écrit les fichiers d'exemples dans ``directory`` et renvoie leurs chemins, triés.

    Les fichiers existants du même nom sont remplacés. Le résultat est toujours le même.
    """
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for example in _examples():
        path = directory / f"{example.stem}.json"
        path.write_text(
            circuit_to_json(example.stem, example.circuit, example.snapshot),
            encoding="utf-8",
        )
        paths.append(path)
    return tuple(sorted(paths))


def main(arguments: Sequence[str]) -> None:
    """Écrit les exemples dans le dossier donné en premier argument."""
    write_phase1_examples(Path(arguments[0]))


# --- Les exemples --------------------------------------------------------------------


def _examples() -> Iterator[_Example]:
    """Produit tous les exemples : portes, constante, oscillation, bascule SR."""
    for name, input_count, build in _GATES:
        circuit = _gate(input_count, build)
        for combination in range(2**input_count):
            vector = tuple((combination >> i) & 1 for i in range(input_count))
            yield _Example(
                f"{name}_{_describe(vector)}",
                circuit,
                settled_snapshot(circuit, vector),
            )

    constant = _gate(0, lambda c, _: c.add_node(NodeKind.NAND))
    yield _Example("constante_1", constant, settled_snapshot(constant, ()))

    looped = _looped_not()
    for ticks in _OSCILLATION_TICKS:
        yield _Example(
            f"not_reboucle_top{ticks}", looped, snapshot_at_tick(looped, (), ticks)
        )

    latch = _sr_latch()
    for step, snapshot in enumerate(sequence_snapshots(latch, _SR_STEPS), start=1):
        yield _Example(f"bascule_sr_pas{step}", latch, snapshot)
    for ticks in _OSCILLATION_TICKS:
        yield _Example(
            f"bascule_sr_metastable_top{ticks}",
            latch,
            snapshot_at_tick(latch, (1, 1), ticks),
        )


def _describe(vector: tuple[int, ...]) -> str:
    """Écrit une combinaison d'entrées pour un nom de fichier : A0_B1."""
    return "_".join(f"{chr(ord('A') + i)}{value}" for i, value in enumerate(vector))


# --- Les circuits ---------------------------------------------------------------------


def _wire(circuit: Circuit, source_id: int, sink_id: int, sink_index: int = 0) -> None:
    """Relie la source 0 d'un nœud au puits ``sink_index`` d'un autre."""
    circuit.connect(Pin(source_id, 0), Pin(sink_id, sink_index))


def _nand(circuit: Circuit, source_a: int, source_b: int) -> int:
    """Ajoute une NAND alimentée par deux sources."""
    nand_id = circuit.add_node(NodeKind.NAND)
    _wire(circuit, source_a, nand_id, 0)
    _wire(circuit, source_b, nand_id, 1)
    return nand_id


def _not(circuit: Circuit, source_id: int) -> int:
    """Ajoute un NOT : une NAND dont les deux puits ont la même source."""
    return _nand(circuit, source_id, source_id)


def _gate(input_count: int, build: _Builder) -> Circuit:
    """Crée les entrées, laisse ``build`` câbler les portes, puis ajoute la sortie."""
    circuit = Circuit()
    inputs = [circuit.add_node(NodeKind.INPUT) for _ in range(input_count)]
    _wire(circuit, build(circuit, inputs), circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _build_not(circuit: Circuit, i: list[int]) -> int:
    return _not(circuit, i[0])


def _build_nand(circuit: Circuit, i: list[int]) -> int:
    return _nand(circuit, i[0], i[1])


def _build_and(circuit: Circuit, i: list[int]) -> int:
    return _not(circuit, _nand(circuit, i[0], i[1]))


def _build_or(circuit: Circuit, i: list[int]) -> int:
    return _nand(circuit, _not(circuit, i[0]), _not(circuit, i[1]))


def _build_xor(circuit: Circuit, i: list[int]) -> int:
    n1 = _nand(circuit, i[0], i[1])
    n2 = _nand(circuit, i[0], n1)
    n3 = _nand(circuit, i[1], n1)
    return _nand(circuit, n2, n3)


# (nom, nombre d'entrées, constructeur) : les portes du tableau E de la phase 1.
_GATES: tuple[tuple[str, int, _Builder], ...] = (
    ("not", 1, _build_not),
    ("nand", 2, _build_nand),
    ("and", 2, _build_and),
    ("or", 2, _build_or),
    ("xor", 2, _build_xor),
)


def _looped_not() -> Circuit:
    """Une NAND dont les deux puits sont sur sa propre sortie, lue par une OUTPUT."""
    circuit = Circuit()
    nand_id = circuit.add_node(NodeKind.NAND)
    _wire(circuit, nand_id, nand_id, 0)
    _wire(circuit, nand_id, nand_id, 1)
    _wire(circuit, nand_id, circuit.add_node(NodeKind.OUTPUT))
    return circuit


def _sr_latch() -> Circuit:
    """Bascule SR en NAND : Q = NAND(S̄, Q̄) et Q̄ = NAND(R̄, Q)."""
    circuit = Circuit()
    s_bar = circuit.add_node(NodeKind.INPUT)
    r_bar = circuit.add_node(NodeKind.INPUT)
    nand_q = circuit.add_node(NodeKind.NAND)
    nand_q_bar = circuit.add_node(NodeKind.NAND)
    _wire(circuit, s_bar, nand_q, 0)
    _wire(circuit, nand_q_bar, nand_q, 1)
    _wire(circuit, r_bar, nand_q_bar, 0)
    _wire(circuit, nand_q, nand_q_bar, 1)
    _wire(circuit, nand_q, circuit.add_node(NodeKind.OUTPUT))
    _wire(circuit, nand_q_bar, circuit.add_node(NodeKind.OUTPUT))
    return circuit


if __name__ == "__main__":
    main(sys.argv[1:])
