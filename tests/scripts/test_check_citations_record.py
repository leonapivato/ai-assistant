"""ADR-0277 §2's record checks in scripts/check_citations.py, over constructed corpora.

Each check is pinned in both directions — the case it reports and the case it
must stay silent on — and at the tier §2 assigns it, because the tier is the
decision: a Tier 1 finding fails the gate (the corpus test in
``test_adr_citations_corpus.py``), a Tier 2 finding never does.

Driven as a subprocess over ``--root``, as ``test_check_citations.py`` drives
the rest of the checker, so what is pinned is the script's real output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "scripts" / "check_citations.py"


def _adr(number: int, *, status: str = "Accepted", body: str = "", header: str = "") -> str:
    return (
        f"# {number}. Decision {number}\n\n- Status: {status}\n- Date: 2026-09-26\n{header}\n"
        f"## Context\n\nWhy.\n\n## Decision\n\n{body}\n\n## Consequences\n\nSome.\n"
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


def _findings(root: Path, adrs: dict[int, str], kind: str) -> list[tuple[int, str, str]]:
    result = _run(root, adrs)
    assert result.returncode in (0, 1), result.stderr
    report = json.loads(result.stdout)
    return [
        (int(f["tier"]), str(f["path"]).rsplit("/", 1)[-1][:4], str(f["citation"]))
        for f in report["findings"]
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


# --- a marked clause equal to another ADR's -----------------------------------

_QUOTING = "> **Normative.**   Rule\n> one-one."


def test_a_duplicate_in_an_adr_above_0277_is_tier_1_and_its_original_tier_2(
    tmp_path: Path,
) -> None:
    """Both clauses are "a marked clause equal to another ADR's"; each takes its own tier."""
    adrs = {1: _adr(1, body=_MARKED), 278: _adr(278, body=_QUOTING)}
    assert _findings(tmp_path, adrs, "duplicate-clause") == [
        (1, "0278", "ADR-0278 §Decision:1"),
        (2, "0001", "ADR-0001 §1:1"),
    ]


def test_a_duplicate_between_older_adrs_is_tier_2(tmp_path: Path) -> None:
    adrs = {1: _adr(1, body=_MARKED), 2: _adr(2, body=_QUOTING)}
    assert _findings(tmp_path, adrs, "duplicate-clause") == [
        (2, "0001", "ADR-0001 §1:1"),
        (2, "0002", "ADR-0002 §Decision:1"),
    ]


def test_a_quotation_without_the_token_is_no_duplicate(tmp_path: Path) -> None:
    """§3's second rule is the way out: a block quote without the token is no mark."""
    adrs = {
        1: _adr(1, body=_MARKED),
        278: _adr(278, body="> **Normative.** Its own rule.\n\n> Rule one-one."),
    }
    assert _findings(tmp_path, adrs, "duplicate-clause") == []


def test_one_adr_repeating_itself_is_not_a_duplicate(tmp_path: Path) -> None:
    body = _MARKED + "\n\n### 3. Three\n\n> **Normative.** Rule one-one."
    assert _findings(tmp_path, {278: _adr(278, body=body)}, "duplicate-clause") == []
