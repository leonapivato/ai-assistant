"""The held population: the act rides ``resume`` (ADR-0235 §1, §2, §6).

Population (a) is a confirmation a park holds, so the act is an act **on work**:
the answer both authorises the call and, in the same call, may make its recipients
standing. Everything here is driven through the real engine over a real
``StepRunner`` and a real park, because the clauses under test are about *when*
things happen relative to a ruling, a record and a send — which a fake engine's
resume cannot exhibit.

The recorded population is ``test_recipient_grant_operations.py``. The two are
separate modules because ADR-0235 §3 makes them separate doors: "answering (a) is
an act on work; answering (b) is an act on a record".
"""

from __future__ import annotations

from ai_assistant.core.types import TurnOutcome

# --- §3: the two populations do not overlap ----------------------------------


def test_the_outcome_carries_the_member_the_adr_declared() -> None:
    """``TurnOutcome`` grows exactly one field, and it defaults to ``None`` (§4)."""
    assert TurnOutcome.model_fields["recipient_grant"].default is None
    assert TurnOutcome(turn=None).recipient_grant is None
