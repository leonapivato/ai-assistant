"""ADR-0277 §2's record checks in scripts/check_citations.py, over constructed corpora.

Each check is pinned in both directions — the case it reports and the case it
must stay silent on — and at the tier §2 assigns it, because the tier is the
decision: a Tier 1 finding fails the gate (the corpus test in
``test_adr_citations_corpus.py``), a Tier 2 finding never does. The repeated-clause
and stale-note checks are pinned as ADR-0278 §1 and §2 narrow them, including every
case ADR-0278 §4's first clause lists, and with the pass counts those sections
require the report to state.

Driven as a subprocess over ``--root``, as ``test_check_citations.py`` drives
the rest of the checker, so what is pinned is the script's real output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPT = Path(__file__).parents[2] / "scripts" / "check_citations.py"


def _adr(
    number: int,
    *,
    status: str = "Accepted",
    body: str = "",
    header: str = "",
    context: str = "Why.",
) -> str:
    return (
        f"# {number}. Decision {number}\n\n- Status: {status}\n- Date: 2026-09-26\n{header}\n"
        f"## Context\n\n{context}\n\n## Decision\n\n{body}\n\n## Consequences\n\nSome.\n"
    )


_MARKED = (
    "### 1. One\n\n> **Normative.** Rule one-one.\n\n> **Normative.** Rule one-two.\n\n"
    "### 2. Two\n\n> **Normative.** Rule two-one."
)


def _run(root: Path, adrs: dict[int, str]) -> subprocess.CompletedProcess[str]:
    for number, text in adrs.items():
        path = root / "docs" / "adr" / f"{number:04d}-decision.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    argv = [sys.executable, str(_SCRIPT), "--root", str(root), "--format", "json", "--no-tracker"]
    return subprocess.run(argv, capture_output=True, text=True, check=False)  # noqa: S603


def _report(root: Path, adrs: dict[int, str]) -> dict[str, Any]:
    result = _run(root, adrs)
    assert result.returncode in (0, 1), result.stderr
    report = json.loads(result.stdout)
    assert isinstance(report, dict)
    return report


def _findings(root: Path, adrs: dict[int, str], kind: str) -> list[tuple[int, str, str]]:
    return [
        (int(f["tier"]), str(f["path"]).rsplit("/", 1)[-1][:4], str(f["citation"]))
        for f in _report(root, adrs)["findings"]
        if f["kind"] == kind
    ]


# --- clause identifiers: Tier 1 ---------------------------------------------


def test_an_identifier_that_resolves_is_silent(tmp_path: Path) -> None:
    cites = _adr(2, body="See ADR-0001 §1:2, §2:1 and ADR-0001 §1:1-2.")
    assert _findings(tmp_path, {1: _adr(1, body=_MARKED), 2: cites}, "clause") == []


def test_an_identifier_naming_a_missing_clause_is_tier_1(tmp_path: Path) -> None:
    cites = _adr(2, body="See ADR-0001 §1:3 and ADR-0001 §Context:1.")
    assert _findings(tmp_path, {1: _adr(1, body=_MARKED), 2: cites}, "clause") == [
        (1, "0002", "ADR-0001 §1:3"),
        (1, "0002", "ADR-0001 §Context:1"),
    ]


def test_a_range_with_a_missing_member_is_tier_1(tmp_path: Path) -> None:
    """§2: a range resolves only in full — `§1:1-3` fails on its third member."""
    cites = _adr(2, body="See ADR-0001 §1:1-3.")
    assert _findings(tmp_path, {1: _adr(1, body=_MARKED), 2: cites}, "clause") == [
        (1, "0002", "ADR-0001 §1:1-3")
    ]


def test_a_range_with_a_zero_endpoint_is_tier_1(tmp_path: Path) -> None:
    cites = _adr(2, body="See ADR-0001 §1:0-2.")
    assert _findings(tmp_path, {1: _adr(1, body=_MARKED), 2: cites}, "clause") == [
        (1, "0002", "ADR-0001 §1:0-2")
    ]


def test_a_reversed_range_is_tier_1(tmp_path: Path) -> None:
    cites = _adr(2, body="See ADR-0001 §1:2-1.")
    assert _findings(tmp_path, {1: _adr(1, body=_MARKED), 2: cites}, "clause") == [
        (1, "0002", "ADR-0001 §1:2-1")
    ]


def test_an_identifier_into_a_missing_adr_is_tier_1_even_in_a_gap(tmp_path: Path) -> None:
    """ADR-0090 §1 silences a decision citation into a gap; it cannot silence this.

    0002 is a gap between 0001 and 0003, so ``ADR-0002`` alone is no finding — but
    no clause of an ADR that was never written exists.
    """
    cites = _adr(3, body="See ADR-0002 §1:1.")
    found = _findings(tmp_path, {1: _adr(1, body=_MARKED), 3: cites}, "clause")
    assert found == [(1, "0003", "ADR-0002 §1:1")]


def test_a_fenced_identifier_is_display(tmp_path: Path) -> None:
    cites = _adr(2, body="```text\nADR-0001 §9:9\n```")
    assert _findings(tmp_path, {1: _adr(1, body=_MARKED), 2: cites}, "clause") == []


def test_an_unresolved_identifier_fails_the_run(tmp_path: Path) -> None:
    result = _run(tmp_path, {1: _adr(1, body=_MARKED), 2: _adr(2, body="ADR-0001 §2:2")})
    assert result.returncode == 1


def test_identifiers_are_counted(tmp_path: Path) -> None:
    result = _run(tmp_path, {1: _adr(1, body=_MARKED + "\n\nADR-0001 §1:1, §2:1")})
    assert json.loads(result.stdout)["counts"]["clause"] == 2


def test_a_wrapped_identifier_list_is_checked_in_full(tmp_path: Path) -> None:
    """A soft line break inside a comma list does not hide its later members."""
    cites = _adr(2, body="See ADR-0001 §1:2,\n§1:9 and ADR-0001\n§2:5.")
    assert _findings(tmp_path, {1: _adr(1, body=_MARKED), 2: cites}, "clause") == [
        (1, "0002", "ADR-0001 §1:9"),
        (1, "0002", "ADR-0001 §2:5"),
    ]


def test_an_absurdly_long_ordinal_is_a_finding_not_a_crash(tmp_path: Path) -> None:
    digits = "9" * 5000
    cites = _adr(2, body=f"See ADR-0001 §1:{digits} and ADR-0001 §1:1-{digits}.")
    found = _findings(tmp_path, {1: _adr(1, body=_MARKED), 2: cites}, "clause")
    assert found == [
        (1, "0002", f"ADR-0001 §1:1-{digits}"),
        (1, "0002", f"ADR-0001 §1:{digits}"),
    ]


# --- stale "remains Proposed" notes: Tier 2 ----------------------------------

_NOTE = (
    "- Partially superseded: 2026-09-18 by ADR-0002 — scoped. These take effect on\n"
    "  ratification of ADR-0002, which remains\n  Proposed. Nothing else moves.\n"
)


def test_a_note_saying_a_ratified_adr_remains_proposed_is_tier_2(tmp_path: Path) -> None:
    adrs = {1: _adr(1, header=_NOTE), 2: _adr(2, body=_MARKED)}
    assert _findings(tmp_path, adrs, "stale-note") == [(2, "0001", "ADR-0002 remains Proposed")]


def test_the_backticked_status_is_read_too(tmp_path: Path) -> None:
    note = "- Note: ADR-0002 remains `Proposed` until the owner rules.\n"
    adrs = {1: _adr(1, header=note), 2: _adr(2, body=_MARKED)}
    assert _findings(tmp_path, adrs, "stale-note") == [(2, "0001", "ADR-0002 remains Proposed")]


def test_a_note_that_is_still_true_is_silent(tmp_path: Path) -> None:
    adrs = {1: _adr(1, header=_NOTE), 2: _adr(2, status="Proposed", body=_MARKED)}
    assert _findings(tmp_path, adrs, "stale-note") == []


def test_a_note_quoting_the_phrase_is_not_the_claim(tmp_path: Path) -> None:
    """The correcting note quotes the stale one; nothing names an ADR against the phrase."""
    note = (
        "- Note (2026-09-26): ADR-0002 was ratified, so that note's \"which remains\n"
        '  Proposed" was true when written and is stale.\n'
    )
    adrs = {1: _adr(1, header=note), 2: _adr(2, body=_MARKED)}
    assert _findings(tmp_path, adrs, "stale-note") == []


def test_the_phrase_in_the_body_is_not_a_header_note(tmp_path: Path) -> None:
    body = "ADR-0002 remains Proposed until the owner rules."
    adrs = {1: _adr(1, body=body), 2: _adr(2, body=_MARKED)}
    assert _findings(tmp_path, adrs, "stale-note") == []


def test_a_stale_note_never_fails_the_run(tmp_path: Path) -> None:
    result = _run(tmp_path, {1: _adr(1, header=_NOTE), 2: _adr(2, body=_MARKED)})
    assert result.returncode == 0


# --- a corrected stale note (ADR-0278 §2) --------------------------------------

#: The correcting note's shape, as #2560 wrote it, with the words wrapped.
_CORRECTION = (
    "- Note (2026-09-26): ADR-0002 was\n  ratified on 2026-09-18, so the scoped replacements\n"
    '  recorded above took effect then; that note\'s "which remains Proposed" is stale.\n'
)


def _stale(root: Path, header: str) -> tuple[list[tuple[int, str, str]], int]:
    adrs = {1: _adr(1, header=header), 2: _adr(2, body=_MARKED), 3: _adr(3, body=_MARKED)}
    report = _report(root, adrs)
    found = [
        (int(f["tier"]), str(f["path"]).rsplit("/", 1)[-1][:4], str(f["citation"]))
        for f in report["findings"]
        if f["kind"] == "stale-note"
    ]
    return found, int(report["passed"]["stale-note"])


def test_a_corrected_note_is_counted_and_not_listed(tmp_path: Path) -> None:
    """ADR-0278 §4: a later dated item saying the ADR was ratified corrects it."""
    assert _stale(tmp_path, _NOTE + _CORRECTION) == ([], 1)


def test_a_correcting_note_naming_a_different_adr_leaves_the_stale_note_reported(
    tmp_path: Path,
) -> None:
    """ADR-0278 §4: the correction must name the number the stale note names."""
    other = _CORRECTION.replace("ADR-0002 was", "ADR-0003 was")
    assert _stale(tmp_path, _NOTE + other) == ([(2, "0001", "ADR-0002 remains Proposed")], 0)


def test_a_correction_may_stand_several_items_below(tmp_path: Path) -> None:
    between = "- Partially supersedes: ADR-0003 — something else entirely.\n"
    assert _stale(tmp_path, _NOTE + between + _CORRECTION) == ([], 1)


def test_a_correction_above_the_stale_note_corrects_nothing(tmp_path: Path) -> None:
    """ADR-0278 §2: the correcting item stands *below* the note."""
    assert _stale(tmp_path, _CORRECTION + _NOTE) == (
        [(2, "0001", "ADR-0002 remains Proposed")],
        0,
    )


def test_a_note_cannot_correct_itself(tmp_path: Path) -> None:
    """The stale note's own item is not *a later list item*, dated or not."""
    note = "- Note (2026-09-18): ADR-0002 remains Proposed; ADR-0002 was ratified later.\n"
    assert _stale(tmp_path, note) == ([(2, "0001", "ADR-0002 remains Proposed")], 0)


