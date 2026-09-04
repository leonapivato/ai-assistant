"""The CONFIRM prompt at the browser edge (ADR-0177 §8, ADR-0178 §7).

Two operations reach a browser here that could not before. ADR-0177 §8 blocked the
surface "before a ratified decision supplies what ADR-0148 §8's fourth clause
requires"; ADR-0178 §8 discharges that precondition "by this ADR's ratification and
merge and not before", and ADR-0178 §7 states the floor over **a surface** rather than
over either renderer — so the browser inherits it without a third decision.

What is checked here is the view the page actually receives, which is the level
#1404's obligation is stated at: ``_step_view`` is an explicit enumeration, so "a
gateway that shipped the approval control while enumerating none of it would satisfy
every test above" (ADR-0178 §10). The cases mirror the CLI's own — the mixed binding,
the destination-less occurrence, the account-only set, one recipient named twice, every
occurrence rendered, and the non-egress confirmation — plus the one this surface owes
and the CLI does not: that the set crossing to the page is the set `core` derived.

**Driven through a real socket** for ``test_gateway.py``'s reason, on
``test_gateway_streams``' own harness rather than a fourth copy of it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from test_gateway_streams import Harness, _harness

from ai_assistant.core.errors import UnknownContinuationError
from ai_assistant.core.types import (
    Confirmation,
    ConfirmationEgress,
    ContinuationToken,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    Disposition,
    EgressDestination,
    EgressSpan,
    ExecutionState,
    SpanCoverage,
    StepOutcome,
    TurnOutcome,
)
from ai_assistant.interfaces.gateway.http import Request
from ai_assistant.interfaces.gateway.records import RequestClass
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS, _TURN_BUDGET
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson

pytestmark = pytest.mark.integration

_AT = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)

#: The two shapes this lane adds, each with the operation ADR-0177 §1 admits it for.
_ADDED: dict[str, str] = {
    "/confirmations": "pending_confirmations",
    "/confirmation/resume": "resume",
}

#: One well-formed body per shape. Every value is the **browser's own**: the token it
#: was handed back, and the human's answer.
_WELL_FORMED: dict[str, dict[str, Any]] = {
    "/confirmations": {},
    "/confirmation/resume": {"token": "h-1", "approved": True},
}

_IDENTITY = "work@example.com"


def _span(  # noqa: PLR0913 — one keyword per field of the span being built
    argument: str,
    *,
    index: int | None = None,
    extent: int = 5,
    canonical: str | None = None,
    supplied: str | None = None,
    tier: DataTier | None = None,
    provenance: DiscloserProvenance = DiscloserProvenance.SYSTEM_SELECTED,
) -> EgressSpan:
    """One span, carrying a destination exactly where ``canonical`` is given."""
    destination = (
        None
        if canonical is None
        else EgressDestination(
            protocol=DestinationProtocol.SMTP,
            supplied=supplied if supplied is not None else canonical,
            canonical=canonical,
        )
    )
    return EgressSpan(
        argument=argument,
        index=index,
        provenance=provenance,
        extent=extent,
        tier=tier,
        destination=destination,
    )


def _confirmation(
    *spans: EgressSpan,
    handle: str = "h-1",
    identity: str = _IDENTITY,
    parameters: Mapping[str, FrozenJson] | None = None,
    egress: bool = True,
    planned_with_external_content: bool = False,
) -> Confirmation:
    """One parked confirmation, with an egress member unless ``egress`` is false.

    Built here rather than through ``FakeAssistantEngine.park`` because the cases
    below turn on ``parameters`` as well as on the binding, and the fake's helper
    fixes the first.
    """
    return Confirmation(
        tool_id="smtp",
        tool_description="Send an email.",
        parameters={"to": "Alice@Example.ORG", "body": "hello"}
        if parameters is None
        else parameters,
        reason="this discloses data off-device",
        token=ContinuationToken(handle=handle),
        egress=(
            ConfirmationEgress(
                account_identity=identity,
                spans=spans,
                planned_with_external_content=planned_with_external_content,
                coverage=SpanCoverage.NOT_COVERED,
            )
            if egress
            else None
        ),
    )


def _parked(confirmation: Confirmation) -> TurnOutcome:
    """The outcome of a turn that parked on ``confirmation``."""
    return TurnOutcome(
        turn=None,
        conversation_id="c-1",
        step=StepOutcome(
            disposition=Disposition.AWAITING_CONFIRMATION,
            state=ExecutionState(id="e-1", plan_id="p-1", steps=(), updated_at=_AT),
            step_id="s-1",
            confirmation=confirmation,
        ),
    )


def _holding(*confirmations: Confirmation) -> FakeAssistantEngine:
    """An engine holding these parks, answerable by their own handles."""
    engine = FakeAssistantEngine()
    for one in confirmations:
        engine.parked[one.token.handle] = one
    return engine


async def _view(one: Harness, confirmation: Confirmation) -> dict[str, Any]:
    """Drive a turn that parks and return the confirmation view the page receives."""
    one.engine.turn_outcome = _parked(confirmation)
    status, body = await one.whole("POST", "/ask", {"utterance": "send it"})
    assert status == 200, body
    view: dict[str, Any] = body["outcome"]["step"]["confirmation"]
    return view


def _derived(confirmation: Confirmation) -> list[dict[str, Any]]:
    """The canonical destination set as `core` derives it, spelled the view's way.

    Computed here from :attr:`ConfirmationEgress.canonical_destination_set` — the
    property ADR-0178 §3 makes the single source of this set — so a comparison against
    what crossed is a comparison against `core` and not against the gateway's own
    idea of it.
    """
    assert confirmation.egress is not None
    return [
        {
            "account_identity": member.account_identity,
            "protocol": None if member.protocol is None else member.protocol.value,
            "canonical": member.canonical,
        }
        for member in confirmation.egress.canonical_destination_set
    ]


# --- ADR-0177 §1, §2: two more operations, and the enumeration stays closed ---


def test_the_two_paths_name_the_operations_the_adr_admits() -> None:
    """§1's enumeration of thirty, of which these two were the last unserved.

    Read off the one table the gateway classifies from, so the ADR and the code are
    one thing to compare rather than two.
    """
    for path, operation in _ADDED.items():
        assert _ASSISTANT_PATHS[("POST", path)] == operation, path


@pytest.mark.parametrize("path", sorted(_ADDED))
async def test_the_added_shape_asks_the_assistant_for_something(path: str) -> None:
    """ADR-0177 §2: the four request classes do not become five, and no rule is
    conditioned on which of the thirty an ``assistant-request`` names."""
    request = Request(method="POST", path=path, headers=(), body=b"{}")
    async with _harness() as one:
        assert one.gateway._classify(request) is RequestClass.ASSISTANT


@pytest.mark.parametrize("path", sorted(_ADDED))
async def test_the_added_shape_is_refused_without_a_session_and_reaches_nothing(
    path: str,
) -> None:
    """ADR-0168 §1's biconditional in the direction that matters: a confirmation is
    plainly asking the assistant for something, so a browser with no session reaches
    no engine at all — least of all one that would resolve a park."""
    async with _harness() as one:
        status, body = await one.whole("POST", path, _WELL_FORMED[path], admitted=False)

        assert status == 401
        assert body["fault"] == "no-live-session"
        assert one.engine.calls == []


# --- #1404: a park is the confirmation, not a boolean ------------------------


async def test_a_turn_that_parks_renders_the_confirmation_and_not_a_boolean() -> None:
    """The whole of #1404's first clause.

    ``_step_view`` reduced a ``Confirmation`` to ``awaiting_confirmation``, so no
    confirmation content reached the browser at all. All five content members cross
    now, and the boolean is gone rather than kept beside them — a page reading it
    would have a second, poorer way to ask the same question.
    """
    async with _harness(_holding()) as one:
        view = await _view(one, _confirmation(_span("body")))

        assert set(view) == {
            "token",
            "tool_id",
            "tool_description",
            "parameters",
            "reason",
            "egress",
        }
        assert view["tool_id"] == "smtp"
        assert view["tool_description"] == "Send an email."
        assert view["reason"] == "this discloses data off-device"
        _, body = await one.whole("POST", "/ask", {"utterance": "again"})
        assert "awaiting_confirmation" not in body["outcome"]["step"], body


async def test_the_parameters_cross_whole_and_in_the_mappings_own_order() -> None:
    """ADR-0177 §8: ``parameters`` is "rendered whole — every key and every value the
    mapping carries", none omitted, none truncated silently, "and none ordered in a
    way that hides one".

    A list of pairs rather than an object, so the mapping's own order is the order
    that crosses and nothing between here and the page can rearrange it.
    """
    async with _harness(_holding()) as one:
        view = await _view(
            one,
            _confirmation(
                _span("body"),
                parameters={"to": "alice@example.org", "subject": "hi", "body": "hello"},
            ),
        )

        assert [one["key"] for one in view["parameters"]] == ["to", "subject", "body"]
        assert [one["value"] for one in view["parameters"]] == [
            "alice@example.org",
            "hi",
            "hello",
        ]


async def test_an_integer_argument_reaches_the_page_unchanged() -> None:
    """The reason ``parameters`` crosses as text the gateway spelled.

    A JSON number reaching a browser is read by ``JSON.parse`` into a double, so an
    integer above 2**53 would arrive **changed** — and a confirmation showing a value
    the call would not run with is worse than one showing none. This is
    ``_preferences_view``'s losslessness rule reaching the one member of this surface
    whose contents nothing constrains.
    """
    big = 2**53 + 1
    async with _harness(_holding()) as one:
        view = await _view(
            one,
            _confirmation(_span("body"), parameters={"count": big, "nested": {"a": [1, 2]}}),
        )

        rendered = {one["key"]: one["value"] for one in view["parameters"]}
        assert rendered["count"] == str(big)
        assert rendered["nested"] == '{"a": [1, 2]}'


async def test_the_values_cross_as_data_and_are_not_pre_escaped() -> None:
    """``Confirmation``'s own contract: the values are carried "as data, not
    pre-formatted", because "safe" is target-specific and escaping is each adapter's
    own job on render.

    So the gateway neutralises nothing on the way out — the page's neutralisation is
    structural, by inserting every value through a text node (ADR-0175 §9), and a
    gateway that escaped for HTML here would show the owner an argument the call would
    not run with.
    """
    raw = "wipe\x1b[2Jscreen <script>alert(1)</script>"
    async with _harness(_holding()) as one:
        view = await _view(one, _confirmation(_span("body"), parameters={"body": raw}))

        assert view["parameters"] == [{"key": "body", "value": raw}]


# --- ADR-0178 §7: the floor, over the view the page receives -----------------


async def test_an_egress_confirmation_names_the_account_the_set_and_every_occurrence() -> None:
    """§7's first clause, over the mixed binding it is hardest on.

    ADR-0148 §8's fourth clause in full — the connected account's identity, the
    canonical destination set in both forms, and the payload description — with ``to``
    bearing a destination and ``body`` not, tested as one case rather than assumed
    away.
    """
    confirmation = _confirmation(
        _span("body", extent=5),
        _span("to", canonical="alice@example.org", supplied="Alice@Example.ORG", extent=17),
    )
    async with _harness(_holding()) as one:
        egress = (await _view(one, confirmation))["egress"]

        assert egress["account_identity"] == _IDENTITY
        assert egress["destinations"] == [
            {"account_identity": None, "protocol": "smtp", "canonical": "alice@example.org"}
        ]
        assert [span["argument"] for span in egress["spans"]] == ["body", "to"]
        named = egress["spans"][1]["destination"]
        assert named == {
            "protocol": "smtp",
            "supplied": "Alice@Example.ORG",
            "canonical": "alice@example.org",
        }


async def test_a_destination_less_occurrence_crosses_whole_and_names_no_recipient() -> None:
    """§7's second clause: both forms for the occurrences that carry a destination,
    and for those only.

    A span with no destination still crosses — by its argument, its position, its
    provenance, its extent and its tier — and carries ``null`` where a recipient would
    be. Dropping it, or inventing a destination for it, would fail the whole-rendering
    clause in the two opposite directions.
    """
    confirmation = _confirmation(
        _span(
            "body",
            extent=11,
            tier=DataTier.PERSONAL,
            provenance=DiscloserProvenance.USER_AUTHORED,
        )
    )
    async with _harness(_holding()) as one:
        egress = (await _view(one, confirmation))["egress"]

        assert egress["spans"] == [
            {
                "argument": "body",
                "index": None,
                "provenance": "user_authored",
                "extent": 11,
                "tier": "personal",
                "destination": None,
            }
        ]


async def test_an_account_only_set_names_the_account_as_the_destination() -> None:
    """§7's third clause: where every span carries no destination the set is the
    connected account — ADR-0148 §2's third clause — and the surface names it rather
    than showing no recipients.

    The account arm is the reduced one ADR-0178 §3 substitutes: an identity and
    neither of the other two fields, and no connection reference anywhere.
    """
    confirmation = _confirmation(_span("body"), _span("subject"))
    async with _harness(_holding()) as one:
        egress = (await _view(one, confirmation))["egress"]

        assert egress["destinations"] == [
            {"account_identity": _IDENTITY, "protocol": None, "canonical": None}
        ]
        assert "reference" not in str(egress)


async def test_one_recipient_named_twice_is_one_set_member_and_two_occurrences() -> None:
    """ADR-0150 §10's third clause, which is why the occurrences travel at all.

    A confirmation naming one argument for a member reached by two has understated the
    call; one showing only the occurrences leaves the user to deduplicate in their
    head. Both cross, and the arithmetic that makes them one member is `core`'s.
    """
    confirmation = _confirmation(
        _span("cc", canonical="alice@example.org", supplied="Alice@Example.ORG", extent=17),
        _span("to", canonical="alice@example.org", supplied="alice@example.org", extent=17),
    )
    async with _harness(_holding()) as one:
        egress = (await _view(one, confirmation))["egress"]

        assert len(egress["destinations"]) == 1
        assert [span["argument"] for span in egress["spans"]] == ["cc", "to"]
        assert [span["destination"]["supplied"] for span in egress["spans"]] == [
            "Alice@Example.ORG",
            "alice@example.org",
        ]


async def test_every_occurrence_crosses_none_omitted_and_none_truncated() -> None:
    """§7's fourth clause: occurrences are rendered whole, "none omitted, none
    truncated silently, and none ordered so as to hide one"."""
    spans = tuple(
        _span("to", index=index, canonical=f"user{index}@example.org", extent=18)
        for index in range(12)
    )
    confirmation = _confirmation(*spans)
    async with _harness(_holding()) as one:
        egress = (await _view(one, confirmation))["egress"]

        assert len(egress["spans"]) == 12
        assert [span["index"] for span in egress["spans"]] == list(range(12))
        assert len(egress["destinations"]) == 12


