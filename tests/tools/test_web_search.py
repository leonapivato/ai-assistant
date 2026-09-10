"""ADR-0231's searcher: the order it acts in, and what it mints from an answer.

ADR-0231 §18 names the representative inputs this decision owes, and the ones a
searcher owes rather than a servicer or a transport are here, in the ADR's own
numbering so that a later reader walking the list does not have to reconstruct it:

* **8** — a response declaring no report instant mints nothing, and an unreadable one
  is the same refusal.
* **9** — the drops ADR-0231 §10 states, each over each span and each of the four
  forms its totality rule admits, with the siblings still minted in order.
* **13** — the credential is read inside the authorised call and nowhere else.
* **13a** — a call mutated after construction reaches no credential and no channel.
* **13aa** — a bound account that moves under the credential read sends nothing.
* **13b** — the content bound tested at the boundary and not only over it.
* **14** — the invocation is claimed and completed, and an interrupted one stays open.
* **12a**'s spend arm — a refused admission reaches no credential, no channel, no
  claim and no completion.

Two of §18's arms are elsewhere on purpose. **12** — "the declaration is in no
registry" — is a property of a *composition* and is asserted in
``tests/app/test_composition_web_search.py``, where it can be broken. **11** and the
response bound's own boundary are Lane 2's, over the exchange, in
``test_https_exchange.py``.

**Nothing here opens a socket** (see ``web_search_harness``), and no case reads a
clock: the instant every record is attested to is the one the scripted response
declares, which is ADR-0092 §3's rule made testable rather than merely stated.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from egress_transport_harness import CREDENTIAL, IDENTITY, REFERENCE, SLOT, Records, entry
from web_search_harness import (
    DATE_FIELD,
    MAX_RESULT_CHARS,
    MAX_RESULTS,
    OMITTED,
    ORIGIN,
    QUERY,
    REPORTED_AT,
    GatedTransport,
    InterruptingTransport,
    RaisingTransport,
    RefusingGate,
    ReprovisioningRecords,
    SlowGate,
    StallingTransport,
    answering,
    authorised_search,
    body,
    built,
    elsewhere_account,
    far_end,
    request,
    response,
    result,
    suspendable,
)
from web_searcher_contract import (
    A_BOUND,
    ConnectedAccount,
    GatedSearch,
    ScriptedRefusal,
    ScriptedSearch,
    WebSearcherContract,
)

from ai_assistant.core.errors import (
    AuthorisationSpentError,
    ConnectionStoreError,
    ToolBindingError,
    ToolError,
    TransportError,
)
from ai_assistant.core.types import (
    CostBasis,
    MemorySource,
    PermissionOutcome,
    SearchRefusal,
    ToolOutcome,
)
from ai_assistant.orchestration.recovery import RecoveryScan
from ai_assistant.testing import FakeAuditTrail, FakePlanStore
from ai_assistant.tools import web_search
from ai_assistant.tools.egress import TransportPinError
from ai_assistant.tools.web_search import (
    MAX_JSON_DEPTH,
    WEB_SEARCH,
    WEB_SEARCH_SOURCE_NAME,
    WebSearchEgress,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import ToolCall

pytestmark = pytest.mark.anyio

#: A content bound small enough that the boundary cases script a handful of
#: characters rather than a paragraph. Nothing in the contract is a function of it.
_SMALL_CONTENT_BOUND: Final = 64

#: The bound a case sets when it wants the deadline to fire (ADR-0241 §1). Small
#: enough that the wait is a fraction of a second and large enough that a loaded
#: machine still reaches the stage under test before it expires.
_EXPIRING_BOUND: Final = timedelta(milliseconds=200)

#: How much longer than its bound an expiring search may take before the case calls
#: it a hang. Generous, because what Arm 1 asserts is that the search **stops** —
#: a tight figure would fail on a busy machine while asserting nothing more.
_SLACK: Final = timedelta(seconds=5)


async def _searched(*, timeout: timedelta = A_BOUND, **arrangement: Any) -> Any:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, §2)
    """Drive one authorised search over a subject arranged by ``arrangement``.

    Args:
        timeout: The bound to pass (ADR-0241 §1). Defaults to a figure no case here
            reaches by accident, so a case that fails is failing on its own clause.
        arrangement: Passed straight to ``web_search_harness.built``.

    Returns:
        The outcome and the arrangement, so a case can assert on both.
    """
    subject = await built(**arrangement)
    call = await authorised_search(subject.trail, proposal=await request(subject))
    return await subject.searcher.search(call, timeout=timeout), subject


# --------------------------------------------------------------------------- #
# the shared conformance suite
# --------------------------------------------------------------------------- #


class TestWebSearchEgressContract(WebSearcherContract):
    """``WebSearchEgress`` against the shared suite (ADR-0231 §17).

    Every subject below is the *real* searcher over a scripted far end, so what the
    suite drives is the production order — the three checks, the admission, the claim
    and the completion — and not a stand-in for it.
    """

    #: ADR-0231 §17: ``app/composition.py`` "constructs a searcher only where an
    #: account is connected", so this implementation has no unconnected state to
    #: exhibit. See the suite's own note for why the two §17 clauses agree.
    constructed_only_with_an_account = True

    @pytest.fixture
    async def searcher(self) -> WebSearchEgress:
        subject = await built(channels=[answering(result())])
        return subject.integration.searcher

    def results_bound(self) -> int:
        return MAX_RESULTS

    def content_bound(self) -> int:
        return _SMALL_CONTENT_BOUND

    async def searching(self, results: int) -> ScriptedSearch:
        # Distinct, short contents: distinct so an implementation minting one record
        # per result and one minting the same record twice are told apart, and short
        # so that none of them meets the small content bound this harness configures.
        answers = [
            result(title=f"t{index}", url=f"https://example.invalid/{index}", description=None)
            for index in range(results)
        ]
        searcher, call = await self._prepared(channels=[answering(*answers)])
        return ScriptedSearch(searcher=searcher, call=call)

    async def refusing(self, refusal: SearchRefusal) -> ScriptedRefusal:
        searcher, call = await self._refusing(refusal)
        # ADR-0241 §4's member is the one a *bound* reaches rather than a script, so
        # the arrangement below stalls the transport and this hook names the bound
        # that expires against it. Every other member fits inside the suite's own.
        bound = _EXPIRING_BOUND if refusal is SearchRefusal.DEADLINE_EXPIRED else A_BOUND
        return ScriptedRefusal(searcher=searcher, call=call, timeout=bound)

    async def gated(self) -> GatedSearch:
        transport = GatedTransport(answering(result()))
        searcher, call = await self._prepared(transport=transport)
        return GatedSearch(searcher=searcher, call=call, arm=transport.suspend_next)

    async def connected(self) -> ConnectedAccount:
        searcher, _ = await self._prepared(channels=[answering(result())])
        return ConnectedAccount(searcher=searcher, origin=ORIGIN, declaration=WEB_SEARCH)

    async def unconnected(self) -> WebSearchEgress:  # pragma: no cover — see the flag
        raise NotImplementedError

    async def _prepared(self, **arrangement: Any) -> tuple[WebSearchEgress, ToolCall]:
        """A subject and the authorised call that reaches its scripted answer.

        Args:
            arrangement: Passed straight to ``web_search_harness.built``.

        Returns:
            The searcher and the call.
        """
        subject = await built(max_result_chars=_SMALL_CONTENT_BOUND, **arrangement)
        proposal = await request(subject)
        return subject.searcher, await authorised_search(subject.trail, proposal=proposal)

    async def _refusing(self, refusal: SearchRefusal) -> tuple[WebSearchEgress, ToolCall]:
        """A subject whose search refuses with ``refusal``, and the call that reaches it.

        Every one is driven from a *real* cause rather than from a switch: a gate that
        refuses, a transport that will not connect, a body that is not the documented
        shape, a bound of one byte, a response with no ``Date``, and a response with no
        results. That is what makes ADR-0231 §17's "raises for no source reason"
        an assertion about this searcher rather than about a stub.

        Args:
            refusal: The class to reach.

        Returns:
            The searcher and the call.
        """
        arrangements: dict[SearchRefusal, dict[str, Any]] = {
            SearchRefusal.SPEND_REFUSED: {"gate": RefusingGate()},
            SearchRefusal.TRANSPORT_FAILED: {
                "refusal": TransportError("this file connects to nothing")
            },
            # A **real** stall and a real bound, not a scripted class: ADR-0241 §12's
            # Arm 1 asks for "a stub origin that connects and never answers", so the
            # member the suite parametrises over is reached the way a deployment
            # reaches it.
            SearchRefusal.DEADLINE_EXPIRED: {"transport": StallingTransport()},
            SearchRefusal.PROVIDER_REFUSED: {
                "channels": [far_end(response(payload=b"not the documented shape"))]
            },
            SearchRefusal.RESPONSE_TOO_LARGE: {
                "channels": [answering(result())],
                "max_response_bytes": 1,
            },
            SearchRefusal.UNATTESTED: {"channels": [answering(result(), date=None)]},
            SearchRefusal.NO_RESULT: {"channels": [answering()]},
        }
        return await self._prepared(**arrangements[refusal])


# --------------------------------------------------------------------------- #
# what `request` proposes (ADR-0231 §6, §17)
# --------------------------------------------------------------------------- #


async def test_request_carries_the_registered_origin_and_no_binding() -> None:
    """§17's request clause, over the production searcher.

    The origin is the **registration's** and not a caller's: there is no parameter
    through which one could arrive, which is what makes "the recipient is fixed by the
    connected account and reachable by no argument the model can write" a property of
    the signature rather than a rule (ADR-0231 §5).
    """
    subject = await built()

    proposal = await subject.searcher.request(QUERY)

    assert proposal is not None
    assert proposal.tool == WEB_SEARCH
    assert dict(proposal.parameters) == {"origin": ORIGIN, "query": QUERY}
    assert proposal.step_id is None
    assert proposal.execution_id is None
    assert proposal.egress_binding is None


async def test_request_reads_no_store_opens_no_channel_and_reads_no_credential() -> None:
    """§17: ``request`` "reads no store, mints no identifier, opens no channel and
    reaches no authorisation conclusion"."""
    subject = await built()

    await subject.searcher.request(QUERY)

    assert subject.records.reads == []
    assert subject.keyring.reads == []
    assert subject.transport.attempts == ()
    assert await subject.trail.export_invocations() == []


