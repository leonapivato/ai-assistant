"""ADR-0271 §8's arms **1** and **2**: the pin, and that it is a value and not a pointer.

P2's whole subject — `permissions` setting `PermissionRuling.proved_quote` at the ruling,
from the read condition 6's evidence route was proved over (§1). P1 landed the field, its
validator and the detachment; nothing set one until now.

**What is here.** Arm 1: the pin on a route-(d) ``ALLOW`` whose coverage carries a
``MONEY`` member met at ``"120"``/``"EUR"``, on the ruling and on the decision
``from_request`` builds; its absence on a coverage carrying no ``MONEY`` member, on a
member met by no route, on a ``CONFIRM``, on a ``DENY`` and on a route-(a) ``ALLOW``; the
**last** of two quotes; ``PermissionRuling``'s refusal over each of ADR-0254 §7's three
other row shapes; and the durable round trip through ``SqliteAuditTrail`` across a close
and reopen. Arm 2: a quote appended **after** the ruling leaves the pinned value
unchanged, and the read is **one** read.

**What is deliberately not here.** §2's charge reading and §3's comparison are **P3**'s
lane (arms 3, 4 and 5), and this tree holds neither — so an arm over one would assert
against code that does not exist. ``ChargedOutput`` appears below only as a value the
durable record must carry, which is arm 1's own sentence about it and not a reading of it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import pytest
from authorization_builders import (
    AT,
    GOAL,
    NOW,
    SITE,
    binding,
    route_d_decision,
)
from test_goal_authorization_policy import grants, live, seam
from test_goal_authorization_trail import _Trail, established
from test_quote_coverage import (
    ACT,
    UNPRICED_TOOL,
    ceiling,
    policy_with,
    priced,
    quote_for,
)

from ai_assistant.core.types import (
    ActionQuote,
    ChargedOutput,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RiskLevel,
    StepOutputRef,
    ToolDefinition,
)
from ai_assistant.permissions._coverage import governing_quote
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import AUTHORIZATION_TOOL, FakeGoalQuotes

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.types import ActionRequest, Authorization

#: When each decision below was ruled on. ``route_d_decision``'s own default, restated
#: here because the durable arm constructs its decision rather than taking that builder's.
DECIDED_AT: Final[datetime] = NOW

#: The decision id the durable arm writes and reads back.
PINNED_DECISION: Final = "d-pinned"


def pinned(ruling: PermissionRuling, call: ActionRequest) -> PermissionDecision:
    """The decision ``from_request`` builds from ``ruling`` (ADR-0271 §1).

    §1: the pin *"reaches the durable* ``PermissionDecision`` *by the path that exists
    today,* ``from_request`` *transcribing the ruling whole"* — so ``PermissionDecision``
    gains no field and this call takes no new parameter. The arm is that the value
    arrives, not that a new carrier exists.
    """
    return PermissionDecision.from_request(
        call, ruling, id="d-1", decided_at=datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
    )


# --- arm 1: the pin is set exactly where the evidence route decided something ---------


class TestThePinIsSetOnARouteDAllowTheEvidenceRouteDecided:
    """Arm 1's positive limb (ADR-0271 §1, ADR-0270 §2, ADR-0266 §7)."""

    async def test_a_met_money_member_pins_the_quote_it_was_proved_against(self) -> None:
        """The case the whole decision is about.

        A route-(d) ``ALLOW`` whose coverage carries a ``MONEY`` member met against a
        governing quote at ``"120"``/``"EUR"`` records **that quote** on the ruling — by
        value, whole, and equal to the one the seam held rather than to a value
        reconstructed from it.
        """
        call = priced()
        quote = quote_for(call, amount="120")
        gate, _ = policy_with(ceiling("150"), FakeGoalQuotes([quote], goal=GOAL))

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.ALLOW
        assert ruling.authorised_goal == GOAL, "route (d), the only route that pins"
        assert ruling.proved_quote == quote
        assert ruling.proved_quote is not None
        assert ruling.proved_quote.amount == Decimal("120")
        assert ruling.proved_quote.currency == "EUR"

    async def test_the_decision_from_request_builds_carries_it(self) -> None:
        """§1: ``from_request`` transcribes the ruling whole, so the pin reaches the record.

        Stated separately from the ruling above because the transcription is a **deep
        copy**: a reading that carried the ruling by reference would pass this arm and
        the round-trip one and still hand the durable record an object the policy could
        move afterwards.
        """
        call = priced()
        quote = quote_for(call, amount="120")
        gate, _ = policy_with(ceiling("150"), FakeGoalQuotes([quote], goal=GOAL))

        ruling = await gate.decide(call)
        decision = pinned(ruling, call)

        assert decision.ruling.proved_quote == quote
        assert decision.ruling.proved_quote is not ruling.proved_quote, (
            "transcribed by value, so the record cannot be moved through the ruling"
        )

    async def test_the_last_of_two_quotes_is_the_one_pinned(self) -> None:
        """§1: *"of the quotes* ``GoalQuotes.for_action`` *returned, the last of them"*.

        ADR-0267 §5's governing-quote rule, read at the pin: a re-quote displaces its
        predecessor, and *"an earlier quote is consulted in no case"*. Both quotes here
        are inside the ceiling and carry the same digest, so **both** would satisfy
        condition 6 — which is what makes this an arm about the *selection* rather than
        about coverage, and what an implementation scanning for a satisfying quote would
        fail.
        """
        call = priced()
        first = quote_for(call, amount="80")
        second = quote_for(call, amount="120")
        gate, _ = policy_with(ceiling("150"), FakeGoalQuotes([first, second], goal=GOAL))

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.ALLOW
        assert ruling.proved_quote == second
        assert ruling.proved_quote != first


