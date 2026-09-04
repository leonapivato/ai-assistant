"""``PROTOCOL_VERSION`` moved for the establishing act, on three grounds (ADR-0235 §10).

§10 obliges the implementing lane to move the constant "in the same change" and to
record "the ground in the constant's own commentary as every prior move has" — and
it is the first entry in this log obliged by **three** grounds at once, requiring
the entry to record all three rather than fold them into one.

**Both halves matter and neither substitutes for the other**, which is
``test_web_search_protocol_version.py``'s reasoning one decision on: ADR-0124 §9
makes compliance with the bump rule a **review obligation** and decides no
mechanical check (#891 carries the one that does not exist), so what a test can
hold is that the number moved *and* that the move is accounted for in the log a
reviewer reads.

**And here the accounting is the half worth having**, because a reader who found
only one of the three grounds recorded would conclude the other two were oversights
— when what is true is that each obliges the move on its own and a peer at 30 and a
peer at 31 disagree about the surface on every one of them.
"""

from __future__ import annotations

import inspect
from typing import Final

from ai_assistant.wire import envelope

#: The version ADR-0235 §10 moves to, and the one it moves from.
#:
#: **§10 fixes no number and says why**: "any figure written here is a fact about a
#: tree that may move again before the lane does", so the rule is that the lane reads
#: the constant at the moment it lands and moves it by one. It stood at 30, where
#: ADR-0231's Lane 4 left it, and the move is recorded here as the reading it was.
_MOVED_TO: Final = 31
_MOVED_FROM: Final = 30


def test_the_protocol_version_moved_past_the_figure_this_decision_reached() -> None:
    """§10: the move, asserted as a move and not as a state.

    An equality here would make a later, unrelated and correctly reasoned bump look
    like a violation of ADR-0235, which is the failure ``CONTRIBUTING.md`` -> "No
    state claims in living documents" is about. The absolute figure has exactly one
    home, ``tests/core/test_engine_surface_closure.py``, where a lane moving it is
    made to name the limb it is under.
    """
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_all_three_grounds() -> None:
    """§10: the entry records **all three** grounds rather than folding them into one.

    The promoted method set grows by five; ``resume``'s declared arguments grow by
    one; and a wire-carried ``core`` type gains a member. "Each of the three obliges
    the move on its own and the entry records all three" — so an entry naming the
    method set alone would leave a reader believing a version 30 client could still
    decode a version 31 hub's ordinary turn, which is false.
    """
    entry = _entry_for(_MOVED_TO)

    assert f"**{_MOVED_TO} since ADR-0235 §10**" in entry
    assert "grantable_decisions" in entry
    assert "establish_recipient_grant" in entry
    assert "remember_recipients_until" in entry
    assert "recipient_grant" in entry
    assert "TurnOutcome" in entry
    assert f"**{_MOVED_FROM} since" in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def test_the_entry_names_both_limbs_of_the_bump_rule() -> None:
    """ADR-0124 §9's two limbs, named rather than left for a reader to classify.

    The three grounds are not three instances of one limb: two are the **first**
    (the method set, and a declared argument on a sixth method) and one is the
    **second** (a member on a wire-carried ``core`` type). A reviewer asking "which
    rule obliged this" reads the entry, and an entry naming one limb would send them
    to the wrong clause.
    """
    entry = _entry_for(_MOVED_TO)

    assert "**first** limb" in entry
    assert "**second** limb" in entry


def test_the_entry_records_which_direction_each_break_bites_in() -> None:
    """The half that is a fact about the tree rather than about the ADR.

    ``TurnOutcome`` sets ``extra="forbid"`` and the projection dumps every field
    including a ``None`` one, so a version 31 hub emits ``recipient_grant`` on every
    turn result and a version 30 client fails ``extra_forbidden`` on the first of
    them; the other direction is quiet, because the field is additive with a default.
    Saying which way it bites is what distinguishes this entry from one that asserted
    a break it had not checked.
    """
    entry = _entry_for(_MOVED_TO)

    assert 'extra="forbid"' in entry
    assert "extra_forbidden" in entry
    assert "additive with a" in entry


def test_the_entry_records_the_two_figures_a_reviewer_reads_next() -> None:
    """The method set moved and ADR-0177 §1's browser enumeration did not (§9).

    ADR-0235 §9 leaves the browser to a later consumer lane with its own ratified
    decision, so the two figures move apart on this change — and the entry has to say
    so, because "the method set grew" is exactly the sentence a reader would
    otherwise take as also true of the enumeration.
    """
    entry = _entry_for(_MOVED_TO)

    assert "fifty-four" in entry
    assert "thirty-one" in entry


def test_the_entry_records_the_one_exception_under_wire() -> None:
    """ "Nothing else under ``wire/`` changes for it" has one standing exception.

    ``wire/client.py`` is hand-written where ``METHODS``, both adapters and the error
    registry are derived, so its forwarding methods are the one edit — which is the
    exception the entry at 12 already records in terms and which ADR-0151 §11 set
    before it. An entry that repeated the unqualified sentence would be describing a
    tree in which the CLI could not reach any of the five new operations.
    """
    entry = _entry_for(_MOVED_TO)

    assert "wire/client.py" in entry
    assert "hand-written" in entry


def _entry_for(version: int) -> str:
    """The version log's entry for one version, read out of the module's source.

    ``test_web_search_protocol_version.py``'s reader, and it is reached for rather
    than restated for that module's own reason: the log is prose a reviewer reads,
    the prefixes and the wrapping are stripped so a case matches the *prose* rather
    than the column it was reflowed to, and a second copy of the slicing would be a
    second thing to keep in step with the comment block's shape.

    Args:
        version: The version whose entry to return.

    Returns:
        That entry's prose, one line, with the comment prefixes removed.
    """
    source = inspect.getsource(envelope)
    entry = source.split(f"#: **{version} since")[-1].split("PROTOCOL_VERSION: Final")[0]
    stripped = (line.removeprefix("#:").strip() for line in entry.splitlines())
    return f"**{version} since " + " ".join(part for part in stripped if part)