def test_a_correction_without_a_date_on_its_first_line_corrects_nothing(tmp_path: Path) -> None:
    undated = "- Note: ADR-0002 was ratified\n  on 2026-09-18, so that note is stale.\n"
    assert _stale(tmp_path, _NOTE + undated) == (
        [(2, "0001", "ADR-0002 remains Proposed")],
        0,
    )


def test_the_words_must_follow_the_number_directly(tmp_path: Path) -> None:
    """``ADR-0002, which was ratified`` is not the form §2 names; the miss is benign."""
    indirect = "- Note (2026-09-26): ADR-0002, which was ratified, took effect then.\n"
    assert _stale(tmp_path, _NOTE + indirect) == (
        [(2, "0001", "ADR-0002 remains Proposed")],
        0,
    )


def test_a_correction_in_the_body_is_no_header_note(tmp_path: Path) -> None:
    """ADR-0278 §2: a list item *of the same header*."""
    adrs = {
        1: _adr(1, header=_NOTE, body=_CORRECTION),
        2: _adr(2, body=_MARKED),
    }
    assert _findings(tmp_path, adrs, "stale-note") == [(2, "0001", "ADR-0002 remains Proposed")]


def test_each_stale_note_is_corrected_on_its_own(tmp_path: Path) -> None:
    """Two stale notes, one correction: the uncorrected note is still reported."""
    second = _NOTE.replace("ADR-0002", "ADR-0003")
    assert _stale(tmp_path, _NOTE + second + _CORRECTION) == (
        [(2, "0001", "ADR-0003 remains Proposed")],
        1,
    )