async def test_a_non_egress_confirmation_carries_no_egress_and_claims_nothing() -> None:
    """§7's last clause and §4's third: a confirmation whose ``egress`` is ``None``
    owes none of the floor and asserts none of it.

    ``null`` rather than an empty value: an empty span tuple is a well-formed payload
    description meaning something else entirely, and the absence states that the
    ruling was taken over no egress binding **and nothing more** — so nothing here
    says the call transmits nothing or reaches no recipient.
    """
    confirmation = _confirmation(egress=False, parameters={"body": "hello"})
    async with _harness(_holding()) as one:
        view = await _view(one, confirmation)

        assert view["egress"] is None
        assert view["parameters"] == [{"key": "body", "value": "hello"}]
        assert view["reason"] == "this discloses data off-device"


# --- ADR-0178 §3: the set is `core`'s, and the surface derives none of it -----


async def test_the_set_that_crosses_is_the_set_core_derived() -> None:
    """§3, and #1404's "one further test": the page renders the set it was handed.

    Compared member for member and **in order** against
    ``ConfirmationEgress.canonical_destination_set`` — the property §3 makes the single
    source of this set — over a binding that exercises every part of the rule at once:
    an aliased pair that deduplicates, several distinct recipients, a destination-less
    span, and recipients either side of the code-point ordering boundary.

    A gateway that re-derived the set would pass a test written against its own
    output; this one fails the moment the two computations disagree, which is the
    drift §3 says no lane may ship.
    """
    confirmation = _confirmation(
        _span("body"),
        _span("bcc", canonical="zoe@example.org", extent=15),
        _span("cc", canonical="alice@example.org", supplied="Alice@Example.ORG", extent=17),
        _span("to", canonical="alice@example.org", extent=17),
        _span("to", index=1, canonical="Bob@example.org", extent=15),
    )
    async with _harness(_holding()) as one:
        egress = (await _view(one, confirmation))["egress"]

        assert egress["destinations"] == _derived(confirmation)
        # Four occurrences carry a destination and one pair is an alias, so the set is
        # three — which is what makes this a test of the derivation and not of a copy.
        assert len(egress["destinations"]) == 3
        assert len(egress["spans"]) == 5