class TestTheAbsenceIsTotalOverEveryOtherCase:
    """Arm 1's negative limb: *"absent in every other case"* (ADR-0271 §1)."""

    async def test_a_route_d_allow_over_a_coverage_carrying_no_money_member_pins_nothing(
        self,
    ) -> None:
        """A row bounding no price leaves the evidence route deciding nothing.

        The arm that separates *"the route"* from *"the quotes"*: the goal **holds** a
        quote naming this act and the seam is wired, but the coverage carries only a
        ``TERMS`` member, so no member is met through the evidence route and there is
        nothing the pin would be a record of. An implementation writing ``quotes[-1]``
        whenever a quote is in hand pins one here.
        """
        call = priced()
        held = FakeGoalQuotes([quote_for(call, amount="120")], goal=GOAL)
        gate, quotes = policy_with(live(tool=UNPRICED_TOOL), held)

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.ALLOW
        assert ruling.authorised_goal == GOAL, "still route (d)"
        assert ruling.proved_quote is None
        assert quotes is not None
        assert quotes.call_count == 0, (
            "and the seam is not read at all, because a read could change no answer"
        )

    async def test_a_money_member_met_by_no_route_pins_nothing(self) -> None:
        """A price above the ceiling: no route meets the member, so no route is taken.

        The ruling is the ``CONFIRM`` the table reached, and a ``CONFIRM`` records no
        pin — a quote that failed a comparison is not a quote the dispatch was proved
        against.
        """
        call = priced()
        held = FakeGoalQuotes([quote_for(call, amount="170")], goal=GOAL)
        gate, _ = policy_with(ceiling("150"), held)

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert ruling.proved_quote is None

    async def test_a_confirm_pins_nothing(self) -> None:
        """The plain ``CONFIRM``: a policy holding no authorisation source at all."""
        call = priced()
        gate = ThresholdActionPolicy(confirm_at_risk=RiskLevel.LOW)

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert ruling.proved_quote is None

    async def test_a_deny_pins_nothing(self) -> None:
        """A ``DENY`` reached with the quote seam wired and a covering row in hand.

        Driven over the **same** wiring the positive arm uses, so the only difference is
        the threshold: the declaration is refused outright, no standing route is taken,
        and nothing is pinned though a quote that would have proved the ceiling exists.
        """
        call = priced()
        held = FakeGoalQuotes([quote_for(call, amount="120")], goal=GOAL)
        gate = ThresholdActionPolicy(
            deny_at_risk=UNPRICED_TOOL.risk_level,
            grants=grants(),
            authorizations=seam(ceiling("150")),
            quotes=held,
        )

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.DENY
        assert ruling.proved_quote is None

    async def test_a_route_a_allow_pins_nothing(self) -> None:
        """Route (a) — the user's own answer to a ``CONFIRM`` — records no pin.

        ADR-0254 §7's first route. ``resolve`` cites the confirmation and nothing else:
        the user authorised **this call**, not a ceiling proved against a price, so there
        is no comparison for a pin to be the operand of. The confirmation resolved here
        is the one the priced request drew above, which is the shape most likely to
        tempt a reading that carried a pin across the resolution.
        """
        call = priced()
        held = FakeGoalQuotes([quote_for(call, amount="170")], goal=GOAL)
        gate, _ = policy_with(ceiling("150"), held)
        asked = await gate.decide(call)
        assert asked.outcome is PermissionOutcome.CONFIRM
        confirmed = PermissionDecision.from_request(
            call, asked, id="d-confirm", decided_at=DECIDED_AT
        )

        ruling = await gate.resolve(confirmed, approved=True)

        assert ruling.outcome is PermissionOutcome.ALLOW
        assert ruling.authorised_by == "d-confirm", "route (a)"
        assert ruling.proved_quote is None