# --------------------------------------------------------------------------- #
# 8. a response with no readable report instant mints nothing
# --------------------------------------------------------------------------- #


async def test_a_response_declaring_no_instant_mints_nothing() -> None:
    """§18 arm 8, and ADR-0092 §3 through it.

    The response is one the provider shape admits and carries a result; what it does
    not carry is the instant the record would be attested to. There is no substitute,
    so the search yields nothing.
    """
    outcome, _ = await _searched(channels=[answering(result(), date=None)])

    assert outcome.refusal is SearchRefusal.UNATTESTED
    assert outcome.records == ()
    assert outcome.reported_at is None


@pytest.mark.parametrize(
    "date",
    [
        pytest.param("not an instant at all", id="a-malformed-string"),
        pytest.param("Sun, 06 Nov 94 08:49:37 GMT", id="a-two-digit-year"),
        pytest.param("Sunday, 06-Nov-94 08:49:37 GMT", id="the-rfc-850-format"),
        pytest.param("Sun Nov  6 08:49:37 1994", id="the-asctime-format"),
        pytest.param("Fri, 04 Sep 2026 12:00:00 UTC", id="a-zone-that-is-not-gmt"),
        pytest.param("Fri, 31 Sep 2026 12:00:00 GMT", id="a-day-september-does-not-have"),
        pytest.param("Fri, 04 Sep 2026 25:00:00 GMT", id="an-hour-out-of-range"),
        pytest.param("Fri, 04 Xxx 2026 12:00:00 GMT", id="a-month-that-is-not-one"),
        pytest.param("Fri, ²4 Sep 2026 12:00:00 GMT", id="a-non-ascii-digit"),
    ],
)
async def test_an_unreadable_instant_is_the_same_refusal_as_none(date: str) -> None:
    """§18 arm 8's second half, and §10's clause that makes them one answer.

    "A value carried in that position which cannot be read as an instant is not a
    declared one" — the same closed answer rather than a new one, "written down so
    that no implementation reads an unparseable field as licence to fall back to a
    clock it read". Every arm here fails an implementation that did.

    The non-ASCII digit arm is the one a permissive parser gets wrong in the worst
    direction: ``"²".isdigit()`` is ``True`` and ``int("²")`` raises, so a check that
    tested ``isdigit`` without ``isascii`` would not read the date *and* would raise a
    ``ValueError`` out of a member ADR-0231 §17 says only a cancellation leaves.
    """
    outcome, _ = await _searched(channels=[answering(result(), date=date)])

    assert outcome.refusal is SearchRefusal.UNATTESTED


async def test_two_date_fields_declare_no_instant_this_searcher_will_pick_between() -> None:
    """§10's "no substitute", at the one place a client could invent one.

    A far end sending two ``Date`` fields has declared two instants. Taking the first
    would be this system choosing which of the provider's statements to attest to,
    which is exactly the substitution ADR-0092 §3 forbids.
    """
    doubled = response(date=DATE_FIELD, headers=[f"Date: {DATE_FIELD}"], payload=body(result()))

    outcome, _ = await _searched(channels=[far_end(doubled)])

    assert outcome.refusal is SearchRefusal.UNATTESTED


async def test_the_declared_instant_is_the_one_every_record_is_attested_to() -> None:
    """§10: ``reported_at`` "is the instant the provider's own response declares".

    Asserted on the outcome *and* on the record, because ``SearchOutcome`` requires
    them equal and a case reading only one would pass against an implementation that
    put a clock in both.
    """
    outcome, _ = await _searched(channels=[answering(result())])

    assert outcome.reported_at == REPORTED_AT
    assert [record.provenance.attestation.reported_at for record in outcome.records] == [
        REPORTED_AT
    ]


# --------------------------------------------------------------------------- #
# 9. what §10 transcribes, and what it drops
# --------------------------------------------------------------------------- #


async def test_a_kept_result_transcribes_three_spans_verbatim_one_per_line() -> None:
    """§10's fixed form: title, address, snippet, one per line, no other byte added.

    The leading and trailing spaces are the case §10's absence rule "comes closest to
    swallowing": a title of ``" x "`` is *present* and is transcribed with both spaces
    intact, which fails an implementation that trims a span on its way to deciding
    whether one is absent.
    """
    outcome, _ = await _searched(
        channels=[
            answering(result(title=" x ", url="https://example.invalid/a", description="a snippet"))
        ]
    )

    assert [record.content for record in outcome.records] == [
        " x \nhttps://example.invalid/a\na snippet"
    ]


@pytest.mark.parametrize(
    "absent",
    [
        pytest.param(OMITTED, id="the-field-omitted"),
        pytest.param(None, id="null"),
        pytest.param("", id="the-empty-string"),
        pytest.param(
            "\u00a0\t",
            id="whitespace-alone-including-a-non-ascii-space",
        ),
    ],
)
@pytest.mark.parametrize("span", ["title", "description"])
async def test_an_absent_title_or_snippet_omits_its_line_and_moves_no_other_byte(
    span: str, absent: Any
) -> None:
    """§18 arm 9: absence in each of the four forms §10 admits, over each span.

    "An absent title or snippet omits its line and no other byte moves." An
    implementation that read ``""`` as a title mints a record one line longer than a
    conforming one over the same response, and fails here.
    """
    outcome, _ = await _searched(
        channels=[
            answering(
                result(
                    **{span: absent},
                    url="https://example.invalid/a",
                    **({} if span == "title" else {"title": "a title"}),
                    **({} if span == "description" else {"description": "a snippet"}),
                )
            )
        ]
    )

    kept = "a snippet" if span == "title" else "a title"
    assert [record.content for record in outcome.records] == [
        f"https://example.invalid/a\n{kept}"
        if span == "title"
        else f"{kept}\nhttps://example.invalid/a"
    ]


@pytest.mark.parametrize(
    "absent",
    [
        pytest.param(OMITTED, id="the-field-omitted"),
        pytest.param(None, id="null"),
        pytest.param("", id="the-empty-string"),
        pytest.param(
            "\u00a0\t",
            id="whitespace-alone-including-a-non-ascii-space",
        ),
    ],
)
async def test_a_result_whose_address_is_absent_is_dropped(absent: Any) -> None:
    """§10: "a result whose **address** is absent is dropped".

    A result *is* a title, an address and a snippet; transcribing two of the source's
    three spans would be this system deciding which of them mattered.
    """
    outcome, _ = await _searched(
        channels=[
            answering(
                result(url=absent),
                result(title="kept", url="https://a.invalid/k", description=None),
            )
        ]
    )

    assert [record.content for record in outcome.records] == ["kept\nhttps://a.invalid/k"]


@pytest.mark.parametrize("break_character", ["\n", "\r"])
@pytest.mark.parametrize("span", ["title", "url", "description"])
async def test_a_result_whose_span_carries_a_line_break_is_dropped_whole(
    span: str, break_character: str
) -> None:
    """§18 arm 9: "one arm per span and per character".

    "Since an implementation that guards the title and forgets the snippet passes a
    single-span test." An implementation that *transcribed* a break passes every other
    case in this file and fails these, because its record's line count no longer says
    which span is which.
    """
    carrying = {span: f"before{break_character}after"}
    if span != "url":
        carrying["url"] = "https://example.invalid/a"

    outcome, _ = await _searched(
        channels=[
            answering(
                result(**carrying),
                result(title="kept", url="https://a.invalid/k", description=None),
            )
        ]
    )

    assert [record.content for record in outcome.records] == ["kept\nhttps://a.invalid/k"]


@pytest.mark.parametrize(
    "ill_typed",
    [
        pytest.param(42, id="a-number"),
        pytest.param(True, id="a-boolean"),
        pytest.param({"nested": "object"}, id="an-object"),
        pytest.param(["an", "array"], id="an-array"),
    ],
)
@pytest.mark.parametrize("span", ["title", "url", "description"])
async def test_a_non_string_span_drops_its_result_and_its_siblings_are_minted(
    span: str, ill_typed: Any
) -> None:
    """§18 arm 9's fourth form, over each of the three span positions.

    "That fails an implementation that coerces a non-string to its textual form, which
    would mint a record no other conforming implementation over the same response
    mints, and one that treats it as absent, which would mint a record one line
    shorter."
    """
    carrying = {span: ill_typed}
    if span != "url":
        carrying["url"] = "https://example.invalid/a"

    outcome, _ = await _searched(
        channels=[
            answering(
                result(**carrying),
                result(title="kept", url="https://a.invalid/k", description=None),
            )
        ]
    )

    assert [record.content for record in outcome.records] == ["kept\nhttps://a.invalid/k"]


