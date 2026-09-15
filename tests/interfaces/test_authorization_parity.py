"""The two surfaces ADR-0254 §11 owes, held to the same clauses (the parity sweep).

**Why this module exists.** ADR-0250's M4 review spent rounds 7, 8 and 9 fixing one
surface and leaving its twin — *"a clause of the decision stated on one surface and not
the other is the defect rounds 7, 8 and 9 each were"*. Both renderers here were written
from the same reading, which is exactly the state that drifts silently: a later edit to
one is a clause the other loses, and no test over either alone can see it.

**What is asserted is a table**, one row per clause ADR-0254 §11 states about a
rendering, and each row names what each surface must say. It is deliberately about
*clauses* and not about wording: the two surfaces speak differently and should, so the
row names the fact and each side names the evidence for it.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Final

import pytest

from ai_assistant.interfaces import cli, gateway


def _joined(source: str) -> str:
    """One source text with its adjacent string literals joined.

    A sentence written over three lines is three literals the compiler joins and a
    substring search does not, so without this every row of the table below would be a
    claim about where the author happened to wrap — which is the brittleness this module
    exists to avoid rather than to introduce. Python's implicit concatenation and
    JavaScript's ``+`` are both handled, and so is an ``f`` prefix on the continuation,
    because a sentence interpolating an indent is written that way here.
    """
    return re.sub(r'"\s*\+?\s*f?"', "", source)


#: The command line's whole authorization rendering, as source.
#:
#: Read off the functions rather than off the file, so a clause moved into a helper is
#: still found and a clause deleted is not found in a neighbouring surface's prose.
TERMINAL: Final = _joined(
    "".join(
        inspect.getsource(one)
        for one in (
            cli._bound_sentence,
            cli._render_coverage,
            cli._render_confirmation_authorization,
            cli._render_authorization,
            cli._render_standing_authorizations,
            cli._render_authorization_settlement,
            cli._render_opened_authorizations,
        )
    )
)

#: The browser's, as the bytes the page is actually served — read off the shipped file
#: rather than off a copy, for the same reason ``test_bundle`` does.
BROWSER: Final = _joined(
    (Path(gateway.__file__).parent / "assets" / "app.js").read_text(encoding="utf-8")
)

#: One row per clause, each naming the evidence on each surface.
#:
#: The pairs are **not** the same string, because the two surfaces speak differently and
#: should: a terminal prints a command to paste and a page draws a button. What the row
#: fixes is that the clause is stated on both.
CLAUSES: Final = (
    ("§11: the coverage is rendered member by member", "argument", "view.argument"),
    ("§8: the user's own words sit beside every member", "you said", "you said"),
    ("§11: the horizon is shown (ADR-0256)", "lapses at", "It lapses at"),
    ("§11: the horizon is shown again in the listing", "horizon is", "the horizon is"),
    ("§11: the listing says whether the row still stands", "still stands", "still stands"),
    ("§11: a lapsed row says it has lapsed", "has lapsed", "has lapsed"),
    ("§11: the goal is rendered by statement", "goal_statement", "goal_statement"),
    ("§11: the revocation handle is on screen", "view.id", "view.id"),
    (
        "§11: the listing promises nothing about the next call",
        "not a promise",
        "not a promise",
    ),
    (
        "§1: an empty coverage is not a wildcard",
        "no argument of yours",
        "no argument of yours",
    ),
    (
        "§11: the question says what answering leaves standing",
        "standing authority",
        "standing authority",
    ),
    (
        "§11: withdrawal is prospective and rewrites nothing",
        "already decided is rewritten",
        "already decided is rewritten",
    ),
    ("§16: an unknown id says so", "no record", "no record"),
    ("§1: a question is withdrawn by declining it", "declining it", "declining it"),
    ("§2: a MONEY bound reads as a ceiling", "up to", "up to"),
    (
        "§2: a PERIOD bound reads as half-open",
        "up to but not including",
        "up to but not including",
    ),
    ("§2: a TERMS bound reads as a named set", "one of:", "one of:"),
    (
        "§11: two authorities opened by one act are announced as two",
        "standing permission",
        "standing permission",
    ),
    # The announcement **names** the remedy on both surfaces and performs it on neither:
    # the terminal prints the command to type, and the page names the panel the act is
    # taken in. A control in a reply reports into DOM the next turn throws away, which is
    # what round 6 found, and a terminal has no such control to offer in the first place.
    (
        "§11: the announcement names the remedy and does not take it",
        "revoke-authorization",
        "What this authorises",
    ),
)


@pytest.mark.parametrize(
    ("clause", "terminal", "browser"),
    CLAUSES,
    ids=[one[0] for one in CLAUSES],
)
def test_both_surfaces_state_every_clause_the_decision_owes(
    clause: str, terminal: str, browser: str
) -> None:
    """One row of the table, on both surfaces.

    A failure here names the clause and the surface that lost it, which is the whole
    point: the alternative is discovering it three review rounds later on whichever
    surface the reviewer happened to read.
    """
    assert terminal in TERMINAL, f"the command line no longer states: {clause}"
    assert browser in BROWSER, f"the browser no longer states: {clause}"
