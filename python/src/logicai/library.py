"""Bibliothèque de composants : enregistrer les découvertes, les nommer, les remplacer.

Chaque circuit enregistré devient un composant (cahier, « Composants et bibliothèque »).
Les étapes d'un enregistrement :

1. nettoyage (on retire ce qui n'influence aucune sortie) ;
2. calcul de la signature canonique sur le circuit aplati : sa table de vérité (voir
   ``signature``), ou, pour un circuit à mémoire, sa réponse à la batterie de séquences
   (voir ``sequential``) ;
3. si la signature est inconnue : nouvelle découverte, le circuit devient un composant ;
4. si elle est connue et que le circuit a moins de NAND : record, la définition du
   composant est remplacée, et tous les circuits qui l'utilisent profitent de la
   version plus petite (les composants sont rangés par référence) ;
5. sinon, rien ne change.

La bibliothèque ne décide d'aucune récompense : ``register`` dit seulement ce qui s'est
passé (``Outcome``). Transformer cela en points sera le travail de la phase 4.

Les définitions sont des circuits modifiables : il ne faut pas les modifier depuis
l'extérieur.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from types import MappingProxyType
from typing import Self

from logicai.behavior import truth_table
from logicai.circuit import Circuit
from logicai.cleanup import remove_useless_nodes
from logicai.errors import (
    ComponentTooLargeError,
    FlattenError,
    InvalidLimitsError,
    LibraryError,
    LibraryFormatError,
    NoOutputError,
    UnknownComponentNameError,
    UnstableCircuitError,
)
from logicai.flatten import flat_nand_count, flatten
from logicai.sequential import (
    SequentialForm,
    SequentialSignature,
    run_battery,
    sequential_form,
)
from logicai.serialization import circuit_from_json, circuit_to_json
from logicai.signature import CanonicalForm, Signature, canonical_form, known_name
from logicai.simulation import Status

# Limites par défaut (réponse de Téo) ; ``None`` veut dire « aucune limite ».
DEFAULT_MAX_INPUTS = 15
DEFAULT_MAX_OUTPUTS = 15

# Nom d'un composant sans nom connu : C-001, C-002...
_UNNAMED_FORMAT = "C-{number:03d}"
_FIRST_NUMBER = 1

# Un composant est rangé dans un fichier ``<nom>.json``.
_FILE_SUFFIX = ".json"


@dataclass(frozen=True)
class LibraryLimits:
    """Maximum d'entrées et de sorties d'un composant ; ``None`` = aucune limite."""

    max_inputs: int | None = DEFAULT_MAX_INPUTS
    max_outputs: int | None = DEFAULT_MAX_OUTPUTS

    def __post_init__(self) -> None:
        """Refuse une limite qui ne serait ni ``None`` ni un entier positif."""
        for label, value in (
            ("entrées", self.max_inputs),
            ("sorties", self.max_outputs),
        ):
            if value is not None and value < 1:
                raise InvalidLimitsError(
                    f"La limite d'{label} doit être un entier positif ou None "
                    f"(aucune limite), pas {value}."
                )

    @classmethod
    def unlimited(cls) -> Self:
        """Renvoie des limites qui n'imposent aucun maximum."""
        return cls(max_inputs=None, max_outputs=None)


class Outcome(Enum):
    """Ce qu'un enregistrement a changé dans la bibliothèque."""

    NEW = auto()  # signature jamais vue : nouveau composant
    RECORD = auto()  # signature connue, moins de NAND : définition remplacée
    KNOWN = auto()  # signature connue, pas moins de NAND : rien ne change


@dataclass(frozen=True)
class Registration:
    """Résultat de ``register`` : ce qui s'est passé, et le composant concerné."""

    outcome: Outcome
    name: str


@dataclass(frozen=True)
class Component:
    """Un composant : un nom, sa définition, et sa signature.

    ``input_order`` relie l'ordre des entrées de la définition à la forme canonique
    de la signature (voir ``CanonicalForm``). Le coût, lui, n'est pas rangé ici : il
    dépend des composants que la définition utilise, donc ``Library.cost`` le recalcule.
    """

    name: str
    circuit: Circuit
    signature: Signature | SequentialSignature
    input_order: tuple[int, ...]

    @property
    def has_memory(self) -> bool:
        """Dit si c'est un circuit à mémoire (sa signature est séquentielle)."""
        return isinstance(self.signature, SequentialSignature)


@dataclass(frozen=True)
class _Candidate:
    """Un circuit prêt à être enregistré : nettoyé, avec son coût et sa signature."""

    circuit: Circuit
    cost: int
    form: CanonicalForm | SequentialForm