@pytest.mark.parametrize(
    "every",
    [
        pytest.param([result(url=None)], id="every-address-absent"),
        pytest.param([result(title="a\nb")], id="every-span-carrying-a-break"),
        pytest.param([result(description=7)], id="every-span-ill-typed"),
        pytest.param([result(title="x" * 400)], id="every-content-over-the-bound"),
    ],
)
async def test_a_response_every_result_of_which_is_dropped_is_no_result(
    every: list[dict[str, Any]],
) -> None:
    """§18 arm 9: dropped for **any** of the reasons, and "rather than an empty success".

    ``NO_RESULT`` and not a success carrying no record: ``SearchOutcome`` refuses the
    latter outright, which is what makes this a statement about the searcher's
    classification rather than about the value.
    """
    outcome, _ = await _searched(
        channels=[answering(*every)], max_result_chars=_SMALL_CONTENT_BOUND
    )

    assert outcome.refusal is SearchRefusal.NO_RESULT
    assert outcome.records == ()


async def test_a_response_carrying_no_result_at_all_is_no_result() -> None:
    """§10: a response carrying no result yields nothing, and is not a shape refusal.

    Two arms, because the documented response expresses "nothing matched" both ways —
    an empty list, and no group at all — and reading the second as malformed would
    report a provider that answered perfectly well as one that answered something else.
    """
    empty, _ = await _searched(channels=[answering()])
    absent, _ = await _searched(channels=[far_end(response(payload=body(group=False)))])

    assert empty.refusal is SearchRefusal.NO_RESULT
    assert absent.refusal is SearchRefusal.NO_RESULT


async def test_a_response_carrying_more_results_than_the_count_mints_exactly_that_many() -> None:
    """§18 arm 9: "in the order the provider returned them"."""
    answers = [
        result(title=f"t{index}", url=f"https://example.invalid/{index}", description=None)
        for index in range(MAX_RESULTS + 2)
    ]

    outcome, _ = await _searched(channels=[answering(*answers)])

    assert [record.content for record in outcome.records] == [
        f"t{index}\nhttps://example.invalid/{index}" for index in range(MAX_RESULTS)
    ]


async def test_a_dropped_result_does_not_cost_a_sibling_its_slot() -> None:
    """The reading ``_minted`` states, asserted rather than left to a docstring.

    The walk steps over a dropped result and stops once ``search_max_results`` records
    exist, so a response whose *first* result is over the content bound still yields
    the count the operator configured where the provider supplied enough usable ones.
    An implementation that capped the results considered and then dropped would mint
    two here.
    """
    answers = [
        result(title="x" * 400, url="https://example.invalid/dropped"),
        *(
            result(title=f"t{index}", url=f"https://example.invalid/{index}", description=None)
            for index in range(MAX_RESULTS)
        ),
    ]

    outcome, _ = await _searched(
        channels=[answering(*answers)], max_result_chars=_SMALL_CONTENT_BOUND
    )

    assert len(outcome.records) == MAX_RESULTS


async def test_every_minted_record_carries_the_provenance_section_ten_fixes() -> None:
    """§10's ``Provenance`` clause, field by field.

    Each is a value a later reader acts on: the band ``EXTERNAL`` places the record in,
    the confidence every attested producer carries, the empty evidence that says this
    is not a citation target, and the ``derived_from_external`` that asserts nothing
    in this band (ADR-0106 §1).
    """
    outcome, _ = await _searched(channels=[answering(result())])

    (record,) = outcome.records
    assert record.kind == "semantic"
    assert record.provenance.source is MemorySource.EXTERNAL
    assert record.provenance.confidence == pytest.approx(0.9)
    assert record.provenance.evidence == ()
    assert record.provenance.derived_from_external is False
    assert record.topics == ()
    assert record.about_person is None
    assert record.provenance.attestation is not None
    assert record.provenance.attestation.reported_by == WEB_SEARCH_SOURCE_NAME
    assert record.provenance.attestation.extent is None


# --------------------------------------------------------------------------- #
# 13b. the content bound at the boundary and not only over it
# --------------------------------------------------------------------------- #


async def test_a_content_at_the_bound_is_minted_and_one_character_longer_is_dropped() -> None:
    """§18 arm 13b: "fails an implementation whose comparison is the wrong way round".

    The figure is the **quoted** rendering's length, as ADR-0230 §6 measures one: the
    two delimiters ``json.dumps`` adds are inside the bound, so a case computing the
    content's own length would arrange the wrong pair.
    """
    address = "https://a.invalid/x"
    padding = 0
    while len(json.dumps(f"{'t' * padding}\n{address}")) < _SMALL_CONTENT_BOUND:
        padding += 1
    at_the_bound = "t" * padding
    assert len(json.dumps(f"{at_the_bound}\n{address}")) == _SMALL_CONTENT_BOUND

    kept, _ = await _searched(
        channels=[answering(result(title=at_the_bound, url=address, description=None))],
        max_result_chars=_SMALL_CONTENT_BOUND,
    )
    dropped, _ = await _searched(
        channels=[answering(result(title=at_the_bound + "t", url=address, description=None))],
        max_result_chars=_SMALL_CONTENT_BOUND,
    )

    assert [record.content for record in kept.records] == [f"{at_the_bound}\n{address}"]
    assert dropped.refusal is SearchRefusal.NO_RESULT


async def test_the_bound_is_counted_on_the_quoted_rendering_and_not_on_the_source() -> None:
    """ADR-0230 §6's measure, and ADR-0222 §4's reason for it.

    An astral code point renders as two surrogate escapes — twelve output characters
    for one source character — so a searcher counting source characters would admit a
    result twelve times the length its operator configured. Arranged so that the
    source is comfortably inside the bound and the rendering is comfortably over it.
    """
    address = "https://a.invalid/x"
    title = "\U0001f600" * 8

    outcome, _ = await _searched(
        channels=[answering(result(title=title, url=address, description=None))],
        max_result_chars=_SMALL_CONTENT_BOUND,
    )

    assert len(f"{title}\n{address}") < _SMALL_CONTENT_BOUND
    assert len(json.dumps(f"{title}\n{address}")) > _SMALL_CONTENT_BOUND
    assert outcome.refusal is SearchRefusal.NO_RESULT


# --------------------------------------------------------------------------- #
# what the provider said, and what this system could not reach
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "status",
    [
        pytest.param("HTTP/1.1 204 No Content", id="a-2xx-carrying-no-representation"),
        pytest.param("HTTP/1.1 401 Unauthorized", id="a-rejected-credential"),
        pytest.param("HTTP/1.1 429 Too Many Requests", id="a-rate-limit"),
        pytest.param("HTTP/1.1 503 Service Unavailable", id="an-outage-the-far-end-reports"),
    ],
)
async def test_a_status_a_search_cannot_be_read_out_of_is_provider_refused(status: str) -> None:
    """One status is read, and every other is the provider answering something else.

    A ``204`` is the arm worth stating: it is a *success*, and calling it a search of
    zero results would report ``NO_RESULT`` where the honest answer is that no
    representation was sent at all.
    """
    outcome, _ = await _searched(
        channels=[far_end(response(status=status, payload=body(result())))]
    )

    assert outcome.refusal is SearchRefusal.PROVIDER_REFUSED


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"", id="an-empty-body"),
        pytest.param(b"not json at all", id="octets-that-are-not-json"),
        pytest.param(b"[]", id="json-that-is-not-an-object"),
        pytest.param(b"\xff\xfe", id="octets-that-are-not-utf-8"),
        pytest.param(b'{"web": []}', id="a-group-of-the-wrong-type"),
        pytest.param(b'{"web": {"results": {}}}', id="a-result-list-of-the-wrong-type"),
        pytest.param(b'{"web": {"results": ["a string"]}}', id="a-result-that-is-not-an-object"),
    ],
)
async def test_a_body_that_is_not_the_documented_shape_is_provider_refused(payload: bytes) -> None:
    """§10: refused "before this clause is reached".

    Every arm is a *well-formed HTTP response* — the exchange read it and handed it
    back — carrying a payload no documented answer carries. That is the provider
    answering something else, which is a different operator fact from an outage
    (ADR-0231 §13).
    """
    outcome, _ = await _searched(channels=[far_end(response(payload=payload))])

    assert outcome.refusal is SearchRefusal.PROVIDER_REFUSED


@pytest.mark.parametrize(
    "depth",
    [
        pytest.param(MAX_JSON_DEPTH + 1, id="one-past-the-bound"),
        pytest.param(200_000, id="deep-enough-to-exhaust-the-decoders-stack"),
    ],
)
async def test_a_body_nested_past_the_bound_is_provider_refused(depth: int) -> None:
    """A well-formed body the decoder cannot descend is a body, not a fault.

    ``json``'s scanner descends one level per open bracket, so a response nested
    deeply enough exhausts the interpreter's stack rather than failing to parse — and
    that is reachable well inside ``search_max_response_bytes``' default megabyte,
    which is what makes it a response a provider can actually send. ADR-0231 §17 says
    this member raises for no source reason.

    **The deep arm is the one that would fail a caught ``RecursionError``.** A stack
    that has already overflowed is not one an ``except`` clause can be relied on to
    unwind — the first attempt at this fix caught the error and the error left anyway
    — so the depth is bounded off the octets before the decoder is entered, and this
    arm is what says so. The boundary arm beside it fails a comparison the wrong way
    round.
    """
    payload = b'{"web": ' + b"[" * depth + b"]" * depth + b"}"

    outcome, _ = await _searched(
        channels=[far_end(response(payload=payload))], max_response_bytes=len(payload) + 1024
    )

    assert outcome.refusal is SearchRefusal.PROVIDER_REFUSED


