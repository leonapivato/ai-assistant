"""The upgrade of an episode stored before ADR-0353 into its record (ADR-0353 §9:6).

Mechanical, with no model (ADR-0326 §4:1). Each stored understanding version loses its
**retired fields** — ``meaning_ground``, ``references``, ``relationships``,
``unresolved`` and ``answers`` — by the owner's ruling under ADR-0326 §4:4: "I think its
fine for a clean wipe too if its easier". What a version drew on survives: the referents
of its references and of its relationships join its ``meaning_referents``, after the
meaning's own and in the order the version holds them, each added once and none added
that the version already holds. What goes is the ground, each reference's phrase, each
relationship's statement and ground, the unresolved matters and the answer pointers.
Nothing else of the version changes, and no episode, memory, matter or other record is
dropped.

A pure function of the stored record, so the store applies it inside its own
transaction and a test applies it to a dict. It is **idempotent**: a record whose every
version is already in ADR-0353's shape comes back unchanged and reports no change.
"""

from __future__ import annotations

import json
from typing import Any, Final

#: ADR-0353 §9:5's retired fields, which §9:6 drops from every stored version.
RETIRED_FIELDS: Final = ("meaning_ground", "references", "relationships", "unresolved", "answers")


def _key(referent: object) -> str:
    """One referent's identity as stored: two referents are one where every field is equal."""
    return json.dumps(referent, sort_keys=True, ensure_ascii=True)


def _drawn_on(version: dict[str, Any]) -> list[Any]:
    """The referents of a version's references and relationships, in the order held."""
    found: list[Any] = []
    for name in ("references", "relationships"):
        held = version.get(name)
        if not isinstance(held, list):
            continue
        for one in held:
            referents = one.get("referents") if isinstance(one, dict) else None
            if isinstance(referents, list):
                found.extend(referents)
    return found


def understood_version(version: dict[str, Any]) -> bool:
    """Carry one stored version to ADR-0353 §9's form, in place.

    Returns:
        Whether anything changed: ``False`` for a version holding no retired field.
    """
    if not any(name in version for name in RETIRED_FIELDS):
        return False
    own = version.get("meaning_referents", [])
    if isinstance(own, list):
        kept = list(own)
        seen = {_key(one) for one in kept}
        for referent in _drawn_on(version):
            key = _key(referent)
            if key not in seen:
                seen.add(key)
                kept.append(referent)
        version["meaning_referents"] = kept
    for name in RETIRED_FIELDS:
        version.pop(name, None)
    return True


def understood_episode(stored: dict[str, Any]) -> bool:
    """Carry every understanding version ``stored`` records to ADR-0353 §9's form.

    Args:
        stored: One stored record, decoded from its JSON. A record with no processing
            record, or whose versions are not the shapes a build wrote, is left alone
            where it cannot be read: the store's decode, which follows, judges a shape
            this does not know.

    Returns:
        Whether anything changed, so the store rewrites only a record that moved.
    """
    processing = stored.get("processing_record")
    versions = processing.get("understanding") if isinstance(processing, dict) else None
    if not isinstance(versions, list):
        return False
    changed = False
    for version in versions:
        if isinstance(version, dict) and understood_version(version):
            changed = True
    return changed