async def test_no_connection_reference_or_endpoint_reaches_the_page() -> None:
    """ADR-0148 §8's fourth clause bars the connection reference from a confirmation in
    terms, and ADR-0178 §2 excludes the transport endpoint as a value no surface can
    say anything true about.

    Neither is on ``ConfirmationEgress`` to begin with, so this asserts the property at
    the place a lane could still lose it: the enumeration this gateway ships.
    """
    confirmation = _confirmation(_span("to", canonical="alice@example.org", extent=17))
    async with _harness(_holding()) as one:
        egress = (await _view(one, confirmation))["egress"]

        # ADR-0181 §6's addition moves this roster by one and changes nothing else
        # about what it excludes: no connection reference, no transport endpoint.
        assert set(egress) == {
            "account_identity",
            "destinations",
            "spans",
            "planned_with_external_content",
        }
        assert set(egress["spans"][0]) == {
            "argument",
            "index",
            "provenance",
            "extent",
            "tier",
            "destination",
        }


async def test_a_call_planned_over_external_content_crosses_beside_the_whole_floor() -> None:
    """ADR-0181 §6 and §10's clause for this lane, at the half a page cannot supply.

    §10 requires the ``True`` case to carry "the fact **and** every occurrence
    ADR-0178 §7's floor already requires", so the floor is asserted here rather than
    trusted: §6's sixth clause is that nothing of it is suppressed or reordered on
    the strength of the new fact, and a view that had dropped the recipients to make
    room would pass a membership-only check.

    The value crosses at all because ADR-0178 §3 leaves the page no other route to
    it — the page renders what it was handed and derives nothing (#1445).
    """
    confirmation = _confirmation(
        _span("body", extent=5),
        _span("to", canonical="alice@example.org", supplied="Alice@Example.ORG", extent=17),
        planned_with_external_content=True,
    )
    async with _harness(_holding()) as one:
        egress = (await _view(one, confirmation))["egress"]

        assert egress["planned_with_external_content"] is True

        # ...and ADR-0178 §7's floor, whole and unmoved.
        assert egress["account_identity"] == _IDENTITY
        assert egress["destinations"] == _derived(confirmation)
        assert [span["argument"] for span in egress["spans"]] == ["body", "to"]
        named = egress["spans"][1]["destination"]
        assert named["canonical"] == "alice@example.org"
        assert named["supplied"] == "Alice@Example.ORG"