async def test_a_title_carrying_literal_brackets_is_transcribed_verbatim() -> None:
    """§10's verbatim clause against the nesting bound: a bracket in a span is a word.

    A result whose title happens to carry more brackets than the structural bound is
    still four levels deep, and §10 admits exactly four drops — an ill-typed span, an
    absent address, a line break, and a content over ``search_max_result_chars``.
    "Carries a bracket" is not among them, so a depth counter that read one would
    refuse a result this decision transcribes.
    """
    brackets = "[" * (MAX_JSON_DEPTH * 4)

    outcome, _ = await _searched(
        channels=[answering(result(title=brackets, url="https://a.invalid/x", description=None))]
    )

    assert [record.content for record in outcome.records] == [f"{brackets}\nhttps://a.invalid/x"]


async def test_an_escaped_quote_does_not_end_the_string_the_brackets_are_inside() -> None:
    """The scanner's third direction: ``\\"`` is a character, not a terminator.

    A title carrying a quotation mark *and* more brackets than the structural bound is
    a perfectly ordinary result — §10 transcribes it verbatim — and it is refused by a
    scanner that read the escaped quote as ending the string, because every bracket
    after it would then be counted as structure. The other two arms never enter this
    branch: one has no quote inside its span and the other has no escape.

    **One quotation mark and not two**, which is what makes this discriminate: an even
    number restores the parity a broken scanner lost, so the brackets land back inside
    a mis-parsed string and are not counted either way. With one, a scanner that
    ignored the escape reads everything after it as structure — verified by removing
    the branch and watching this fail.
    """
    quoted = 'he said " ' + "[" * (MAX_JSON_DEPTH * 4)

    outcome, _ = await _searched(
        channels=[answering(result(title=quoted, url="https://a.invalid/x", description=None))]
    )

    assert [record.content for record in outcome.records] == [f"{quoted}\nhttps://a.invalid/x"]


async def test_closers_inside_a_string_do_not_buy_a_deeper_response() -> None:
    """The bound's other failure direction, which is the one an attacker would use.

    A ``]`` inside an earlier string would *decrement* a naive running depth, so a
    crafted body could carry real nesting past the bound and pass under it — reaching
    the decoder this guard exists to keep it away from. Asserted over a payload whose
    string closers alone would have paid for the nesting that follows.
    """
    payload = (
        b'{"padding": "'
        + b"]" * (MAX_JSON_DEPTH * 3)
        + b'", "web": '
        + b"[" * (MAX_JSON_DEPTH * 2)
        + b"]" * (MAX_JSON_DEPTH * 2)
        + b"}"
    )

    outcome, _ = await _searched(
        channels=[far_end(response(payload=payload))], max_response_bytes=len(payload) + 1024
    )

    assert outcome.refusal is SearchRefusal.PROVIDER_REFUSED


async def test_a_body_at_the_nesting_bound_is_read_normally() -> None:
    """The boundary's other half: a documented answer is four levels deep, not a hundred.

    Without it the bound could be set to one and every case above would still pass
    while the integration refused every real response.
    """
    padding = MAX_JSON_DEPTH - 4
    nested = b"[" * padding + b"]" * padding
    payload = (
        b'{"padding": ' + nested + b', "web": {"results": [{"title": "t", '
        b'"url": "https://a.invalid/x"}]}}'
    )

    outcome, _ = await _searched(
        channels=[far_end(response(payload=payload))], max_response_bytes=len(payload) + 1024
    )

    assert [record.content for record in outcome.records] == ["t\nhttps://a.invalid/x"]


async def test_a_channel_that_cannot_be_opened_is_transport_failed() -> None:
    """§13's operator reading: an outage, and never a statement about the provider."""
    outcome, subject = await _searched(refusal=TransportError("this file connects to nothing"))

    assert outcome.refusal is SearchRefusal.TRANSPORT_FAILED
    assert len(subject.transport.attempts) == 1, "the attempt is recorded even when refused"


async def test_a_redirect_is_transport_failed_and_no_second_channel_is_opened() -> None:
    """ADR-0231 §5's redirect clause, read back through the searcher.

    The exchange refuses one and opens no second channel; what this adds is the class
    the searcher reports for it, which is the value §13's audit carries.
    """
    outcome, subject = await _searched(
        channels=[far_end(response(status="HTTP/1.1 302 Found", headers=["Location: /elsewhere"]))]
    )

    assert outcome.refusal is SearchRefusal.TRANSPORT_FAILED
    assert len(subject.transport.attempts) == 1


async def test_a_response_over_the_read_bound_is_abandoned_and_refused() -> None:
    """ADR-0231 §5, read back through the searcher: nothing is parsed, nothing minted."""
    outcome, _ = await _searched(channels=[answering(result())], max_response_bytes=8)

    assert outcome.refusal is SearchRefusal.RESPONSE_TOO_LARGE
    assert outcome.records == ()


# --------------------------------------------------------------------------- #
# 13. the credential is read inside the authorised call and nowhere else
# --------------------------------------------------------------------------- #


async def test_the_credential_is_read_once_inside_the_authorised_call() -> None:
    """§18 arm 13, and ADR-0148 §7's positional gate through it.

    The read happens, and it happens exactly once and for the slot **the record
    names** — never a slot a binding carried, because a binding carries none.
    """
    _, subject = await _searched(channels=[answering(result())])

    assert subject.keyring.reads == [SLOT]


async def test_a_call_that_never_reaches_the_searcher_reads_no_credential() -> None:
    """§18 arm 13's second half: "a turn whose ruling was not ``ALLOW`` reads none".

    A ``CONFIRM`` or a ``DENY`` constructs no ``ToolCall`` — ``ToolCall``'s own
    validator runs ``authorises`` — so the searcher is never reached, and the assertion
    is over the ``Secrets`` fake that would have recorded a read.
    """
    subject = await built(channels=[answering(result())])

    with pytest.raises(ValueError, match="does not authorise"):
        await authorised_search(
            subject.trail,
            proposal=await request(subject),
            outcome=PermissionOutcome.CONFIRM,
        )

    assert subject.keyring.reads == []
    assert subject.transport.attempts == ()


# --------------------------------------------------------------------------- #
# 13a. a call mutated after construction reaches no credential and no channel
# --------------------------------------------------------------------------- #


async def test_a_call_whose_parameters_were_rewritten_reaches_no_credential() -> None:
    """§18 arm 13a, over ADR-0018 §3's bypass.

    ``frozen=True`` refuses ``call.request = …`` and does nothing about
    ``call.__dict__["request"] = …``. So the payload is rewritten *after* the decision
    bound its digest: revalidation rebuilds the call, the re-evaluated ``authorises``
    sees a digest the decision does not bind, and nothing is read or opened. An
    implementation that trusted construction sends the substituted query.
    """
    subject = await built(channels=[answering(result())])
    call = await authorised_search(subject.trail, proposal=await request(subject))
    call.request.__dict__["parameters"] = {"origin": ORIGIN, "query": "a question nobody asked"}

    with pytest.raises(ToolBindingError, match="not the call that was authorised"):
        await subject.searcher.search(call, timeout=A_BOUND)

    assert subject.keyring.reads == []
    assert subject.transport.attempts == ()
    assert await subject.trail.export_invocations() == []


async def test_a_call_whose_definition_was_replaced_is_refused_against_the_registered_one() -> None:
    """§18 arm 13a's second half — "a **valid but different** definition".

    The check that catches it is ADR-0029 §2's second, and here it compares against
    **the searcher's own registered declaration** rather than a registry's, because
    §5 gives this integration no registry entry. Without it a definition tampered into
    a still-valid state — ADR-0018 §4's case — could reach the callable under a
    ``discloses``, a ``cost`` or a ``risk_level`` other than the one the policy ruled
    on.
    """
    subject = await built(channels=[answering(result())])
    weakened = WEB_SEARCH.model_copy(update={"description": "a description nobody registered"})
    call = await authorised_search(subject.trail, proposal=await request(subject, tool=weakened))

    with pytest.raises(ToolBindingError, match="not the one this searcher registered"):
        await subject.searcher.search(call, timeout=A_BOUND)

    assert subject.keyring.reads == []
    assert subject.transport.attempts == ()
    assert await subject.trail.export_invocations() == []