# --- an unmarked ADR above 0277: Tier 1 --------------------------------------


def test_an_unmarked_adr_above_0277_is_tier_1(tmp_path: Path) -> None:
    adrs = {277: _adr(277, body=_MARKED), 278: _adr(278, body="Prose only.")}
    assert _findings(tmp_path, adrs, "unmarked") == [(1, "0278", "ADR-0278")]


def test_a_withdrawn_adr_above_0277_may_be_unmarked(tmp_path: Path) -> None:
    adrs = {277: _adr(277, body=_MARKED), 278: _adr(278, status="Withdrawn", body="Prose.")}
    assert _findings(tmp_path, adrs, "unmarked") == []


def test_an_unmarked_adr_at_or_below_0277_is_not_reached(tmp_path: Path) -> None:
    """§2: which older ADRs ADR-0089 §5 binds depends on ratification order."""
    adrs = {1: _adr(1, body="Prose."), 277: _adr(277, body="Prose.")}
    assert _findings(tmp_path, adrs, "unmarked") == []


# --- a marked clause equal to another ADR's (ADR-0277 §2, ADR-0278 §1) ---------

_QUOTING = "> **Normative.**   Rule\n> one-one."

#: What an ADR above 0277 marks for itself, so it is never an unmarked finding.
_MARKED_278 = "> **Normative.** Its own rule."

