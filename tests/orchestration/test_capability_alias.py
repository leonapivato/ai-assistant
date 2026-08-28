"""The selection-time capability alias layer (ADR-0053).

Unit tests for the pure resolver, over the two properties that keep it honest: a
rewrite only ever lands on an advertised capability, and anything unrecognised
passes through unchanged so selection reports ``NO_CAPABLE_TOOL`` truthfully. The
end-to-end behaviour — that a resolved capability actually selects and runs a
wired tool — is asserted against the real ``StepRunner`` in ``test_runner.py``.
"""

from __future__ import annotations

import pytest

from ai_assistant.orchestration.capability_alias import (
    CAPABILITY_ALIASES,
    resolve_capability,
)

#: The capability the shipped local tool advertises, the vocabulary these tests
#: resolve onto. One name since ADR-0208 §1 unregistered ``recall_memory``; the
#: configured egress tool is a deployment fact rather than a package one, so it is
#: deliberately absent from the *default* vocabulary these unit cases resolve over.
ADVERTISED = ("report_current_time",)

#: The capabilities the eight rows ADR-0208 §2 deleted used to serve, plus the
#: capability the tool itself advertised.
DELETED_MEMORY_SYNONYMS = (
    "recall",
    "recall_memories",
    "search_memory",
    "search_memories",
    "retrieve_memory",
    "memory_recall",
    "memory_search",
    "lookup_memory",
)


def test_an_exact_advertised_capability_is_returned_unchanged() -> None:
    """The common case pays no folding and no table lookup."""
    assert resolve_capability("report_current_time", ADVERTISED) == "report_current_time"


@pytest.mark.parametrize(
    "emitted",
    ["Report_Current_Time", "report-current-time", "REPORT CURRENT TIME", "report_current_time_"],
)
def test_a_case_or_separator_variant_folds_onto_the_advertised_name(emitted: str) -> None:
    """Surface folding matches a trivial rendering variant to the same name."""
    assert resolve_capability(emitted, ADVERTISED) == "report_current_time"


@pytest.mark.parametrize(
    ("emitted", "expected"),
    [
        ("get_time", "report_current_time"),
        ("tell_time", "report_current_time"),
        ("what_time_is_it", "report_current_time"),
        ("current_time", "report_current_time"),
    ],
)
def test_a_curated_synonym_resolves_onto_its_advertised_target(emitted: str, expected: str) -> None:
    """A hand-listed synonym maps onto the capability its tool advertises."""
    assert resolve_capability(emitted, ADVERTISED) == expected


@pytest.mark.parametrize("emitted", ["Get Time", "get-time", "GET_TIME"])
def test_a_surface_variant_of_a_synonym_folds_before_the_table_lookup(emitted: str) -> None:
    """A rendering variant of a listed synonym resolves the same as the synonym."""
    assert resolve_capability(emitted, ADVERTISED) == "report_current_time"


def test_an_unknown_capability_is_returned_unchanged() -> None:
    """Anything not recognised reaches ``find`` verbatim, so it skips honestly."""
    assert resolve_capability("delete_everything", ADVERTISED) == "delete_everything"


def test_a_synonym_is_inert_when_its_target_is_not_advertised() -> None:
    """A rewrite never lands on a capability no tool serves.

    ``get_time`` is a curated synonym of ``report_current_time``, but with only
    ``send_email`` advertised the target is absent, so nothing is rewritten and the
    emitted string passes through to an honest ``NO_CAPABLE_TOOL``.
    """
    assert resolve_capability("get_time", ("send_email",)) == "get_time"


def test_resolution_lands_only_on_an_advertised_capability_or_the_input() -> None:
    """Every branch returns an advertised name or the caller's own string.

    The property the whole layer rests on: it never invents a third value.
    """
    advertised_set = set(ADVERTISED)
    for emitted in [
        "report_current_time",
        "Report Current Time",
        "get_time",
        "search_memory",
        "delete_everything",
        "",
    ]:
        resolved = resolve_capability(emitted, ADVERTISED)
        assert resolved in advertised_set or resolved == emitted


def test_every_curated_target_is_a_capability_the_shipped_tools_advertise() -> None:
    """The table only ever aims at ADR-0048's advertised vocabulary.

    A target that is never advertised would be dead weight and a latent way to
    aim a synonym at nothing; keeping the table honest is a unit-test concern.
    """
    assert set(CAPABILITY_ALIASES.values()) <= set(ADVERTISED)