# --------------------------------------------------------------------------- #
# the pin: a call bound elsewhere reaches nothing (ADR-0231 §5, PR #2074)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("elsewhere", "complaint"),
    [
        pytest.param(
            elsewhere_account(reference="conn-9999"),
            "not registered for",
            id="another-connection",
        ),
        pytest.param(
            {"transport_endpoint": "https://other.example.invalid"},
            "not the one this integration is configured to use",
            id="another-endpoint",
        ),
    ],
)
async def test_a_binding_for_another_account_reaches_no_credential(
    elsewhere: dict[str, str], complaint: str
) -> None:
    """ADR-0148 §6's pre-transmission refusals, and the first is the one that is forgotten.

    "The connection reference the binding carries names the connection record it
    consults", so the reference is compared before the record is read — because the
    record is read **by the registration's** reference. Without it, a binding for
    account B is checked against account A's record and the query goes out under A's
    credential although the approval named B.
    """
    subject = await built(channels=[answering(result())])
    call = await authorised_search(
        subject.trail, proposal=await request(subject, elsewhere=elsewhere)
    )

    with pytest.raises(TransportPinError, match=complaint):
        await subject.searcher.search(call, timeout=A_BOUND)

    assert subject.keyring.reads == []
    assert subject.transport.attempts == ()


async def test_a_ruled_origin_that_is_not_the_registered_one_reaches_no_channel() -> None:
    """ADR-0231 §5's own pin, which PR #2074's waiver put in this lane.

    ``HttpsExchange.get`` takes the origin per call, because §5 makes it a per-call
    argument bearing ``x-egress-destination``; what says the *ruled* origin is the one
    this integration is registered for is this comparison, in the object that holds the
    registration. Compared as **text before it is parsed**, so a spelling that merely
    resolves the same way is a recipient nobody wrote down.
    """
    subject = await built(channels=[answering(result())])
    call = await authorised_search(
        subject.trail, proposal=await request(subject, origin="https://SEARCH.example.invalid")
    )

    with pytest.raises(TransportPinError, match="not the one this integration is registered for"):
        await subject.searcher.search(call, timeout=A_BOUND)

    assert subject.keyring.reads == []
    assert subject.transport.attempts == ()


async def test_a_call_carrying_no_egress_binding_reaches_nothing() -> None:
    """ADR-0148 §8's third floor, restated at the one seam that could ignore it.

    Unreachable through the seam that builds a binding, and checked anyway: what would
    otherwise stand here is a ``cast``, and the value it would assert about is the
    recipient.
    """
    subject = await built(channels=[answering(result())])
    call = await authorised_search(subject.trail, proposal=await request(subject, unbound=True))

    with pytest.raises(ToolBindingError, match="carries no egress binding"):
        await subject.searcher.search(call, timeout=A_BOUND)

    assert subject.keyring.reads == []
    assert subject.transport.attempts == ()


# --------------------------------------------------------------------------- #
# 13aa. a bound account that moves under the credential read sends nothing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("script", "case"),
    [
        pytest.param(
            (entry(), entry(revision=2)),
            "reprovisioned",
            id="a-reprovisioning-inside-the-read",
        ),
        pytest.param((entry(), entry(state=None)), "disconnected", id="a-disconnection"),
        pytest.param(
            (entry(), ConnectionStoreError("the store is down")),
            "unanswerable",
            id="a-second-read-that-cannot-be-answered",
        ),
    ],
)
async def test_an_account_that_moves_across_the_credential_read_sends_nothing(
    script: tuple[Any, ...], case: str
) -> None:
    """§18 arm 13aa, over ADR-0148 §6's discard clause and its fail-closed limb.

    The credential is in hand when the second read happens, so "a read that cannot be
    answered is treated as a changed one": a caller that saw the store's error and
    retried would be retrying with a live credential and no verified account. The
    refusal is the one ADR-0231 §5 names, and **no byte was written to any channel** —
    none was opened.
    """
    del case
    subject = await built(channels=[answering(result())], records=Records(*script))
    call = await authorised_search(subject.trail, proposal=await request(subject))

    outcome = await subject.searcher.search(call, timeout=A_BOUND)

    assert outcome.refusal is SearchRefusal.PROVIDER_REFUSED
    assert subject.keyring.reads == [SLOT], "the credential was read, and then discarded"
    assert subject.transport.attempts == (), "no channel was opened"


async def test_the_slot_asked_for_is_the_one_the_first_read_named() -> None:
    """§18 arm 13aa's fourth arm: the one-step clause, asserted at the ``Secrets`` fake.

    "A conforming implementation offers none before ``Secrets.get``", so the slot asked
    for is the one the pre-read named and **never the successor's**. Arranged by a
    store whose second answer names a different slot: an implementation with an
    ``await`` between the pre-read and the credential access would read the successor's
    slot, and this asserts it did not.
    """
    successor = entry(revision=2, slot=SLOT.model_copy(update={"key": "conn-0001-r2"}))
    subject = await built(channels=[answering(result())], records=Records(entry(), successor))
    call = await authorised_search(subject.trail, proposal=await request(subject))

    outcome = await subject.searcher.search(call, timeout=A_BOUND)

    assert subject.keyring.reads == [SLOT]
    assert outcome.refusal is SearchRefusal.PROVIDER_REFUSED


@pytest.mark.parametrize(
    "after",
    [
        pytest.param(entry(revision=2), id="a-reprovisioning"),
        pytest.param(entry(state=None), id="a-disconnection"),
        pytest.param(None, id="a-record-the-store-no-longer-holds"),
    ],
)
async def test_an_account_that_moves_while_the_credential_read_is_suspended_sends_nothing(
    after: object,
) -> None:
    """§18 arm 13aa's first three arms, over a ``Secrets`` fake **held inside ``get``**.

    This is the interleaving the clause is actually about, and the one a fake that
    answers immediately cannot reach: the bound connection record is reprovisioned —
    and, in the other arms, disconnected or removed — *while the credential read is
    suspended*, so ADR-0148 §6's post-read check runs against a record that moved under
    it. On release **no byte is written to the channel**, the credential is discarded,
    and the outcome is ``PROVIDER_REFUSED``, which is the refusal ADR-0231 §5 names.

    An implementation that read the credential and transmitted passes every other case
    in this file and fails these.
    """
    records = ReprovisioningRecords(entry(), after)  # type: ignore[arg-type]  # None is an arm
    ring = await suspendable(records=records)
    subject = await built(channels=[answering(result())], records=records, secrets=ring)
    call = await authorised_search(subject.trail, proposal=await request(subject))

    gate = ring.suspend_next()
    search = asyncio.ensure_future(subject.searcher.search(call, timeout=A_BOUND))
    await gate.reached()
    await records._reprovision()
    gate.release()
    outcome = await search

    assert outcome.refusal is SearchRefusal.PROVIDER_REFUSED
    assert subject.transport.attempts == (), "no channel was opened"


async def test_no_suspension_is_offered_between_the_record_read_and_the_credential_read() -> None:
    """§18 arm 13aa's **fourth** arm: ADR-0148 §6's one-step clause, at the interleaving.

    A reprovisioning task is queued from inside the pre-read, so it is runnable from
    the instant that read returns and runs at whichever await the searcher reaches
    first. "A conforming implementation offers none before ``Secrets.get``", so the arm
    asserts that **the task has not run when the ``Secrets`` fake is called**, that the
    slot asked for is the one the pre-read named and **never the successor's**, and
    that the send is then discarded ``PROVIDER_REFUSED`` by the post-read check.

    An implementation with an ``await`` in that gap reads a credential the pre-read did
    not name — the window ADR-0097 §5a closes — and fails here while passing every
    other case in this file.
    """
    successor = entry(revision=2, slot=SLOT.model_copy(update={"key": "conn-0001-r2"}))
    records = ReprovisioningRecords(entry(), successor)
    ring = await suspendable(records=records)
    subject = await built(channels=[answering(result())], records=records, secrets=ring)
    call = await authorised_search(subject.trail, proposal=await request(subject))

    # The suspension is armed inside `Secrets.get` and nowhere else, so it is the
    # *first* await this searcher offers after the pre-read — which is exactly where
    # the queued task runs. `moved_at_entry` is recorded before that await, so it
    # answers the question the clause asks: had the successor landed by the time the
    # credential was asked for?
    gate = ring.suspend_next()
    search = asyncio.ensure_future(subject.searcher.search(call, timeout=A_BOUND))
    await gate.reached()
    gate.release()
    outcome = await search

    assert ring.moved_at_entry == [False], "no suspension was offered before the credential read"
    assert ring.reads == [SLOT], "the slot asked for is the pre-read's, never the successor's"
    assert records.reprovisioned, "the queued act did land, at the first await that was offered"
    assert outcome.refusal is SearchRefusal.PROVIDER_REFUSED
    assert subject.transport.attempts == ()


async def test_a_record_that_is_not_connectable_reaches_no_keyring_and_no_channel() -> None:
    """ADR-0148 §6's pre-read limb: nothing is asked under an account that is not one.

    A refusal rather than a raise, which is where this departs from the mail seam and
    why: ADR-0231 §17 makes every source reason a ``SearchRefusal`` member returned
    from ``search``, and "this searcher cannot ask under this account" is one operator
    fact whether it was noticed before the read or after it.
    """
    subject = await built(channels=[answering(result())], records=Records(entry(state=None)))
    call = await authorised_search(subject.trail, proposal=await request(subject))

    outcome = await subject.searcher.search(call, timeout=A_BOUND)

    assert outcome.refusal is SearchRefusal.PROVIDER_REFUSED
    assert subject.keyring.reads == []
    assert subject.transport.attempts == ()