class Library:
    """L'ensemble des composants découverts, rangés par nom."""

    def __init__(self, limits: LibraryLimits | None = None) -> None:
        """Crée une bibliothèque vide (par défaut : 15 entrées et 15 sorties max)."""
        self._limits = limits if limits is not None else LibraryLimits()
        self._components: dict[str, Component] = {}
        self._definitions: dict[str, Circuit] = {}
        self._by_signature: dict[Signature | SequentialSignature, str] = {}
        self._next_number = _FIRST_NUMBER
        # Vue en lecture seule, toujours à jour : on la donne à ``flatten``.
        self._definitions_view: Mapping[str, Circuit] = MappingProxyType(
            self._definitions
        )

    @property
    def limits(self) -> LibraryLimits:
        """Renvoie les limites d'entrées et de sorties des composants."""
        return self._limits

    # --- Enregistrer ----------------------------------------------------------

    def register(self, circuit: Circuit) -> Registration:
        """Enregistre un circuit : nouvelle découverte, record, ou déjà connu.

        Le circuit donné n'est pas modifié. Un circuit refusé (sans sortie, trop
        grand, instable, ou qui pose un composant inconnu) laisse la bibliothèque
        inchangée.
        """
        candidate = self._prepare(circuit)
        existing = self._by_signature.get(candidate.form.signature)
        if existing is None:
            return self._add_new(candidate)
        if candidate.cost < self.cost(existing):
            return self._replace(existing, candidate)
        return Registration(Outcome.KNOWN, existing)

    def _prepare(self, circuit: Circuit) -> _Candidate:
        """Contrôle le circuit, le nettoie, puis calcule son coût et sa signature."""
        self._check_size(circuit)
        return self._analyze(remove_useless_nodes(circuit))

    def _analyze(self, circuit: Circuit) -> _Candidate:
        """Aplatit le circuit, refuse l'instable, puis calcule coût et signature.

        Un circuit dont la batterie de séquences révèle une mémoire a une signature
        séquentielle ; les autres ont leur table de vérité.
        """
        flat = flatten(circuit, self._definitions_view)
        input_count = len(circuit.inputs())
        battery = run_battery(flat)
        if battery is not None and battery.status is Status.UNSTABLE:
            raise UnstableCircuitError(
                "Le circuit oscille pendant la batterie de séquences : il n'a pas de "
                "signature et ne peut pas devenir un composant."
            )
        if battery is not None and battery.memory:
            form: CanonicalForm | SequentialForm = sequential_form(battery, input_count)
            return _Candidate(circuit, flat.nand_count(), form)
        table = truth_table(flat)
        if table.status is not Status.STABLE:
            raise UnstableCircuitError(
                "Le circuit est instable (une sortie change encore après T_max + 1 "
                "tops) : il n'a pas de signature et ne peut pas devenir un composant."
            )
        form = canonical_form(table, input_count)
        return _Candidate(circuit, flat.nand_count(), form)

    def _check_size(self, circuit: Circuit) -> None:
        """Refuse un circuit sans sortie, ou avec trop d'entrées ou de sorties."""
        input_count, output_count = len(circuit.inputs()), len(circuit.outputs())
        if output_count == 0:
            raise NoOutputError("Un circuit sans sortie ne peut pas devenir composant.")
        limits = self._limits
        if limits.max_inputs is not None and input_count > limits.max_inputs:
            raise ComponentTooLargeError(
                f"Le circuit a {input_count} entrées, la limite est "
                f"{limits.max_inputs}."
            )
        if limits.max_outputs is not None and output_count > limits.max_outputs:
            raise ComponentTooLargeError(
                f"Le circuit a {output_count} sorties, la limite est "
                f"{limits.max_outputs}."
            )

    def _add_new(self, candidate: _Candidate) -> Registration:
        """Ajoute un nouveau composant, avec son nom connu ou un numéro."""
        signature = candidate.form.signature
        name = known_name(signature) if isinstance(signature, Signature) else None
        if name is None or name in self._components:
            name = self._fresh_name()
        self._components[name] = Component(
            name, candidate.circuit, signature, candidate.form.input_order
        )
        self._definitions[name] = candidate.circuit
        self._by_signature[signature] = name
        return Registration(Outcome.NEW, name)

    def _replace(self, name: str, candidate: _Candidate) -> Registration:
        """Remplace la définition d'un composant par un circuit plus petit.

        Les entrées du nouveau circuit sont réordonnées pour garder l'ordre des
        broches du composant : les circuits qui l'utilisent déjà ne changent pas de
        comportement.
        """
        old = self._components[name]
        order = _match_input_order(old.input_order, candidate.form.input_order)
        circuit = candidate.circuit.with_inputs_reordered(order)
        self._components[name] = Component(
            name, circuit, old.signature, old.input_order
        )
        self._definitions[name] = circuit
        return Registration(Outcome.RECORD, name)

    def _fresh_name(self) -> str:
        """Donne le prochain nom numéroté libre : C-001, C-002...

        Un nom déjà pris est sauté : c'est ce qui fait continuer la numérotation après
        un rechargement.
        """
        while True:
            name = _UNNAMED_FORMAT.format(number=self._next_number)
            self._next_number += 1
            if name not in self._components:
                return name

    # --- Lire -----------------------------------------------------------------

    def names(self) -> tuple[str, ...]:
        """Renvoie les noms des composants.

        L'ordre est celui où ils sont apparus ; après un rechargement depuis un dossier,
        c'est l'ordre alphabétique des fichiers.
        """
        return tuple(self._components)

    def has_signature(self, signature: Signature | SequentialSignature) -> bool:
        """Dit si un composant de la bibliothèque a déjà cette signature."""
        return signature in self._by_signature

    def component(self, name: str) -> Component:
        """Renvoie le composant demandé, ou lève ``UnknownComponentNameError``."""
        try:
            return self._components[name]
        except KeyError:
            raise UnknownComponentNameError(
                f"La bibliothèque n'a pas de composant nommé {name!r}."
            ) from None

    def cost(self, name: str) -> int:
        """Renvoie le coût d'un composant : ses NAND après aplatissement.

        Recalculé à chaque appel : si un composant qu'il utilise a été remplacé par
        une version plus petite, son coût baisse aussi.
        """
        return flat_nand_count(self.component(name).circuit, self._definitions_view)

    def definitions(self) -> Mapping[str, Circuit]:
        """Renvoie, en lecture seule, la définition de chaque composant par son nom."""
        return self._definitions_view

    def instantiate(self, circuit: Circuit, name: str) -> int:
        """Pose un composant de la bibliothèque dans un circuit et renvoie son nœud."""
        definition = self.component(name).circuit
        return circuit.add_component_node(
            name, len(definition.inputs()), len(definition.outputs())
        )

    # --- Fichiers JSON --------------------------------------------------------

    def save(self, directory: Path) -> None:
        """Écrit chaque composant dans ``<dossier>/<nom>.json`` (le dossier est créé).

        Les fichiers existants du même nom sont remplacés : sauvegarder après un
        record écrit donc la version la plus petite.
        """
        directory.mkdir(parents=True, exist_ok=True)
        for name, component in self._components.items():
            path = directory / f"{name}{_FILE_SUFFIX}"
            path.write_text(circuit_to_json(name, component.circuit), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path, limits: LibraryLimits | None = None) -> Self:
        """Relit une bibliothèque depuis un dossier de fichiers ``<nom>.json``.

        Rien n'est cru sur parole : chaque composant est revérifié comme à
        l'enregistrement (références, boucles, instabilité, doublons de signature,
        limites). Au moindre problème, ``LibraryFormatError`` est levée et aucune
        bibliothèque n'est rendue.
        """
        if not directory.is_dir():
            raise LibraryFormatError(f"{directory} n'est pas un dossier.")
        circuits: dict[str, Circuit] = {}
        for path in sorted(directory.glob(f"*{_FILE_SUFFIX}")):
            name, circuit = _read_component_file(path)
            circuits[name] = circuit
        library = cls(limits)
        library._restore(circuits)
        return library

    def _restore(self, circuits: Mapping[str, Circuit]) -> None:
        """Remplit une bibliothèque vide avec des définitions lues dans des fichiers."""
        self._definitions.update(circuits)  # tous d'abord : ils peuvent se référencer
        for name, circuit in circuits.items():
            try:
                self._restore_one(name, circuit)
            except LibraryFormatError:
                raise
            except (FlattenError, LibraryError) as error:
                raise LibraryFormatError(f"Composant {name!r} : {error}") from error

    def _restore_one(self, name: str, circuit: Circuit) -> None:
        """Revérifie un composant lu dans un fichier, puis le range."""
        self._check_size(circuit)
        candidate = self._analyze(circuit)
        signature = candidate.form.signature
        twin = self._by_signature.get(signature)
        if twin is not None:
            raise LibraryFormatError(
                f"Composant {name!r} : même fonction que {twin!r} (une seule "
                "découverte par signature)."
            )
        self._components[name] = Component(
            name, circuit, signature, candidate.form.input_order
        )
        self._by_signature[signature] = name


