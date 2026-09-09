"""``PROTOCOL_VERSION`` moved for ``STRUCTURED_READ`` and its log names why (ADR-0240 §11).

§11 asks that "``PROTOCOL_VERSION`` moves by one from the value in the tree on the day
the implementing lane lands" and that "``wire/envelope.py``'s log gains an entry naming
this ADR and this reason". The rest of §11's persistence clauses — a ``PlanExport`` at
``schema_version`` 7, a document of the earlier shape not validating, and
``EXPORT_VERSION`` not moving — are asserted where those values live
(``tests/core/test_planning_types.py``, ``tests/memory/``).

**Both halves matter and neither substitutes for the other**, which is
``test_web_search_protocol_version.py``'s reasoning one decision on: ADR-0124 §9 makes
compliance with the bump rule a **review obligation** and decides no mechanical check
(#891 carries the one that does not exist), so what a test can hold is that the number
moved *and* that the move is accounted for in the log a reviewer reads.

**And here the accounting is the half worth having, because this move rests on both
limbs where the entry above it rested on one.** ADR-0231 §1 gave ``WEB_SEARCH`` no
field, so the defaulted-member limb was unavailable and the closed enumeration was the
whole of that break; ADR-0240 §2 gives this kind a ``structure`` **and** adds the
member, so both bite and the entry has to say so. An entry that borrowed its
neighbour's reasoning would be a correctly-moved number with a half-true account under
it.
"""

from __future__ import annotations

import inspect
from typing import Final

from ai_assistant.wire import envelope

#: The version ADR-0240 §11 moves to, and the one it moves from.
#:
#: **§11 deliberately fixes no numeral and says why** — "ADR-0238 has already scheduled
#: ``PROTOCOL_VERSION`` 31 → 32 for a lane that may land before or after this one, and a
#: numeral in a ratified ADR that the tree has moved past is the failure ADR-0226 §4's
#: own successors had to correct". So the figure is read off the tree of the lane's own
#: day and recorded here, where it can be checked, rather than in the decision text.
_MOVED_TO: Final = 32
_MOVED_FROM: Final = 31


def test_the_protocol_version_moved_past_the_figure_this_decision_reached() -> None:
    """§11: the move, asserted as a move and not as a state.

    An equality here would make a later, unrelated and correctly reasoned bump look
    like a violation of ADR-0240 — the failure ``CONTRIBUTING.md`` → "No state claims in
    living documents" is about, and which ADR-0186 §13 already ruled on for the
    neighbouring clause. So what is asserted is the half that stays true for as long as
    ADR-0240 stands: the number is **at or past** the figure this decision reached,
    because a later ADR can move it on and none can un-move this move. The absolute
    figure has exactly one home, ``tests/core/test_engine_surface_closure.py``, where a
    lane moving it is made to name the limb it is under.
    """
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_both_of_its_grounds() -> None:
    """§11: the entry names the ADR, the member, the field and both limbs.

    The log is the comment block above the constant, so it is read out of the module's
    source. What is asserted is that the entry names the version, the decision, and
    **both** halves of ADR-0124 §9's second limb — the closed enumeration a version 31
    peer refuses outright, and the defaulted field the projection emits on every ask
    that an older ``extra="forbid"`` then refuses.
    """
    entry = _entry_for(_MOVED_TO)

    assert f"**{_MOVED_TO} since ADR-0240 §11**" in entry
    assert "STRUCTURED_READ" in entry
    assert "structure" in entry, "the field half of the pair"
    assert 'extra="forbid"' in entry, "and the limb it bites through"
    assert "closed" in entry, "the enumeration half"
    assert f"**{_MOVED_FROM} since" in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def test_the_entry_records_that_the_promoted_method_set_did_not_move() -> None:
    """ADR-0124 §9's **first** limb, stated as not reached rather than left silent.

    ADR-0240 adds no Protocol, no method to the promoted ``AssistantEngine`` surface and
    no gateway route; the one Protocol it widens is ``Planner``, which is on neither
    promoted surface and whose new keyword no peer emits. ``test_engine_surface_closure``
    pins the figure itself beside the constant; what this asserts is that the log *says
    so*, which is the half a reviewer reads when asking why the number moved.
    """
    entry = _entry_for(_MOVED_TO)

    assert "fifty-four" in entry
    assert "thirty-one" in entry
    assert "empty_reads" in entry, "and says why the widened Protocol is not a ground"


def _entry_for(version: int) -> str:
    """The version log's entry for one version, read out of the module's source.

    The log is a run of ``#:`` comments above the constant, each entry opening with
    ``**<n> since ADR-…**``, so an entry is the span from its own opener to the next one
    — or to the constant, for the last. Sliced rather than parsed because the comment
    block is prose a reviewer reads and has no structure worth asserting.

    **The prefixes and the wrapping are stripped**, so what the cases above match is the
    entry's *prose* rather than the column it happened to be reflowed to: a phrase
    asserted across a line break is a test that fails on ``ruff format`` rewrapping a
    paragraph, which would report a rewrapped comment as a missing account of the
    version.

    Args:
        version: The version whose entry to return.

    Returns:
        That entry's prose, one line, with the comment prefixes removed.
    """
    source = inspect.getsource(envelope)
    entry = source.split(f"#: **{version} since")[-1].split("PROTOCOL_VERSION: Final")[0]
    stripped = (line.removeprefix("#:").strip() for line in entry.splitlines())
    return f"**{version} since " + " ".join(part for part in stripped if part)