class TestTheSelectionStatedAtItsOneStatement:
    """``governing_quote`` on its own, because two rules mask each other at the ruling.

    ADR-0271 §1 and ADR-0270 §2 say the pin is present *"exactly where the evidence route
    decided something"* — a coverage carrying a ``MONEY`` member. ADR-0267 §5 separately
    says the quote seam is read **zero** times for a coverage carrying none. Both hold at
    the ruling, and the second makes the first unobservable there: the tuple is empty, so
    an implementation that skipped the ``MONEY`` test entirely would still answer ``None``
    on every request this policy can build. These arms state the first rule where it is
    written, over quotes a caller **does** hold, so it is pinned by something other than
    the read gate happening to stand in front of it.
    """

    def test_a_coverage_carrying_no_money_member_selects_nothing(self) -> None:
        """Quotes in hand and no priced member: the evidence route decided nothing."""
        call = priced()
        assert governing_quote(live(tool=UNPRICED_TOOL).coverage, (quote_for(call),)) is None

    def test_a_coverage_carrying_a_money_member_selects_the_last_quote(self) -> None:
        """And with one, it is the **last** of what the one read returned."""
        call = priced()
        first = quote_for(call, amount="80")
        second = quote_for(call, amount="120")
        assert governing_quote(ceiling("150").coverage, (first, second)) is second

    def test_a_priced_coverage_over_no_quote_selects_nothing(self) -> None:
        """Total over the empty tuple rather than raising, which a met condition 6
        excludes but which the reading does not depend on."""
        assert governing_quote(ceiling("150").coverage, ()) is None