async def test_a_keyring_holding_nothing_under_the_slot_sends_nothing() -> None:
    """An interrupted provisioning act leaves a record naming a slot with no value."""
    subject = await built(channels=[answering(result())], holds=None)
    call = await authorised_search(subject.trail, proposal=await request(subject))

    outcome = await subject.searcher.search(call, timeout=A_BOUND)

    assert outcome.refusal is SearchRefusal.PROVIDER_REFUSED
    assert subject.transport.attempts == ()


async def test_a_first_record_read_that_fails_is_not_converted() -> None:
    """ADR-0148 §6: "A store outage asserts nothing about the call and is never converted".

    The *second* read is different and is covered above. This is the first, where
    nothing is in hand: the store's own error leaves, and the servicer degrades the
    turn on it exactly as ADR-0226 §5 requires it to degrade on anything else.
    """
    subject = await built(
        channels=[answering(result())], records=Records(ConnectionStoreError("the store is down"))
    )
    call = await authorised_search(subject.trail, proposal=await request(subject))

    with pytest.raises(ConnectionStoreError, match="the store is down"):
        await subject.searcher.search(call, timeout=A_BOUND)

    assert subject.keyring.reads == []
    assert subject.transport.attempts == ()


# --------------------------------------------------------------------------- #
# 14 and 12a's spend arm: the ledger, the gate, and what an interruption leaves
# --------------------------------------------------------------------------- #


async def test_a_serviced_search_leaves_one_claim_completed_succeeded() -> None:
    """§18 arm 14: "``orchestration`` claims nothing"; the seam claims and completes."""
    _, subject = await _searched(channels=[answering(result())])

    rows = [row.invocation for row in await subject.trail.export_invocations()]
    claims = [row for row in rows if row.completes is None]
    completions = [row for row in rows if row.completes is not None]

    assert len(claims) == 1, "exactly one claim, appended by the seam and not the loop"
    assert [row.completes for row in completions] == [claims[0].id]
    assert completions[0].outcome is ToolOutcome.SUCCEEDED


@pytest.mark.parametrize(
    ("arrangement", "expected"),
    [
        pytest.param(
            {"refusal": TransportError("this file connects to nothing")},
            ToolOutcome.FAILED,
            id="a-transport-failure-completes-failed",
        ),
        pytest.param(
            {"channels": [answering()]},
            ToolOutcome.SUCCEEDED,
            id="a-completed-call-that-yielded-nothing-completes-succeeded",
        ),
        pytest.param(
            {"channels": [answering(result(), date=None)]},
            ToolOutcome.SUCCEEDED,
            id="an-unattested-answer-completes-succeeded",
        ),
    ],
)
async def test_the_completion_says_what_happened_to_the_call_and_not_to_the_search(
    arrangement: dict[str, Any], expected: ToolOutcome
) -> None:
    """The split ``_result_of`` states, asserted where it could be got wrong.

    ``NO_RESULT`` and ``UNATTESTED`` are answers a provider *gave*: the call was made
    and it completed, so the row says ``SUCCEEDED`` while the search yields nothing. A
    searcher that recorded every refusal as a failed invocation would make the ledger's
    account of what left this machine false in the safe-looking direction.
    """
    _, subject = await _searched(**arrangement)

    completions = [
        row.invocation
        for row in await subject.trail.export_invocations()
        if row.invocation.completes is not None
    ]

    assert [row.outcome for row in completions] == [expected]


async def test_a_refused_admission_reaches_no_credential_no_channel_and_no_claim() -> None:
    """§18 arm 12a's spend arm, and ADR-0194 §3's ordering through it.

    "The spend arm additionally asserts that **no credential is read, no channel is
    opened, no invocation claim is appended and no completion is**, which fails an
    implementation that claimed before consulting the gate."
    """
    gate = RefusingGate()
    subject = await built(channels=[answering(result())], gate=gate)
    call = await authorised_search(subject.trail, proposal=await request(subject))

    outcome = await subject.searcher.search(call, timeout=A_BOUND)

    assert outcome.refusal is SearchRefusal.SPEND_REFUSED
    assert gate.admissions == 1, "the gate was consulted"
    assert subject.keyring.reads == []
    assert subject.transport.attempts == ()
    assert await subject.trail.export_invocations() == []


async def test_an_interruption_on_the_way_to_the_completion_leaves_the_claim_open() -> None:
    """§18 arm 14's second half, "in the direction that would fail an implementation
    which added the recovery arm §6 forbids".

    ADR-0029 §3 requires a ``BaseException`` that is not a cancellation to propagate
    unchanged: no outcome is invented for it, no completion is written, and the claim
    is left open — the honest state for a process being torn down, and the state
    ADR-0231 §6 rules "nothing reconciles".
    """
    subject = await built(transport=InterruptingTransport())
    call = await authorised_search(subject.trail, proposal=await request(subject))

    with pytest.raises(KeyboardInterrupt):
        await subject.searcher.search(call, timeout=A_BOUND)

    rows = [row.invocation for row in await subject.trail.export_invocations()]
    assert len(rows) == 1, "the claim, and no completion for it"
    assert rows[0].completes is None

    # **And it *stays* open**, which is the half that would fail an implementation
    # adding the recovery arm §6 forbids. The scan is driven exactly as the
    # composition root wires it — one store behind the trail and the completer faces —
    # over a plan store holding no execution at all, which is the state a search
    # decision leaves: it has no `step_id` and no `execution_id` (§6), so
    # `_recover_execution` never reaches this claim's approval.
    await RecoveryScan(
        plans=FakePlanStore(), trail=subject.trail, completer=subject.trail
    ).recover()

    after = [row.invocation for row in await subject.trail.export_invocations()]
    assert [row.id for row in after] == [rows[0].id], "the scan completed nothing"
    assert after[0].completes is None
    assert await subject.trail.open_invocations(decision_id=call.decision.id) == [rows[0]]

    # **And no further claim is admitted under that decision** (ADR-0192 §1): "the
    # decision authorised one call", and the claim already spent it. A searcher that
    # retried — or a later lane that resolved the open claim by guessing — would make
    # a second search under an authorisation the user gave once.
    opened = len(subject.transport.attempts)
    with pytest.raises(AuthorisationSpentError):
        await subject.searcher.search(call, timeout=A_BOUND)

    assert len(subject.transport.attempts) == opened, "and the refused claim opened nothing"


# --------------------------------------------------------------------------- #
# what the searcher refuses to be built as
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["", "   ", " search ", "search\n"])
async def test_a_name_the_attestation_would_not_carry_unchanged_is_refused_at_build(
    name: str,
) -> None:
    """ADR-0231 §17's stripping clause, refused where it is configured.

    ``Attestation.reported_by`` is ``Identifier``, which strips what it accepts, so a
    searcher named ``" search "`` would mint a record whose ``reported_by`` is
    ``"search"`` and fail the suite's equality — at a mint, far from the constructor
    that caused it.
    """
    subject = await built()

    with pytest.raises(ValueError, match="name must be non-blank"):
        WebSearchEgress(
            transport=subject.seam,
            ledger=subject.trail,
            gate=subject.trail,
            max_results=MAX_RESULTS,
            max_result_chars=MAX_RESULT_CHARS,
            name=name,
        )


@pytest.mark.parametrize(
    ("bounds", "complaint"),
    [
        pytest.param(
            {"max_results": 0}, "max_results is an integer of at least 1", id="a-count-of-zero"
        ),
        pytest.param(
            {"max_results": 4},
            "max_results is an integer of at most 3",
            id="a-count-over-the-ceiling",
        ),
        pytest.param({"max_results": True}, "max_results is an exact int", id="a-boolean-count"),
        pytest.param(
            {"max_result_chars": 0},
            "max_result_chars is an integer of at least 1",
            id="a-content-bound-of-zero",
        ),
        pytest.param(
            {"max_result_chars": True},
            "max_result_chars is an exact int",
            id="a-boolean-content-bound",
        ),
    ],
)
async def test_a_bound_outside_the_stated_domain_is_refused_at_build(
    bounds: dict[str, Any], complaint: str
) -> None:
    """ADR-0231 §5's domains, at the one place a searcher can be built without ``Settings``.

    The ceiling of three is the clause worth the arm: "§10's figure is the ceiling and
    the setting narrows it, never widens it, so §11's precedence holds in every
    configuration and no deployment can make one search take a third of ADR-0226 §6's
    budget of ten."
    """
    subject = await built()
    arguments = {"max_results": MAX_RESULTS, "max_result_chars": MAX_RESULT_CHARS, **bounds}

    with pytest.raises(ValueError, match=complaint):
        WebSearchEgress(
            transport=subject.seam,
            ledger=subject.trail,
            gate=subject.trail,
            **arguments,
        )


async def test_the_declaration_declares_exactly_the_two_arguments_and_their_keywords() -> None:
    """ADR-0231 §5's schema clause, over the declaration a composition root registers.

    "Its schema declares exactly two arguments: an **origin**, carrying
    ``x-egress-destination: "https"`` and ``x-egress-tier: "operational"``, and a
    **query**, carrying neither keyword."
    """
    properties = WEB_SEARCH.parameters_schema["properties"]
    assert isinstance(properties, Mapping)

    assert set(properties) == {"origin", "query"}
    origin, query = properties["origin"], properties["query"]
    assert isinstance(origin, Mapping)
    assert isinstance(query, Mapping)
    assert origin["x-egress-destination"] == "https"
    assert origin["x-egress-tier"] == "operational"
    assert "x-egress-destination" not in query
    assert "x-egress-tier" not in query