async def test_a_call_no_selected_record_marked_crosses_the_fact_too() -> None:
    """ADR-0181 §6's fourth clause at this seam: rendered in **both** states.

    §10 makes this its own case in terms — "a test asserting only that a marker is
    present when it is ``True`` does not satisfy this clause" — and the gateway is
    where a lane would most plausibly lose it, by omitting a falsy key from the
    payload and leaving the page to read ``undefined``. So the assertion is on the
    key's presence and its value, not on truthiness.
    """
    confirmation = _confirmation(
        _span("to", canonical="alice@example.org", extent=17),
        planned_with_external_content=False,
    )
    async with _harness(_holding()) as one:
        egress = (await _view(one, confirmation))["egress"]

        assert "planned_with_external_content" in egress
        assert egress["planned_with_external_content"] is False
        assert egress["account_identity"] == _IDENTITY  # beside the floor here too


async def test_the_recovery_route_carries_the_origin_the_live_one_does() -> None:
    """ADR-0177 §8 read against ADR-0181 §6: one view function, so one floor.

    §7 is stated over "a surface rendering a ``Confirmation``" and not over the route
    it arrived by, and §6 extends that clause rather than replacing it. A browser
    recovering a park through this read is being asked the same question as one that
    watched it park, so it is shown the same fact.
    """
    planned = _confirmation(
        _span("to", canonical="alice@example.org", extent=17),
        handle="h-1",
        planned_with_external_content=True,
    )
    unplanned = _confirmation(
        _span("to", canonical="bob@example.org", extent=17),
        handle="h-2",
        planned_with_external_content=False,
    )
    async with _harness(_holding(planned, unplanned)) as one:
        status, body = await one.whole("POST", "/confirmations", {})

        assert status == 200
        assert [view["token"] for view in body["confirmations"]] == ["h-1", "h-2"]
        crossed = [
            view["egress"]["planned_with_external_content"] for view in body["confirmations"]
        ]
        assert crossed == [True, False]