class TestTheValidatorRefusesEveryNonRouteDShape:
    """Arm 1's construction limb — ADR-0254 §7's three other row shapes (ADR-0271 §1).

    P1 landed the validator; these are its arms. The last two are the ones that fail a
    validator gating on ``authorised_by`` alone, which is why §1 states the refusal over
    ``authorised_goal``.
    """

    @staticmethod
    def quote() -> ActionQuote:
        """A well-formed quote, so each refusal below is about the **row** and not it."""
        return quote_for(priced(), amount="120")

    def test_a_row_with_authorised_by_unset_is_refused(self) -> None:
        """ADR-0193 §11's third state: the policy's own rules authorised the call."""
        with pytest.raises(ValueError, match="proved_quote"):
            PermissionRuling(
                outcome=PermissionOutcome.ALLOW,
                reason="the policy's own thresholds",
                proved_quote=self.quote(),
            )

    def test_the_route_b_shape_is_refused(self) -> None:
        """``authorised_by`` and ``authorised_subject`` set, ``authorised_goal`` unset."""
        with pytest.raises(ValueError, match="proved_quote"):
            PermissionRuling(
                outcome=PermissionOutcome.ALLOW,
                reason="a standing recipient grant covers this call",
                authorised_by="g-1",
                authorised_subject="a" * 64,
                proved_quote=self.quote(),
            )

    def test_the_route_c_shape_is_refused(self) -> None:
        """``authorised_by`` set, ``authorised_subject`` and ``authorised_goal`` unset."""
        with pytest.raises(ValueError, match="proved_quote"):
            PermissionRuling(
                outcome=PermissionOutcome.ALLOW,
                reason="the configured search destination",
                authorised_by="conn-1",
                proved_quote=self.quote(),
            )


#: :data:`AUTHORIZATION_TOOL` declaring where its output reports what it charged.
#:
#: The second half of arm 1's durable limb. **No lane here reads it** — §2's reading is
#: P3's — and it is present so that the record written below carries both widened shapes
#: at once, which is the arm: *"a decision carrying a* ``proved_quote`` *and a*
#: ``ToolDefinition`` *carrying a* ``charged_output`` *… decodes both byte for byte"*.
CHARGING_TOOL: Final[ToolDefinition] = ToolDefinition.model_validate(
    {
        **AUTHORIZATION_TOOL.model_dump(),
        "charged_output": ChargedOutput(amount="total", currency="total_currency"),
    }
)


class TestBothFieldsSurviveTheDurableRecord:
    """Arm 1's last limb: the round trip across a close and reopen (ADR-0271 §8).

    *"The arm failing a serialisation that drops either, which would leave verification
    with no pin to compare against and no declaration to read a charge under."* The trail
    stores the decision as JSON under its ``meta("schema_version")`` marker, which P0
    already moved for exactly these two shapes — so a reopen is the only way to drive the
    encode and the decode rather than an object the writer still holds.
    """

    @pytest.fixture
    def path(self, tmp_path: Path) -> Path:
        """Where this case's trail lives. A file, because the arm reopens it."""
        return tmp_path / "trail.sqlite3"

    @staticmethod
    def decision(row: Authorization, quote: ActionQuote) -> PermissionDecision:
        """``route_d_decision``'s row, with the pin the policy would have set on it.

        That builder takes no ``proved_quote`` knob and is not given one: its ten knobs
        exist so ADR-0254 §7's ten checks can each be failed independently, and the pin
        is read by none of them.
        """
        baseline = route_d_decision(row, binding(SITE), decision_id=PINNED_DECISION)
        return PermissionDecision(
            id=baseline.id,
            ruling=PermissionRuling(
                outcome=PermissionOutcome.ALLOW,
                reason=baseline.ruling.reason,
                authorised_by=baseline.ruling.authorised_by,
                authorised_subject=baseline.ruling.authorised_subject,
                authorised_goal=baseline.ruling.authorised_goal,
                proved_quote=quote,
            ),
            tool=baseline.tool,
            parameters_digest=baseline.parameters_digest,
            decided_at=baseline.decided_at,
            egress_binding=baseline.egress_binding,
        )

    async def test_the_pin_and_the_declaration_decode_byte_for_byte(self, path: Path) -> None:
        """Written, closed, reopened, read back — and equal to what went in."""
        quote = ActionQuote(
            intended_action=ACT,
            arguments_digest="7" * 64,
            amount=Decimal("120"),
            currency="EUR",
            plan="p1",
            read_from=StepOutputRef(step="s1", field="price"),
            read_at=AT,
        )
        row = established(tool=CHARGING_TOOL)
        held = _Trail(path, row)
        try:
            settled = await held.authorizations.resolve(row.id)
            assert settled is not None
            written = self.decision(settled, quote)
            await held.trail.record(written)
        finally:
            held.close()

        reopened = _Trail(path, row)
        try:
            recovered = await reopened.trail.recent()
        finally:
            reopened.close()

        assert [one.id for one in recovered] == [PINNED_DECISION]
        read_back = recovered[0]
        assert read_back.ruling.proved_quote == quote
        assert read_back.tool.charged_output == CHARGING_TOOL.charged_output
        assert read_back.model_dump_json() == written.model_dump_json(), (
            "byte for byte, and not merely field by field"
        )