async def test_the_registered_declaration_is_the_one_the_searcher_compares_against() -> None:
    """ADR-0029 §2's second check needs an untampered original, and this is it.

    A composition root that built a searcher against one declaration and registered
    another would give the seam a comparison that can never pass — so the builder holds
    one value, and this is the assertion that it does.
    """
    subject = await built()

    proposal = await subject.searcher.request(QUERY)

    assert proposal is not None
    assert proposal.tool == WEB_SEARCH
    assert subject.integration.registration.tool_id == WEB_SEARCH.id
    assert subject.integration.registration.reference == REFERENCE
    assert subject.integration.registration.transport_endpoint == ORIGIN


async def test_the_account_identity_is_never_read_out_of_the_binding_into_a_query() -> None:
    """ADR-0231 §5: the one value that crosses into the request is the query.

    The request written to the channel carries the query and the origin the operator
    configured, and nothing about the account: neither its identity nor its reference
    appears in the target this integration composed. The credential does travel, in the
    one field the seam writes it into — which is what the assertion below distinguishes.
    """
    channel = answering(result())
    outcome, _ = await _searched(channels=[channel])
    assert outcome.records, "the arrangement is one that actually sent a request"

    written = channel.written.decode("ascii", "replace")
    request_line = written.split("\r\n", 1)[0]
    assert IDENTITY not in written
    assert REFERENCE not in written
    assert CREDENTIAL in written, "the credential travels, in its own field"
    assert CREDENTIAL not in request_line, "and never in the request target"


# --------------------------------------------------------------------------- #
# ADR-0241 §12: the bound, where it reaches and where it deliberately does not
# --------------------------------------------------------------------------- #


async def test_a_search_that_never_answers_is_terminated_within_its_bound() -> None:
    """ADR-0241 §12's **Arm 1**, over the production searcher.

    A stub origin that connects and never answers, a real bound and a real stall —
    "because a fake clock would assert nothing about the property the acceptance
    sentence names". What comes back is `DEADLINE_EXPIRED` and **not**
    `TRANSPORT_FAILED`, which is the whole of §4: while one member carried both an
    expiry and a refused connection, no mapping from it could apply ADR-0029 §4's
    ``FAILED``-or-``INDETERMINATE`` rule to the first without applying it to the
    second.

    **The ledger is prompt here on purpose** (§12): §1's third clause says the bound
    does not reach either append, so an arm that stalled the store instead would be
    asserting a guarantee this ADR does not make. Arm 10 below asserts that negative.
    """
    transport = StallingTransport()
    subject = await built(transport=transport)
    call = await authorised_search(subject.trail, proposal=await request(subject))

    started = asyncio.get_running_loop().time()
    outcome = await subject.searcher.search(call, timeout=_EXPIRING_BOUND)
    elapsed = asyncio.get_running_loop().time() - started

    assert outcome.refusal is SearchRefusal.DEADLINE_EXPIRED
    assert outcome.records == ()
    assert elapsed < (_EXPIRING_BOUND + _SLACK).total_seconds(), (
        "a deliberately stalled search is terminated within the declared bound"
    )
    assert transport.attempts, "and the arrangement really did reach the transport"


async def test_an_expired_search_completes_indeterminate_with_an_unknown_cost() -> None:
    """ADR-0241 §12's **Arm 2**, and the live defect §5 corrects.

    ``WEB_SEARCH`` is ``side_effecting`` with ``idempotency`` ``NONE``, so its
    ``interrupted_outcome`` is ``INDETERMINATE``. Recording ``FAILED`` — which is what
    the tree wrote before this decision — says *the call did not act* about a search
    whose query may have left the machine and may have been served and billed, the one
    direction ADR-0014 §4 refuses to guess in.

    **The arm asserts the outcome member and not merely that a row exists**, because
    ``FAILED`` is what a row would have said before, and because a cancellation of the
    same call already completed ``INDETERMINATE`` — the asymmetry §5 names as the bug.
    """
    subject = await built(transport=StallingTransport())
    call = await authorised_search(subject.trail, proposal=await request(subject))

    outcome = await subject.searcher.search(call, timeout=_EXPIRING_BOUND)

    assert outcome.refusal is SearchRefusal.DEADLINE_EXPIRED
    rows = [row.invocation for row in await subject.trail.export_invocations()]
    completions = [row for row in rows if row.completes is not None]
    assert len(rows) == 2, "one claim and one completion for it"
    assert [row.outcome for row in completions] == [ToolOutcome.INDETERMINATE]
    assert completions[0].incurred_cost is not None
    assert completions[0].incurred_cost.basis is CostBasis.UNKNOWN, (
        "ADR-0194 §2's estimate/reported boundary: no lane substitutes the declared "
        "per-call figure for the figure nothing measured"
    )


async def test_an_expiry_inside_the_admission_writes_no_row_at_all() -> None:
    """ADR-0241 §12's **Arm 2b**: the expiry that lands before the claim.

    ADR-0192 §1's placement is relied upon and not moved — before the claim there is
    no invocation row, and inventing one for a call that provably never ran would be
    the opposite error to the one §5 corrects. So the servicing still reports
    ``DEADLINE_EXPIRED`` and the ledger holds nothing.

    The gate takes many times the bound, so the expiry lands *inside* the admission
    with certainty rather than by arithmetic — which is what makes this arm different
    from Arm 12 below, where the two stages split one bound between them.
    """
    subject = await built(
        channels=[answering(result())],
        gate=SlowGate(FakeAuditTrail(), _EXPIRING_BOUND.total_seconds() * 20),
    )
    call = await authorised_search(subject.trail, proposal=await request(subject))

    outcome = await subject.searcher.search(call, timeout=_EXPIRING_BOUND)

    assert outcome.refusal is SearchRefusal.DEADLINE_EXPIRED
    assert await subject.trail.export_invocations() == [], "no claim, so no completion"
    assert subject.keyring.reads == [], "and no credential was read"
    assert subject.transport.attempts == (), "and no channel was opened"


async def test_the_admission_and_the_call_share_one_window(anyio_backend: object) -> None:
    """ADR-0241 §12's **Arm 12**: one window and not two.

    ADR-0194 §3 names this failure in terms — "an implementation handing the admission
    its own fresh window and the callable another passes every never-answering-gate
    fixture and then returns successfully at nearly twice the deadline the caller
    set". Neither Arm 1 nor Arm 2b sees it, because each stalls one stage past the
    whole bound; this one splits the bound between the two stages so that only a
    shared window expires.

    The gate answers at three fifths of the bound and the transport would answer three
    fifths later, so a searcher with one window expires and a searcher with two
    succeeds at nearly twice the figure.
    """
    del anyio_backend
    share = _EXPIRING_BOUND.total_seconds() * 0.6
    subject = await built(
        transport=StallingTransport(share, answering(result())),
        gate=SlowGate(FakeAuditTrail(), share),
    )
    call = await authorised_search(subject.trail, proposal=await request(subject))

    started = asyncio.get_running_loop().time()
    outcome = await subject.searcher.search(call, timeout=_EXPIRING_BOUND)
    elapsed = asyncio.get_running_loop().time() - started

    assert outcome.refusal is SearchRefusal.DEADLINE_EXPIRED, (
        "the admission and the callable share one budget, so the second stage is "
        "handed what is left of the first's window and not a fresh one"
    )
    assert outcome.records == ()
    assert elapsed < (_EXPIRING_BOUND * 2).total_seconds(), (
        "and it expired at the single shared deadline rather than at the sum of two"
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(
            TimeoutError("the library gave up on its own account"),
            SearchRefusal.TRANSPORT_FAILED,
            id="an-upstream-TimeoutError-is-the-transports-failure",
        ),
    ],
)
async def test_an_upstream_failure_inside_the_bound_is_not_this_seams_expiry(
    error: BaseException, expected: SearchRefusal
) -> None:
    """ADR-0241 §12's **Arm 11**, first half, and §7's classification rule.

    "Classification keys on whether *this* deadline expired, and never on catching an
    exception type." The bound is long and nothing about it fired; what raised is the
    transport, for its own reasons. An implementation that kept a broad
    ``except TimeoutError`` and merely renamed its refusal member passes every other
    arm here while reporting a deadline that never expired.
    """
    subject = await built(transport=RaisingTransport(error))
    call = await authorised_search(subject.trail, proposal=await request(subject))

    outcome = await subject.searcher.search(call, timeout=A_BOUND)

    assert outcome.refusal is expected
    assert outcome.refusal is not SearchRefusal.DEADLINE_EXPIRED


async def test_a_cancellation_nobody_asked_for_is_a_fault_and_not_a_teardown() -> None:
    """ADR-0241 §12's **Arm 11**, second half, and §7's second misclassification.

    A ``CancelledError`` raised where no cancellation was requested is a fault the
    searcher raised: ADR-0031 §2's case, which §7 says must reach ADR-0226 §5's
    degradation and §8's ``SEARCH_FAILED`` — "**never** a teardown that ends the turn,
    and never an outcome". So what leaves is an ``AssistantError``, which is what the
    servicing site degrades on, and **not** a ``CancelledError`` the executor would
    honour by tearing the turn down.

    The count is the discriminator and not the class: nothing cancelled this task, so
    ``Task.cancelling()`` never moved.
    """
    subject = await built(transport=RaisingTransport(asyncio.CancelledError()))
    call = await authorised_search(subject.trail, proposal=await request(subject))

    with pytest.raises(ToolError, match="cancellation with nothing cancelled"):
        await subject.searcher.search(call, timeout=A_BOUND)