def _read_component_file(path: Path) -> tuple[str, Circuit]:
    """Lit un fichier de composant ; son nom doit être celui du fichier."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise LibraryFormatError(
            f"{path.name} : fichier illisible ({error})."
        ) from error
    try:
        name, circuit = circuit_from_json(text)
    except LibraryFormatError as error:
        raise LibraryFormatError(f"{path.name} : {error}") from error
    if name != path.stem:
        raise LibraryFormatError(
            f"{path.name} : le nom {name!r} dans le fichier ne correspond pas "
            "au nom du fichier."
        )
    return name, circuit


def _match_input_order(
    stored_order: tuple[int, ...], new_order: tuple[int, ...]
) -> tuple[int, ...]:
    """Trouve l'ordre d'entrées qui colle un nouveau circuit à un composant enregistré.

    Les deux ordres mènent à la même forme canonique : l'entrée canonique j est
    l'entrée ``stored_order[j]`` du composant, et l'entrée ``new_order[j]`` du nouveau
    circuit. L'entrée s du composant doit donc être jouée par l'entrée
    ``new_order[j]`` du nouveau circuit, avec ``stored_order[j] = s``.
    """
    result = [0] * len(stored_order)
    for canonical_input, stored_input in enumerate(stored_order):
        result[stored_input] = new_order[canonical_input]
    return tuple(result)