# --- ADR-0177 §8: pending_confirmations is the one recovery route ------------


async def test_pending_confirmations_lists_every_park_rendered_to_the_floor() -> None:
    """§8: "A browser that has been closed and reopened, and a gateway that has been
    restarted, both recover through this read and through no other route."

    Each recovered park carries the same floor a live one does, because §7 is stated
    over a surface rendering a ``Confirmation`` and not over the route it arrived by.
    """
    first = _confirmation(
        _span("to", canonical="alice@example.org", supplied="Alice@Example.ORG", extent=17),
        handle="h-1",
    )
    second = _confirmation(egress=False, handle="h-2")
    async with _harness(_holding(first, second)) as one:
        status, body = await one.whole("POST", "/confirmations", {})

        assert status == 200
        assert [view["token"] for view in body["confirmations"]] == ["h-1", "h-2"]
        assert body["confirmations"][0]["egress"]["account_identity"] == _IDENTITY
        assert body["confirmations"][0]["egress"]["destinations"] == _derived(first)
        assert body["confirmations"][1]["egress"] is None
        assert [name for name, _ in one.engine.calls] == ["pending_confirmations"]


async def test_the_recovery_read_takes_no_argument_from_the_browser() -> None:
    """ADR-0177 §1: "Every operation admitted above is reached with the arguments the
    promoted surface declares and with no others."

    ``pending_confirmations`` declares none, so a body offering some changes nothing
    about the call — there is no filter, no page and no selector to acquire by
    accident.
    """
    async with _harness(_holding(_confirmation(_span("body")))) as one:
        status, _ = await one.whole("POST", "/confirmations", {"limit": 1, "token": "h-1"})

        assert status == 200
        assert one.engine.calls == [("pending_confirmations", {})]