#: A sentence every ADR may rule for itself, word for word, in its own Decision.
_BOILERPLATE = "> **Normative.** `PROTOCOL_VERSION` does not move for this change."


def _detail(root: Path, adrs: dict[int, str], citation: str) -> str:
    (detail,) = (
        str(f["detail"])
        for f in _report(root, adrs)["findings"]
        if f["kind"] == "duplicate-clause" and f["citation"] == citation
    )
    return detail


def _passed(root: Path, adrs: dict[int, str]) -> dict[str, int]:
    passed = _report(root, adrs)["passed"]
    assert isinstance(passed, dict)
    return {str(kind): int(count) for kind, count in passed.items()}


def test_a_quotation_in_context_above_0277_is_tier_1_and_its_original_is_not_reported(
    tmp_path: Path,
) -> None:
    """ADR-0278 §4: the quoting clause is the finding; the ruling it equals is not."""
    adrs = {1: _adr(1, body=_MARKED), 278: _adr(278, body=_MARKED_278, context=_QUOTING)}
    assert _findings(tmp_path, adrs, "duplicate-clause") == [(1, "0278", "ADR-0278 §Context:1")]
    assert _passed(tmp_path, adrs)["duplicate-clause"] == 1


def test_a_quotation_in_context_fails_the_run(tmp_path: Path) -> None:
    adrs = {1: _adr(1, body=_MARKED), 278: _adr(278, body=_MARKED_278, context=_QUOTING)}
    assert _run(tmp_path, adrs).returncode == 1


def test_the_finding_names_the_clauses_it_equals_and_its_level_2_section(
    tmp_path: Path,
) -> None:
    """ADR-0278 §1's fifth clause: both, in the finding itself."""
    adrs = {
        1: _adr(1, body=_MARKED),
        2: _adr(2, body=_QUOTING),
        278: _adr(278, body=f"{_MARKED_278}\n\n## Consequences\n\n{_QUOTING}"),
    }
    detail = _detail(tmp_path, adrs, "ADR-0278 §Consequences:1")
    assert "ADR-0001 §1:1" in detail
    assert "ADR-0002 §Decision:1" in detail
    assert "`## Consequences`" in detail


def test_the_same_sentence_in_two_decision_sections_above_0277_is_passed_and_counted(
    tmp_path: Path,
) -> None:
    """ADR-0278 §4: boilerplate each ADR rules for itself is no finding at any tier."""
    adrs = {
        278: _adr(278, body=_BOILERPLATE),
        279: _adr(279, body=f"### 3. Versioning\n\n{_BOILERPLATE}"),
    }
    assert _findings(tmp_path, adrs, "duplicate-clause") == []
    assert _passed(tmp_path, adrs)["duplicate-clause"] == 2
    assert _run(tmp_path, adrs).returncode == 0