@pytest.mark.parametrize(
    "arrangement",
    [
        pytest.param(
            {"refusal": TransportError("this file connects to nothing")},
            id="a-destination-that-refuses-the-connection",
        ),
        pytest.param(
            {"channels": [far_end(b"HTTP/1.1 200 OK\r\nContent-Length: 40\r\n\r\ntruncated")]},
            id="a-channel-closed-mid-response",
        ),
    ],
)
async def test_transport_faileds_other_conditions_are_untouched(
    arrangement: dict[str, Any],
) -> None:
    """ADR-0241 §12's **Arm 9**: §4 moved one condition and changed nothing else.

    A refused connection and a channel closed mid-response each still return
    ``TRANSPORT_FAILED`` and each still complete exactly as they do today — which is
    what shows the split took the expiry out of that member and left its remaining
    conditions, including the ones §13 records as an open question, exactly where they
    were.
    """
    outcome, subject = await _searched(**arrangement)

    assert outcome.refusal is SearchRefusal.TRANSPORT_FAILED
    completions = [
        row.invocation
        for row in await subject.trail.export_invocations()
        if row.invocation.completes is not None
    ]
    assert [row.outcome for row in completions] == [ToolOutcome.FAILED]


async def test_the_bound_does_not_reach_the_claim_append() -> None:
    """ADR-0241 §12's **Arm 10**, and the arm asserts the negative.

    ADR-0192 §3 pins both ledger appends "unbounded by this seam" and gives the reason
    a bound there would be a fiction: the audit store this corpus ships absorbs a
    cancellation until its worker physically finishes (ADR-0054), so cancelling the
    append returns nobody sooner. §1 therefore does **not** place its deadline over
    either append — and this is the arm that fails a lane which "helpfully" wraps one
    in it.

    With the claim held for longer than the bound: ``search`` has **not** returned, no
    ``DEADLINE_EXPIRED`` is minted and no channel is opened. Releasing the barrier lets
    the call proceed normally.
    """
    subject = await built(channels=[answering(result())])
    call = await authorised_search(subject.trail, proposal=await request(subject))
    barrier = subject.trail.suspend_next_operation()

    search = asyncio.ensure_future(subject.searcher.search(call, timeout=_EXPIRING_BOUND))
    await barrier.reached()
    await asyncio.sleep(_EXPIRING_BOUND.total_seconds() * 3)

    assert not search.done(), "the claim append is outside the bound, so nothing expired"
    assert subject.transport.attempts == (), "and no channel was opened while it was held"

    barrier.release()
    outcome = await asyncio.wait_for(search, _SLACK.total_seconds())

    assert outcome.refusal is None, "and the call then proceeds normally"
    assert outcome.records


async def test_the_bound_does_not_reach_the_completion_append() -> None:
    """ADR-0241 §12's **Arm 10**, second half: the same, after the callable has run.

    Held on the *completion* rather than the claim, which is the append a lane is most
    likely to wrap because it is the one that runs while the caller is waiting for an
    answer it already has.
    """
    transport = GatedTransport(answering(result()))
    subject = await built(transport=transport)
    call = await authorised_search(subject.trail, proposal=await request(subject))

    exchange = transport.suspend_next()
    search = asyncio.ensure_future(subject.searcher.search(call, timeout=_EXPIRING_BOUND))
    await exchange.reached()
    # The claim has landed and the callable is running, so the next operation this
    # trail sees is the completion — armed here rather than before the search, which
    # would have caught the claim instead.
    completion = subject.trail.suspend_next_operation()
    exchange.release()
    await completion.reached()
    await asyncio.sleep(_EXPIRING_BOUND.total_seconds() * 3)

    assert not search.done(), "the completion append is outside the bound too"

    completion.release()
    outcome = await asyncio.wait_for(search, _SLACK.total_seconds())

    assert outcome.refusal is None
    assert outcome.records


async def test_a_cancellation_after_the_answer_keeps_the_answers_row() -> None:
    """ADR-0241 §12's **Arm 3b**, and §7's second cancellation clause.

    §7's two cancellation clauses differ only in when the cancellation landed, and an
    implementation that read the first as unconditional would rewrite a good row. Here
    the provider returned successfully, the completion append is held on a barrier, and
    the task is then cancelled: the row that lands carries **the outcome the call
    actually reached** and that result's own cost — not ``interrupted_outcome`` and not
    an ``UNKNOWN`` substituted for a figure the result carried — the append is not
    abandoned, exactly one completion is written, and the cancellation leaves
    afterwards.
    """
    transport = GatedTransport(answering(result()))
    subject = await built(transport=transport)
    call = await authorised_search(subject.trail, proposal=await request(subject))

    exchange = transport.suspend_next()
    search = asyncio.ensure_future(subject.searcher.search(call, timeout=A_BOUND))
    await exchange.reached()
    completion = subject.trail.suspend_next_operation()
    exchange.release()
    await completion.reached()

    search.cancel()
    completion.release()

    with pytest.raises(asyncio.CancelledError):
        await search

    rows = [row.invocation for row in await subject.trail.export_invocations()]
    completions = [row for row in rows if row.completes is not None]
    assert len(completions) == 1, "exactly one completion, and the append was not abandoned"
    assert completions[0].outcome is ToolOutcome.SUCCEEDED, (
        "a search that reached its answer was not interrupted in `interrupted_outcome`'s "
        "sense, however the task ends (ADR-0241 §7)"
    )


async def test_a_cancellation_mid_search_completes_the_claim_and_re_raises() -> None:
    """ADR-0241 §12's **Arm 3**, over the production searcher.

    §7 binds ADR-0060 §1 and ADR-0231 §17 entire and adds no clause to either: the
    ``CancelledError`` is re-raised unchanged, no ``SearchOutcome`` is minted and no
    refusal is returned. What §5's completion clause adds is that the claim is
    completed with ``interrupted_outcome`` and an ``UNKNOWN`` cost **before** it
    re-raises — one rule read at two exits rather than two rules.

    And the authorisation stays spent: ADR-0238 §15's Arm 6d binds a cancellation
    exactly as it binds a refused ruling, so a second claim under the same decision is
    refused (ADR-0192 §1).
    """
    transport = GatedTransport(answering(result()))
    subject = await built(transport=transport)
    call = await authorised_search(subject.trail, proposal=await request(subject))

    gate = transport.suspend_next()
    search = asyncio.ensure_future(subject.searcher.search(call, timeout=A_BOUND))
    await gate.reached()
    search.cancel()
    gate.release()

    with pytest.raises(asyncio.CancelledError):
        await search

    rows = [row.invocation for row in await subject.trail.export_invocations()]
    completions = [row for row in rows if row.completes is not None]
    assert [row.outcome for row in completions] == [ToolOutcome.INDETERMINATE]
    assert completions[0].incurred_cost is not None
    assert completions[0].incurred_cost.basis is CostBasis.UNKNOWN

    with pytest.raises(AuthorisationSpentError):
        await subject.searcher.search(call, timeout=A_BOUND)


@pytest.mark.parametrize(
    "bound",
    [
        pytest.param(30, id="not-a-timedelta"),
        pytest.param(None, id="none"),
        pytest.param(timedelta(0), id="zero"),
        pytest.param(timedelta(seconds=-1), id="negative"),
    ],
)
async def test_a_bound_outside_its_domain_reaches_nothing(bound: object) -> None:
    """ADR-0241 §12's **Arm 6**, in the half the shared suite cannot assert.

    §1: a ``timeout`` that is not a ``timedelta``, or is not strictly positive, is
    refused **before** the call is revalidated, before the credential is read, before
    the spend gate is consulted and before any channel is opened — so a refused value
    reaches no store, appends no claim and opens nothing. The suite pins the raise;
    this pins that nothing happened, which is the half that needs the doubles.
    """
    gate = RefusingGate()
    subject = await built(channels=[answering(result())], gate=gate)
    call = await authorised_search(subject.trail, proposal=await request(subject))

    with pytest.raises(ValueError, match="timeout"):
        await subject.searcher.search(call, timeout=bound)

    assert gate.admissions == 0, "the gate was not consulted"
    assert subject.records.reads == [], "nothing was revalidated against the store"
    assert subject.keyring.reads == [], "no credential was read"
    assert subject.transport.attempts == (), "no channel was opened"
    assert await subject.trail.export_invocations() == [], "no claim was appended"


async def test_the_searcher_holds_no_deadline_of_its_own() -> None:
    """ADR-0241 §3: ``WEB_SEARCH_TIMEOUT`` and the constructor override are both gone.

    "The bound comes from one place — the value the caller passes — and a searcher
    holding a second one would be a searcher able to disagree with its caller about
    what window it is running in." Asserted over the module and the signature rather
    than over a behaviour, because what the clause forbids is a *second source*, and a
    second source that happened to agree would pass every behavioural arm here.
    """
    assert not hasattr(web_search, "WEB_SEARCH_TIMEOUT")
    assert "WEB_SEARCH_TIMEOUT" not in web_search.__all__
    assert "timeout" not in inspect.signature(WebSearchEgress.__init__).parameters
