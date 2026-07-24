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

#: The two capabilities ADR-0048's tools advertise, the vocabulary these tests
#: resolve onto.
ADVERTISED = ("recall_memory", "report_current_time")


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
        ("recall", "recall_memory"),
        ("search_memory", "recall_memory"),
        ("retrieve_memory", "recall_memory"),
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
    ``recall_memory`` advertised the target is absent, so nothing is rewritten and
    the emitted string passes through to an honest ``NO_CAPABLE_TOOL``.
    """
    assert resolve_capability("get_time", ("recall_memory",)) == "get_time"


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


def test_empty_advertised_vocabulary_rewrites_nothing() -> None:
    """With no tools registered, every capability passes through unchanged."""
    assert resolve_capability("get_time", ()) == "get_time"
    assert resolve_capability("report_current_time", ()) == "report_current_time"


def test_a_write_synonym_is_not_aliased_onto_the_read_capability() -> None:
    """ "remember" is a store-intent, not a synonym of the read-only recall.

    ADR-0048 ships no memory writer, and aliasing a write-shaped capability onto
    ``recall_memory`` would fire the wrong tool — the exact hazard the layer
    disclaims — so ``remember`` stays unresolved and skips ``NO_CAPABLE_TOOL``.
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