def test_a_decision_clause_under_a_colon_ended_paragraph_naming_its_source_is_passed(
    tmp_path: Path,
) -> None:
    """ADR-0278 §4: the lead-in arm was declined, so the paragraph above changes nothing.

    ADR-0211 §5:3 and ADR-0214 §7:1 are this shape in the corpus. The check passes
    it; ADR-0277 §3 still forbids it, and review enforces that (ADR-0278 §3).
    """
    lead_in = f"ADR-0001 §1:1 already ruled it, and the clause reads:\n\n{_QUOTING}"
    adrs = {1: _adr(1, body=_MARKED), 278: _adr(278, body=_MARKED_278 + "\n\n" + lead_in)}
    assert _findings(tmp_path, adrs, "duplicate-clause") == []
    assert _passed(tmp_path, adrs)["duplicate-clause"] == 2


def test_both_members_outside_decision_are_each_reported(tmp_path: Path) -> None:
    """ADR-0278 §1:2: the equal clause is reported where it too stands outside."""
    adrs = {1: _adr(1, context=_QUOTING), 278: _adr(278, body=_MARKED_278, context=_QUOTING)}
    assert _findings(tmp_path, adrs, "duplicate-clause") == [
        (1, "0278", "ADR-0278 §Context:1"),
        (2, "0001", "ADR-0001 §Context:1"),
    ]
    assert _passed(tmp_path, adrs)["duplicate-clause"] == 0


def test_a_quotation_in_an_older_adr_is_tier_2(tmp_path: Path) -> None:
    adrs = {1: _adr(1, body=_MARKED), 2: _adr(2, context=_QUOTING)}
    assert _findings(tmp_path, adrs, "duplicate-clause") == [(2, "0002", "ADR-0002 §Context:1")]
    assert _run(tmp_path, adrs).returncode == 0


def test_a_mark_above_every_level_2_heading_stands_outside_decision(tmp_path: Path) -> None:
    """A clause in the header has no section; it is reported, and says where it stands."""
    adrs = {1: _adr(1, body=_MARKED), 278: _adr(278, body=_MARKED_278, header=f"\n{_QUOTING}\n")}
    assert _findings(tmp_path, adrs, "duplicate-clause") == [(1, "0278", "ADR-0278")]
    assert "above every level-2 heading" in _detail(tmp_path, adrs, "ADR-0278")


def test_a_quotation_without_the_token_is_no_duplicate(tmp_path: Path) -> None:
    """§3's second rule is the way out: a block quote without the token is no mark."""
    adrs = {
        1: _adr(1, body=_MARKED),
        278: _adr(278, body=_MARKED_278, context="> Rule one-one."),
    }
    assert _findings(tmp_path, adrs, "duplicate-clause") == []
    assert _passed(tmp_path, adrs)["duplicate-clause"] == 0


def test_one_adr_repeating_itself_is_not_a_duplicate(tmp_path: Path) -> None:
    adrs = {278: _adr(278, body=_MARKED_278, context="> **Normative.** Its own rule.")}
    assert _findings(tmp_path, adrs, "duplicate-clause") == []
    assert _passed(tmp_path, adrs)["duplicate-clause"] == 0


def test_an_adr_above_0277_whose_only_run_holds_a_nested_fence_is_unmarked(
    tmp_path: Path,
) -> None:
    """The run is no clause (ADR-0089 §2), so the ADR marks nothing (ADR-0277 §2)."""
    body = "> **Normative.** Example:\n>\n> > ```python\n> > x = 1\n> > ```"
    adrs = {277: _adr(277, body=_MARKED), 278: _adr(278, body=body)}
    assert _findings(tmp_path, adrs, "unmarked") == [(1, "0278", "ADR-0278")]


# --- the pass counts (ADR-0278 §1, §2) ------------------------------------------


def test_the_text_report_states_both_pass_counts(tmp_path: Path) -> None:
    """ADR-0278 §1 and §2: the report states how many it passed, and lists none."""
    adrs = {
        1: _adr(1, header=_NOTE + _CORRECTION, body=_MARKED),
        2: _adr(2, body=_QUOTING),
    }
    for number, text in adrs.items():
        path = tmp_path / "docs" / "adr" / f"{number:04d}-decision.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for fmt in ("text", "markdown"):
        argv = [sys.executable, str(_SCRIPT), "--root", str(tmp_path), "--format", fmt]
        result = subprocess.run(  # noqa: S603
            [*argv, "--no-tracker"], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        assert "Passed without a finding: 2 marked clause(s)" in result.stdout
        assert "and 1 stale header note(s)" in result.stdout
        for listed in ("ADR-0002 remains Proposed", "ADR-0001 §1:1", "ADR-0002 §Decision:1"):
            assert listed not in result.stdout
