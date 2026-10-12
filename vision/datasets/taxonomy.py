"""Unified taxonomy: source folder/label -> espece / etat / classe (docs/02-donnees.md §2)."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

TAXONOMY_PATH = Path(__file__).with_name("taxonomy.yaml")
ETATS = ("sain", "maladie", "nuisible", "carence", "virus")
SOURCES = ("plantvillage", "ccmt", "plantdoc", "serre")
_CLASSE_RE = re.compile(r"^[a-z_]+/[a-z]+/[a-z0-9_]+$")


class TaxonomyError(ValueError):
    """Invalid taxonomy file."""


class UnmappedError(KeyError):
    """A source folder or label has no entry in the taxonomy."""


@dataclass(frozen=True)
class ClassInfo:
    classe: str
    espece: str
    etat: str
    ambigu: bool

    @property
    def sante(self) -> str:
        return "sain" if self.etat == "sain" else "anormal"


@dataclass(frozen=True)
class Taxonomy:
    version: int
    classes: dict[str, ClassInfo]
    _lookup: dict[tuple[str, str], ClassInfo]

    def lookup(self, source: str, key: str) -> ClassInfo:
        try:
            return self._lookup[(source, key)]
        except KeyError:
            raise UnmappedError(f"{source}: {key!r} absent de la taxonomie") from None

    def has(self, source: str, key: str) -> bool:
        return (source, key) in self._lookup

    def keys(self, source: str) -> set[str]:
        return {k for s, k in self._lookup if s == source}

    @property
    def especes(self) -> set[str]:
        return {c.espece for c in self.classes.values()}


def load_taxonomy(path: Path = TAXONOMY_PATH) -> Taxonomy:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw.get("version"), int):
        raise TaxonomyError("champ `version` entier manquant")

    classes: dict[str, ClassInfo] = {}
    lookup: dict[tuple[str, str], ClassInfo] = {}
    for classe, entry in raw["classes"].items():
        if not _CLASSE_RE.match(classe):
            raise TaxonomyError(f"{classe!r} : format attendu espece/etat/nom")
        espece, etat, _ = classe.split("/")
        if etat not in ETATS:
            raise TaxonomyError(f"{classe!r} : etat {etat!r} hors de {ETATS}")
        info = ClassInfo(classe, espece, etat, bool(entry.get("ambigu", False)))
        classes[classe] = info
        for source, keys in (entry.get("sources") or {}).items():
            if source not in SOURCES:
                raise TaxonomyError(f"{classe!r} : source inconnue {source!r}")
            for key in keys:
                if (source, key) in lookup:
                    other = lookup[(source, key)].classe
                    raise TaxonomyError(f"{source}: {key!r} mappé à {other!r} et {classe!r}")
                lookup[(source, key)] = info
    return Taxonomy(raw["version"], classes, lookup)
