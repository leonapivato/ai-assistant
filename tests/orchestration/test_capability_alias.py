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