# --- arm 2: the pin is a value, and it is the value condition 6 was proved against ----


class TestThePinIsAValueAndNotAPointer:
    """Arm 2 (ADR-0271 §1, §8)."""

    async def test_a_quote_appended_after_the_ruling_leaves_the_pin_unchanged(self) -> None:
        """*"The arm that fails an implementation which re-selects by act and digest."*

        A re-quote at ``"140"`` lands on the goal **after** the ruling. Were the pin a
        pointer — the act and the digest, resolved when something read it — the recorded
        decision would now name the later figure, and the reading the dispatch was
        actually proved against would be gone. The value is carried, so it is not.
        """
        call = priced()
        first = quote_for(call, amount="120")
        seam_held = FakeGoalQuotes([first], goal=GOAL)
        gate, _ = policy_with(ceiling("150"), seam_held)

        ruling = await gate.decide(call)
        decision = pinned(ruling, call)
        seam_held.hold_for(GOAL, quote_for(call, amount="140"))

        assert decision.ruling.proved_quote == first
        assert decision.ruling.proved_quote is not None
        assert decision.ruling.proved_quote.amount == Decimal("120")
        assert await seam_held.for_action(GOAL, ACT) == (
            first,
            quote_for(call, amount="140"),
        ), "the goal has moved on; the pinned reading has not"

    async def test_the_ruling_is_built_from_the_one_read_the_comparison_was_taken_over(
        self,
    ) -> None:
        """*"And the read is one read."*

        The seam returns ``("120",)`` to its first caller and ``("120", "130")`` to any
        second one. An implementation evaluating condition 6 against one read and
        constructing the ruling from another would pin ``"130"`` — a quote no comparison
        was ever made against — and would read the seam twice. The arm asserts both: the
        pinned figure, and the count.
        """
        call = priced()
        first = quote_for(call, amount="120")
        later = quote_for(call, amount="130")
        seam_held = _SecondCallAppends(first, later, goal=GOAL)
        gate = ThresholdActionPolicy(
            grants=grants(), authorizations=seam(ceiling("150")), quotes=seam_held
        )

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.ALLOW
        assert ruling.proved_quote == first
        assert seam_held.call_count == 1, "one read for the dispatch, and the ruling is its"
        assert await seam_held.for_action(GOAL, ACT) == (first, later), (
            "and the seam really would have answered differently a second time"
        )


class _SecondCallAppends:
    """A ``GoalQuotes`` whose **second** call returns a further quote beside the first.

    Arm 2's own fixture, and not a widening of ``FakeGoalQuotes``: the canonical fake
    answers the same tuple every time, which is what a seam does, and a double that
    changes its answer under the caller is a probe for one rule rather than a fake of the
    Protocol. Kept local so nothing in ``ai_assistant.testing`` grows a knob only this
    arm has a use for.
    """

    def __init__(self, first: ActionQuote, later: ActionQuote, *, goal: str) -> None:
        """Hold the two quotes and the goal they belong to."""
        self._answers = ((first,), (first, later))
        self._goal = goal
        self._calls = 0

    @property
    def call_count(self) -> int:
        """How many times :meth:`for_action` has been called."""
        return self._calls

    async def for_action(self, goal: str, intended_action: str) -> tuple[ActionQuote, ...]:
        """The first call's answer, then every later call's."""
        self._calls += 1
        if goal != self._goal or intended_action != ACT:
            return ()
        return self._answers[min(self._calls - 1, len(self._answers) - 1)]
