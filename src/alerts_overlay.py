"""Apply the operator-authored alerts diff to relation-supplied rules.

See specs/adr/0006-diff-document-schema.md for the schema and
specs/adr/0005-charm-merge-pipeline.md for the pipeline this slots into.

Pure functions only — no I/O, no Pebble — so this is unit-testable without
charm scaffolding.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class OverlayError(Exception):
    """Raised on schema-invalid input or unresolvable match (ambiguous, duplicate)."""


@dataclass
class Diff:
    """Parsed + validated diff document. Operate on this, not raw YAML."""

    remove: List[Dict[str, Any]] = field(default_factory=list)
    patch: List[Dict[str, Any]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.remove and not self.patch


def load_diff(yaml_str: Optional[str]) -> Optional[Diff]:
    """Parse and validate the diff document.

    `None` or empty input → `None` (no overlay; valid state).
    Schema violations → `OverlayError`.
    """
    if not yaml_str or not yaml_str.strip():
        return None

    try:
        doc = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        raise OverlayError(f"diff.yaml is not valid YAML: {e}") from e

    if doc is None:
        return None
    if not isinstance(doc, dict):
        raise OverlayError("diff.yaml must be a mapping at the top level")

    version = doc.get("schemaVersion")
    if version != SCHEMA_VERSION:
        raise OverlayError(
            f"unsupported schemaVersion {version!r}; expected {SCHEMA_VERSION}"
        )

    add = doc.get("add") or {}
    if add and (add.get("groups") or []):
        raise OverlayError("'add' is not yet implemented")

    remove = _validate_remove(doc.get("remove") or [])
    patch = _validate_patch(doc.get("patch") or [])
    _check_no_conflicting_patches(patch)

    return Diff(remove=remove, patch=patch)


def _validate_match(match: Any, *, where: str) -> str:
    if not isinstance(match, dict):
        raise OverlayError(f"{where}: 'match' must be a mapping")
    if list(match.keys()) != ["alert"]:
        raise OverlayError(
            f"{where}: 'match' must contain exactly one key 'alert' in MVP "
            f"(got {sorted(match.keys())})"
        )
    name = match["alert"]
    if not isinstance(name, str) or not name:
        raise OverlayError(f"{where}: 'match.alert' must be a non-empty string")
    return name


def _validate_remove(entries: Any) -> List[Dict[str, Any]]:
    if not isinstance(entries, list):
        raise OverlayError("'remove' must be a list")
    out = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise OverlayError(f"remove[{i}] must be a mapping")
        _validate_match(entry.get("match"), where=f"remove[{i}]")
        out.append(entry)
    return out


_PATCH_SET_KEYS = {"for", "expr", "labels", "annotations"}


def _validate_patch(entries: Any) -> List[Dict[str, Any]]:
    if not isinstance(entries, list):
        raise OverlayError("'patch' must be a list")
    out = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise OverlayError(f"patch[{i}] must be a mapping")
        _validate_match(entry.get("match"), where=f"patch[{i}]")

        set_block = entry.get("set")
        if not isinstance(set_block, dict) or not set_block:
            raise OverlayError(f"patch[{i}]: 'set' must be a non-empty mapping")

        unknown = set(set_block.keys()) - _PATCH_SET_KEYS
        if unknown:
            raise OverlayError(
                f"patch[{i}]: unsupported keys in 'set': {sorted(unknown)}"
            )

        for k in ("labels", "annotations"):
            if k in set_block and not isinstance(set_block[k], dict):
                raise OverlayError(f"patch[{i}]: 'set.{k}' must be a mapping")
        for k in ("for", "expr"):
            if k in set_block and not isinstance(set_block[k], str):
                raise OverlayError(f"patch[{i}]: 'set.{k}' must be a string")

        out.append(entry)
    return out


def _check_no_conflicting_patches(entries: List[Dict[str, Any]]) -> None:
    seen = set()
    for entry in entries:
        name = entry["match"]["alert"]
        if name in seen:
            raise OverlayError(
                f"two 'patch' entries both target alert {name!r}; "
                f"the UI should have coalesced them"
            )
        seen.add(name)


def apply(
    base: Dict[str, Dict[str, Any]],
    diff: Optional[Diff],
) -> Dict[str, Dict[str, Any]]:
    """Apply `diff` to `base` and return the merged result.

    `base` shape: `{topology_identifier: rules_file_dict}`, where
    `rules_file_dict` is the standard Prometheus YAML format
    (`{"groups": [{"name": ..., "rules": [...]}, ...]}`).

    Returns a deep copy with `remove` then `patch` applied (D5).
    A match that resolves to multiple rules → `OverlayError` (D4).
    A match that resolves to zero rules → logged, not raised (D3).
    """
    if diff is None or diff.is_empty():
        return copy.deepcopy(base)

    merged = copy.deepcopy(base)

    # D5: remove before patch.
    for entry in diff.remove:
        name = entry["match"]["alert"]
        matched = _find_alert_locations(merged, name)
        if len(matched) > 1:
            raise OverlayError(
                f"ambiguous match: {len(matched)} rules named {name!r} "
                f"(remove); MVP match only supports the alert name"
            )
        if not matched:
            logger.warning("overlay remove: no rule named %r", name)
            continue
        topo, group_idx, rule_idx = matched[0]
        del merged[topo]["groups"][group_idx]["rules"][rule_idx]

    for entry in diff.patch:
        name = entry["match"]["alert"]
        matched = _find_alert_locations(merged, name)
        if len(matched) > 1:
            raise OverlayError(
                f"ambiguous match: {len(matched)} rules named {name!r} "
                f"(patch); MVP match only supports the alert name"
            )
        if not matched:
            logger.warning("overlay patch: no rule named %r", name)
            continue
        topo, group_idx, rule_idx = matched[0]
        rule = merged[topo]["groups"][group_idx]["rules"][rule_idx]
        _apply_patch_to_rule(rule, entry["set"])

    return merged


def _find_alert_locations(
    rules_by_topo: Dict[str, Dict[str, Any]],
    alert_name: str,
):
    """Return all (topology, group_index, rule_index) tuples for `alert_name`."""
    hits = []
    for topo, rules_file in rules_by_topo.items():
        groups = (rules_file or {}).get("groups") or []
        for g_idx, group in enumerate(groups):
            for r_idx, rule in enumerate(group.get("rules") or []):
                if rule.get("alert") == alert_name:
                    hits.append((topo, g_idx, r_idx))
    return hits


def _apply_patch_to_rule(rule: Dict[str, Any], set_block: Dict[str, Any]) -> None:
    """Mutate `rule` per D2: replace scalars, deep-merge labels/annotations."""
    for scalar in ("for", "expr"):
        if scalar in set_block:
            rule[scalar] = set_block[scalar]
    for mapping in ("labels", "annotations"):
        if mapping in set_block:
            existing = rule.get(mapping) or {}
            existing.update(set_block[mapping])
            rule[mapping] = existing
