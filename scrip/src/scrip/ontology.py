"""Optional semantic vocabulary for the facts layer.

The ontology is deliberately small and file-native. If ``vault/ontology.yaml`` is
absent, facts behave exactly as before. If present, it constrains selected free
text fields and can canonicalize claim predicates via aliases.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import DataError

try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader

_ONTOLOGY_KEYS = frozenset(
    ("entity_kinds", "edge_kinds", "claim_predicates", "predicate_aliases")
)


@dataclass(frozen=True)
class Ontology:
    entity_kinds: frozenset[str] = frozenset()
    edge_kinds: frozenset[str] = frozenset()
    claim_predicates: frozenset[str] = frozenset()
    predicate_aliases: dict[str, str] | None = None

    @property
    def active(self) -> bool:
        return bool(
            self.entity_kinds
            or self.edge_kinds
            or self.claim_predicates
            or self.predicate_aliases
        )

    def canonical_claim_predicate(self, predicate: str, index: int) -> str:
        aliases = self.predicate_aliases or {}
        canonical = aliases.get(predicate, predicate)
        if self.claim_predicates and canonical not in self.claim_predicates:
            raise DataError(
                f"record {index}: predicate {predicate!r} is not in "
                f"vault/ontology.yaml claim_predicates"
            )
        return canonical

    def validate_entity_kind(self, kind: str, index: int) -> None:
        if self.entity_kinds and kind not in self.entity_kinds:
            raise DataError(
                f"record {index}: entity kind {kind!r} is not in "
                f"vault/ontology.yaml entity_kinds"
            )

    def validate_edge_kind(self, kind: str, index: int) -> None:
        if self.edge_kinds and kind not in self.edge_kinds:
            raise DataError(
                f"record {index}: edge kind {kind!r} is not in "
                f"vault/ontology.yaml edge_kinds"
            )

    def summary(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "entity_kinds": sorted(self.entity_kinds),
            "edge_kinds": sorted(self.edge_kinds),
            "claim_predicates": sorted(self.claim_predicates),
            "predicate_aliases": dict(sorted((self.predicate_aliases or {}).items())),
        }


def ontology_path(root: Path) -> Path:
    return root / "vault" / "ontology.yaml"


def load(root: Path) -> Ontology:
    path = ontology_path(root)
    if not path.exists():
        return Ontology()
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=SafeLoader)
    except yaml.YAMLError as e:
        raise DataError(f"invalid vault/ontology.yaml: {e}") from e
    if data is None:
        return Ontology()
    if not isinstance(data, dict):
        raise DataError("invalid vault/ontology.yaml: expected a mapping")
    _check_known_keys(data)

    entity_kinds = _string_set(data, "entity_kinds")
    edge_kinds = _string_set(data, "edge_kinds")
    claim_predicates = _string_set(data, "claim_predicates")
    predicate_aliases = _string_map(data, "predicate_aliases")
    if claim_predicates:
        for alias, target in predicate_aliases.items():
            if target not in claim_predicates:
                raise DataError(
                    "invalid vault/ontology.yaml: predicate_aliases target "
                    f"{target!r} for {alias!r} is not in claim_predicates"
                )

    return Ontology(
        entity_kinds=frozenset(entity_kinds),
        edge_kinds=frozenset(edge_kinds),
        claim_predicates=frozenset(claim_predicates),
        predicate_aliases=predicate_aliases,
    )


def _check_known_keys(data: dict) -> None:
    unknown = [key for key in data if not isinstance(key, str) or key not in _ONTOLOGY_KEYS]
    if unknown:
        rendered = ", ".join(repr(key) for key in unknown)
        expected = ", ".join(sorted(_ONTOLOGY_KEYS))
        raise DataError(
            f"invalid vault/ontology.yaml: unknown key(s): {rendered}; expected one of: "
            f"{expected}"
        )


def _string_set(data: dict, key: str) -> set[str]:
    value = data.get(key, [])
    if value is None:
        return set()
    if not isinstance(value, list):
        raise DataError(f"invalid vault/ontology.yaml: {key} must be a list of strings")
    out: set[str] = set()
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise DataError(
                f"invalid vault/ontology.yaml: {key}[{i}] must be a non-empty string"
            )
        out.add(item.strip())
    return out


def _string_map(data: dict, key: str) -> dict[str, str]:
    value = data.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DataError(
            f"invalid vault/ontology.yaml: {key} must be a mapping of strings to strings"
        )
    out: dict[str, str] = {}
    for raw_k, raw_v in value.items():
        if not isinstance(raw_k, str) or not raw_k.strip():
            raise DataError(
                f"invalid vault/ontology.yaml: {key} keys must be non-empty strings"
            )
        if not isinstance(raw_v, str) or not raw_v.strip():
            raise DataError(
                f"invalid vault/ontology.yaml: {key}.{raw_k} must be a non-empty string"
            )
        out[raw_k.strip()] = raw_v.strip()
    return out