# --- ADR-0177 §8, §9: the answer is `approved` and the token is opaque -------


class _Recording(FakeAssistantEngine):
    """An engine that records the deadline ``resume`` was given (ADR-0177 §9)."""

    def __init__(self) -> None:
        """Start with no budget seen."""
        super().__init__()
        self.budgets: list[timedelta] = []

    async def resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, as the Protocol declares it
    ) -> TurnOutcome:
        """Record the budget, then answer as the fake does."""
        self.budgets.append(timeout)
        return await super().resume(token, approved=approved, timeout=timeout)


async def test_the_token_is_relayed_byte_for_byte_and_the_answer_is_approved() -> None:
    """§8: the token is relayed opaquely and ``resume`` is "answered with ``approved``
    and nothing else".

    The handle the engine receives is the handle it disclosed, unchanged: this gateway
    mints none, rewrites none and substitutes none, and the wrapping in
    ``ContinuationToken`` is the carrier the promoted surface declares rather than an
    interpretation of what is inside it.
    """
    handle = "h-é-1"
    async with _harness(_holding(_confirmation(_span("body"), handle=handle))) as one:
        status, body = await one.whole(
            "POST", "/confirmation/resume", {"token": handle, "approved": True}
        )

        assert status == 200
        assert one.engine.calls == [("resume", {"token": handle, "approved": True})]
        assert body["outcome"]["step"]["disposition"] == "executed"


async def test_no_browser_value_reaches_the_deadline() -> None:
    """§9: ``resume`` "is given the same budget a turn is given at this surface", and
    §1's deadline carve-out has exactly two members — neither of them a browser's.

    A body carrying a ``timeout`` changes nothing, which is the property that makes the
    carve-out a closed class rather than an exception.
    """
    engine = _Recording()
    engine.parked["h-1"] = _confirmation(_span("body"))
    async with _harness(engine) as one:
        status, _ = await one.whole(
            "POST",
            "/confirmation/resume",
            {"token": "h-1", "approved": True, "timeout": 1, "timeout_seconds": 999},
        )

        assert status == 200
        assert engine.budgets == [_TURN_BUDGET]


async def test_a_refusal_comes_back_as_an_outcome_and_not_as_a_fault() -> None:
    """ADR-0042 §4: a denial "is a result, not an exception" — the adapter conveys
    consent and the policy rules on it.

    So declining is an ordinary answer whose step was denied, rendered where every
    other turn's result is. A gateway that reported it as a fault would have this
    adapter authoring the permission outcome it is forbidden to author.
    """
    async with _harness(_holding(_confirmation(_span("body")))) as one:
        status, body = await one.whole(
            "POST", "/confirmation/resume", {"token": "h-1", "approved": False}
        )

        assert status == 200
        assert body["outcome"]["step"]["disposition"] == "denied"
        assert body["outcome"]["step"]["confirmation"] is None