def test_no_row_targets_the_departed_memory_capability() -> None:
    """ADR-0208 §2's deletion, asserted over the table's *values* (ADR-0208 §6).

    Over the values rather than the keys, so a surviving row fails this test
    whatever key it is written under — which is why §6 owes it separately from the
    selection-path test in ``tests/tools/test_builtin.py``. That one cannot see a
    row left behind: with the tool unbound, ADR-0053's live-registry check makes
    every surviving row inert, selection reports ``NO_CAPABLE_TOOL`` anyway, and
    eight dead claims stand while every other test passes.

    This pins §2's deletion and **nothing wider**. It is not a rule that the table
    may hold no inert entry — ADR-0053 declined to make that rule and ADR-0208 §6
    declines to make it for ADR-0053.
    """
    assert "recall_memory" not in set(CAPABILITY_ALIASES.values())


@pytest.mark.parametrize("emitted", DELETED_MEMORY_SYNONYMS)
def test_a_deleted_memory_synonym_is_no_longer_a_key(emitted: str) -> None:
    """Each of the eight rows is gone, and its capability resolves to itself.

    The key-side statement of the same deletion: a planner emitting ``recall`` or
    ``search_memory`` gets its own string back, so selection reports
    ``NO_CAPABLE_TOOL`` about the name the plan actually named (ADR-0037 §1,
    ADR-0208 §3) rather than about a capability nothing advertises.
    """
    assert emitted not in CAPABILITY_ALIASES
    assert resolve_capability(emitted, ADVERTISED) == emitted


def test_empty_advertised_vocabulary_rewrites_nothing() -> None:
    """With no tools registered, every capability passes through unchanged."""
    assert resolve_capability("get_time", ()) == "get_time"
    assert resolve_capability("report_current_time", ()) == "report_current_time"


def test_a_write_synonym_is_not_aliased_onto_a_memory_capability() -> None:
    """ "remember" is a store-intent, and no row has ever carried it.

    ADR-0048 §1's deferral of a memory writer stands untouched (ADR-0208 §8), and
    ADR-0053's refusal to alias a store-intent onto a read stands with it — now
    vacuously, since ADR-0208 §2 removed the read it would have fired. Either way
    ``remember`` stays unresolved and skips ``NO_CAPABLE_TOOL``.
    """
    assert "remember" not in CAPABILITY_ALIASES
    assert resolve_capability("remember", ADVERTISED) == "remember"


def test_a_fold_two_advertised_capabilities_share_is_left_unresolved() -> None:
    """A normalized collision is ambiguous, so nothing is ranked (ADR-0037 §1).

    Both ``delete-user`` and ``delete_user`` fold to ``delete_user``; an emitted
    ``DELETE USER`` matches neither exactly, and resolving it onto one would pick a
    side-effecting tool over another by lexical accident. It passes through
    unchanged instead.
    """
    colliding = ("delete-user", "delete_user")
    assert resolve_capability("DELETE USER", colliding) == "DELETE USER"
    # An exact name is still returned as itself — the collision only blocks the
    # surface-variant branch, never an exact match.
    assert resolve_capability("delete_user", colliding) == "delete_user"
    assert resolve_capability("delete-user", colliding) == "delete-user"


def test_a_unicode_letter_is_not_treated_as_a_separator() -> None:
    """Surface folding keeps Unicode letters, so it never rewrites a word.

    An ASCII-only rule would fold ``deleteéaccount`` onto ``delete_account`` and
    select a tool the plan never named; ``é`` is a letter, so the two stay
    distinct and the emitted string passes through unchanged.
    """
    assert resolve_capability("deleteéaccount", ("delete_account",)) == "deleteéaccount"
    # A genuine separator around a Unicode word still folds, and a Unicode word
    # advertised is still matched by its own case variant.
    assert resolve_capability("Café-Search", ("café_search",)) == "café_search"


def test_a_casefold_combining_mark_does_not_fold_a_letter_away() -> None:
    """``İ`` casefolds to ``i`` plus a combining dot; the dot is kept, not dropped.

    Treating the combining mark as a separator would fold ``İ`` onto a plain
    ``i`` and select its tool — rewriting one word into another. Keeping marks
    keeps the two distinct, so the emitted string passes through unchanged.
    """
    assert resolve_capability("İ", ("i",)) == "İ"


def test_an_ambiguous_advertised_fold_is_not_rescued_by_the_alias_table() -> None:
    """A variant of advertised names never leapfrogs to a different capability.

    ``get_time`` is both an advertised capability (ambiguously, alongside
    ``get-time``) and a synonym key for ``report_current_time``. An emitted
    ``GET TIME`` folds onto the advertised pair, so it is a variant of *those*
    names — the alias table must not carry it to the time capability instead. The
    fold is ambiguous, so it declines rather than ranking the two advertised sides.
    """
    advertised = ("get-time", "get_time", "report_current_time")
    assert resolve_capability("GET TIME", advertised) == "GET TIME"
    # And when the fold is unambiguous it resolves to that advertised name, still
    # without consulting the alias table's different target.
    assert resolve_capability("Get_Time", ("get_time", "report_current_time")) == "get_time"