async def test_a_second_answer_on_a_settled_binding_crosses_as_an_outcome() -> None:
    """ADR-0198 §§1-2 at this relay, which is what makes the page's re-offer possible
    (#1621).

    A ``resume`` presenting a token whose binding this engine has settled and still
    retains "restates that binding's answer: it returns a ``TurnOutcome`` describing the
    settled binding and raises no ``UnknownContinuationError``" — and it does so
    "**whatever the call's ``approved`` carries**", the recorded answer standing
    unchanged. So the second answer here says ``False`` and the disposition that comes
    back is still ``executed``.

    **The two crossings are indistinguishable, and that is the point rather than a gap.**
    §2 gives a restatement ADR-0170 §4's second shape exactly — ``turn`` ``None``,
    ``routed`` ``None``, ``reply`` ``None``, ``reply_degraded`` ``False``, a ``step`` —
    which is the same shape a resume driven from a **recovered** park produces
    (ADR-0052 §3, and ``_compose`` declines on a pass with no turn). The bodies are
    therefore equal, so no front end can tell a restatement from a resolution by reading
    one; ``app.js`` states its own history instead of guessing, and ``_outcome_view``
    invents no member to tell them apart, which would be this adapter authoring a fact
    the engine did not state (ADR-0168 §1).
    """
    async with _harness(_holding(_confirmation(_span("body")))) as one:
        first_status, first = await one.whole(
            "POST", "/confirmation/resume", {"token": "h-1", "approved": True}
        )
        second_status, second = await one.whole(
            "POST", "/confirmation/resume", {"token": "h-1", "approved": False}
        )

        assert first_status == 200, first
        # Not a fault, which is the whole of what the page needed: an
        # ``UnknownContinuationError`` here would cross as ``422 assistant-declined``
        # and read as a denial for an action that ran (ADR-0084 §7).
        assert second_status == 200, second
        assert second["outcome"]["step"]["disposition"] == "executed"
        assert second["outcome"]["reply"] is None
        assert second["outcome"]["reply_degraded"] is False
        assert second["outcome"]["routed"] is None
        assert second["outcome"]["steps"] == []
        assert second["outcome"] == first["outcome"]
        # And it reached the engine: the gateway relayed the second answer rather than
        # holding state of its own about which tokens it had already spent.
        assert one.engine.calls == [
            ("resume", {"token": "h-1", "approved": True}),
            ("resume", {"token": "h-1", "approved": False}),
        ]


class _Unknown(FakeAssistantEngine):
    """An engine that resolves no token, as one that has restarted does."""

    async def resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, as the Protocol declares it
    ) -> TurnOutcome:
        """Refuse the way ADR-0084 §7 requires: never as a denial."""
        self.calls.append(("resume", {"token": token.handle, "approved": approved}))
        msg = "this token names no step awaiting confirmation in this engine"
        raise UnknownContinuationError(msg)


async def test_a_token_the_engine_cannot_resolve_is_the_hubs_own_refusal() -> None:
    """ADR-0168 §9: a request the hub received and declined is ``assistant-declined``,
    which is what an evicted or restarted park is.

    It is emphatically not a denial (ADR-0084 §7): nobody ruled on this action, and the
    page's route back is ``pending_confirmations`` for a freshly minted token.
    """
    async with _harness(_Unknown()) as one:
        status, body = await one.whole(
            "POST", "/confirmation/resume", {"token": "h-gone", "approved": True}
        )

        assert status == 422
        assert body["fault"] == "assistant-declined"


@pytest.mark.parametrize(
    "payload",
    [
        {"approved": True},
        {"token": "h-1"},
        {"token": "", "approved": True},
        {"token": 1, "approved": True},
        {"token": "h-1", "approved": "yes"},
        {"token": "h-1", "approved": 1},
    ],
)
async def test_an_answer_the_surface_cannot_read_reaches_no_engine(
    payload: dict[str, Any],
) -> None:
    """The two members, read as themselves and neither defaulted nor coerced.

    ``approved`` is the member this matters most for: a truthy string arriving as an
    acceptance would have this adapter decide what the user consented to, which is the
    one thing ADR-0042 §6 forbids a surface anywhere in this system. A blank token is
    refused for the shape reason instead — every token this surface can carry came from
    a view it built, so one that names nothing means the page and the gateway disagree.
    """
    async with _harness(_holding(_confirmation(_span("body")))) as one:
        status, body = await one.whole("POST", "/confirmation/resume", payload)

        assert status == 400
        assert body["fault"] == "malformed-request"
        assert one.engine.calls == []
