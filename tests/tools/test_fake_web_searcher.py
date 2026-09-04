"""The canonical ``WebSearcher`` fake passes the shared conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeWebSearcher`` as
a stand-in for a searcher: it is held to the same contract the concrete one is
(ADR-0231 §17). Beyond the binding, what is here is the scripting behaviour the suite
does not reach — the half ADR-0231 §18's arms 3, 4a and 7 will drive at the servicer,
and therefore the half that has to be right before they are written.

**Here and not under ``tests/testing/``**, for the reason
``tests/planning/test_fake_query_composer.py`` gives: the suite this binds lives
beside the production searcher in this package, and pytest's ``prepend`` import mode
puts a test module's *own* directory on ``sys.path`` and no other's. A binding one
directory over would import ``web_searcher_contract`` only in a whole-suite run, and
would fail to collect on its own — leaving the fake's conformance unavailable to
exactly the narrowed runs that most want it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest
from web_searcher_contract import (
    QUERY,
    ConnectedAccount,
    GatedSearch,
    ScriptedRefusal,
    ScriptedSearch,
    WebSearcherContract,
)

from ai_assistant.core.types import (
    ActionRequest,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    SearchRefusal,
    ToolCall,
)
from ai_assistant.testing import (
    DEFAULT_MAX_RESULT_CHARS,
    DEFAULT_MAX_RESULTS,
    DEFAULT_SEARCH_CONTENT,
    DEFAULT_SEARCH_ORIGIN,
    DEFAULT_SEARCH_SOURCE_NAME,
    FAKE_WEB_SEARCH,
    FakeWebSearcher,
)
from ai_assistant.tools.egress_declaration import DESTINATION_KEYWORD, TIER_KEYWORD

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import FrozenJson

#: When the one decision every call here carries was taken. Fixed, so nothing in this
#: file reads a clock.
_DECIDED_AT: Final = datetime(2026, 9, 4, 11, 30, tzinfo=UTC)

#: A small content bound, so the boundary cases script a handful of characters rather
#: than a paragraph. Nothing in the contract is a function of the figure.
_CONTENT_BOUND: Final = 64


def _authorised(searcher: FakeWebSearcher, query: str = QUERY) -> ToolCall:
    """One authorised call for ``searcher``, as a servicer would have built it.

    Args:
        searcher: The subject the call is for. Its declaration is the fake's own, and
            it is carried by value exactly as ADR-0231 §6 has the servicer carry it.
        query: The query the call proposes.

    Returns:
        The call, which is unconstructable unless the decision authorises it
        (ADR-0231 §17).

    Raises:
        AssertionError: If the searcher has no connected account, and so proposed no
            request for a decision to be taken over.
    """
    parameters: dict[str, FrozenJson] = {"origin": DEFAULT_SEARCH_ORIGIN, "query": query}
    assert searcher.name  # the subject is usable; a blank name is refused at build
    request = ActionRequest(tool=FAKE_WEB_SEARCH, parameters=parameters)
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="the user granted this recipient"),
        id="d-search-1",
        decided_at=_DECIDED_AT,
    )
    return ToolCall(request=request, decision=decision)


class TestFakeWebSearcherContract(WebSearcherContract):
    """``FakeWebSearcher`` against the shared suite (ADR-0231 §17)."""

    @pytest.fixture
    def searcher(self) -> FakeWebSearcher:
        return FakeWebSearcher(max_result_chars=_CONTENT_BOUND)

    def results_bound(self) -> int:
        return DEFAULT_MAX_RESULTS

    def content_bound(self) -> int:
        return _CONTENT_BOUND

    async def searching(self, results: int) -> ScriptedSearch:
        # Distinct contents, so an implementation that minted one record per result
        # and one that minted the same record `results` times are told apart by the
        # cases that read them back.
        subject = FakeWebSearcher(
            results=tuple(f"result {index}" for index in range(results)),
            max_result_chars=_CONTENT_BOUND,
        )
        return ScriptedSearch(searcher=subject, call=_authorised(subject))

    async def refusing(self, refusal: SearchRefusal) -> ScriptedRefusal:
        subject = FakeWebSearcher(refusals={QUERY: refusal}, max_result_chars=_CONTENT_BOUND)
        return ScriptedRefusal(searcher=subject, call=_authorised(subject))

    async def gated(self) -> GatedSearch:
        subject = FakeWebSearcher(max_result_chars=_CONTENT_BOUND)
        return GatedSearch(searcher=subject, call=_authorised(subject), arm=subject.suspend_next)

    async def connected(self) -> ConnectedAccount:
        return ConnectedAccount(
            searcher=FakeWebSearcher(max_result_chars=_CONTENT_BOUND),
            origin=DEFAULT_SEARCH_ORIGIN,
            declaration=FAKE_WEB_SEARCH,
        )

    async def unconnected(self) -> FakeWebSearcher:
        return FakeWebSearcher(origin=None)


# --------------------------------------------------------------------------- #
# the scripting the suite does not reach
# --------------------------------------------------------------------------- #


async def test_a_scripted_refusal_wins_over_a_scripted_answer() -> None:
    """The more specific instruction, so a refusal branch stays testable.

    A fake that silently preferred the records would make a consumer's refusal
    branch untestable in the one case it is easiest to write by accident: scripting
    both for one query.
    """
    searcher = FakeWebSearcher({QUERY: ("something",)}, refusals={QUERY: SearchRefusal.UNATTESTED})

    outcome = await searcher.search(_authorised(searcher))

    assert outcome.refusal is SearchRefusal.UNATTESTED


async def test_the_query_the_call_carries_selects_the_scripted_answer() -> None:
    """A test scripts by the query it expects the composer to have written."""
    searcher = FakeWebSearcher({"porto": ("a porto result",)})

    scripted = await searcher.search(_authorised(searcher, "porto"))
    default = await searcher.search(_authorised(searcher, "lisbon"))

    assert [record.content for record in scripted.records] == ["a porto result"]
    assert [record.content for record in default.records] == [DEFAULT_SEARCH_CONTENT]


async def test_a_content_over_the_bound_is_dropped_and_its_siblings_are_minted() -> None:
    """ADR-0231 §10's drop, over an answer a test chose.

    Dropped rather than truncated, and the remaining results still minted — which is
    what makes this fake usable to drive a servicer's budget arms without the
    servicer having to know why a count came back short.
    """
    searcher = FakeWebSearcher(results=("short", "x" * 200, "also short"), max_result_chars=64)

    outcome = await searcher.search(_authorised(searcher))

    assert [record.content for record in outcome.records] == ["short", "also short"]


async def test_a_response_every_result_of_which_is_dropped_yields_no_result() -> None:
    """§10: "Where every result is dropped the search yields nothing"."""
    searcher = FakeWebSearcher(results=("x" * 200, "y" * 200), max_result_chars=64)

    outcome = await searcher.search(_authorised(searcher))

    assert outcome.refusal is SearchRefusal.NO_RESULT
    assert outcome.records == ()


async def test_both_members_record_what_they_were_handed_on_entry() -> None:
    """ADR-0231 §18's arms 3 and 4a need the absence of a row to mean something.

    Appended **on entry** rather than after the outcome is decided: an arm asserting
    that a refused composition reached no searcher wants the absence of a row, and one
    asserting that a refusal still *happened* wants the row to be there anyway.
    """
    searcher = FakeWebSearcher(refusals={QUERY: SearchRefusal.NO_RESULT})
    call = _authorised(searcher)

    await searcher.request(QUERY)
    await searcher.search(call)

    assert searcher.requested == [QUERY]
    assert searcher.searched == [call]


async def test_an_unconnected_searcher_records_the_query_it_could_not_propose_for() -> None:
    """``request`` answers ``None`` and still says it was asked (ADR-0231 §17).

    A servicer's ``NOT_CONFIGURED`` disposition is a statement that the searcher was
    reached and had no account, which a fake that recorded nothing could not
    distinguish from one that was never called.
    """
    searcher = FakeWebSearcher(origin=None)

    assert await searcher.request(QUERY) is None
    assert searcher.requested == [QUERY]


# --------------------------------------------------------------------------- #
# what the fake refuses to be configured into
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["", "   ", " search ", "search\n"])
def test_a_name_the_attestation_would_not_carry_unchanged_is_refused_at_build(
    name: str,
) -> None:
    """ADR-0231 §17's stripping clause, refused where it is configured.

    ``Attestation.reported_by`` is ``Identifier``, which strips what it accepts, so a
    searcher named ``" search "`` would mint a record whose ``reported_by`` is
    ``"search"`` and fail the suite's equality — at a mint, far from the constructor
    that caused it.
    """
    with pytest.raises(ValueError, match="name must be"):
        FakeWebSearcher(name=name)


#: Each bound, paired with a way to build a fake carrying a given value for it.
#: Spelled as callables rather than as ``**{name: value}`` so that ``mypy`` reads
#: every construction here against the real signature, which is the whole reason a
#: keyword-only constructor is worth having.
_BOUNDS: Final = (
    ("max_results", lambda value: FakeWebSearcher(max_results=value)),
    ("max_result_chars", lambda value: FakeWebSearcher(max_result_chars=value)),
)


def test_a_result_count_above_the_ceiling_is_refused_at_build() -> None:
    """ADR-0231 §5's ceiling, which is the domain and not merely the default.

    "§10's figure is the ceiling and the setting narrows it, never widens it, so §11's
    precedence holds in every configuration and no deployment can make one search take
    a third of ADR-0226 §6's budget of ten." A canonical fake that admitted four would
    let a consumer's test pass over a supply this system can never assemble.
    """
    with pytest.raises(ValueError, match="max_results must be at most 3"):
        FakeWebSearcher(max_results=DEFAULT_MAX_RESULTS + 1)


async def test_a_fake_at_the_ceiling_mints_exactly_that_many() -> None:
    """The boundary beside the refusal, so the pair fails a comparison the wrong way round."""
    searcher = FakeWebSearcher(
        results=tuple(f"result {index}" for index in range(DEFAULT_MAX_RESULTS + 2)),
        max_results=DEFAULT_MAX_RESULTS,
    )

    outcome = await searcher.search(_authorised(searcher))

    assert [record.content for record in outcome.records] == [
        f"result {index}" for index in range(DEFAULT_MAX_RESULTS)
    ]


@pytest.mark.parametrize(("bound", "build"), _BOUNDS)
def test_a_bound_below_one_is_refused_at_build(
    bound: str, build: Callable[[int], FakeWebSearcher]
) -> None:
    """ADR-0231 §5's domains, at the fake as at the concrete searcher."""
    with pytest.raises(ValueError, match=f"{bound} must be at least 1"):
        build(0)


@pytest.mark.parametrize(("bound", "build"), _BOUNDS)
def test_a_bound_that_is_not_an_exact_int_is_refused_at_build(
    bound: str, build: Callable[[int], FakeWebSearcher]
) -> None:
    """``True`` is an ``int`` by ``isinstance`` and would configure a bound of one."""
    with pytest.raises(TypeError, match=f"{bound} must be an integer"):
        build(True)


def test_a_scripted_refusal_that_is_not_a_member_is_refused_at_build() -> None:
    """``SearchRefusal`` is a ``StrEnum``, so ``"no_result"`` compares equal to one."""
    with pytest.raises(TypeError, match="must be a SearchRefusal member"):
        FakeWebSearcher(refusals={QUERY: "no_result"})  # type: ignore[dict-item]


def test_a_naive_report_instant_is_refused_at_build() -> None:
    """``UtcInstant`` refuses one, and every field this fake puts it in is one.

    A fake that took a naive instant would raise a ``ValidationError`` out of
    ``search`` — the one thing ADR-0231 §17 says never leaves that member — at a call
    far from the constructor that caused it.
    """
    with pytest.raises(ValueError, match="reported_at must be timezone-aware"):
        FakeWebSearcher(reported_at=datetime(2026, 9, 4, 12, 0))  # noqa: DTZ001


def test_a_blank_origin_is_refused_at_build() -> None:
    """``None`` means "no account connected"; ``""`` means a mistake."""
    with pytest.raises(ValueError, match="origin must hold text"):
        FakeWebSearcher(origin="  ")


# --------------------------------------------------------------------------- #
# the fake's declaration does not drift from what the seam reads
# --------------------------------------------------------------------------- #


def test_the_fakes_schema_spells_the_two_keywords_the_seam_reads() -> None:
    """The fake spells ADR-0152 §3's keywords rather than importing them.

    So that the canonical fake reaches into no subsystem — and so that the two
    spellings cannot drift apart without something noticing, which is this case. A
    fake whose origin argument declared ``x-egress-dest`` would satisfy every clause
    in the suite and then bind as "not an egress call" at the one seam that matters.
    """
    properties = FAKE_WEB_SEARCH.parameters_schema["properties"]
    assert isinstance(properties, Mapping)
    origin = properties["origin"]
    assert isinstance(origin, Mapping)

    assert origin[DESTINATION_KEYWORD] == "https"
    assert origin[TIER_KEYWORD] == "operational"


def test_the_fakes_default_bounds_are_the_adrs_named_defaults() -> None:
    """A fake constructed with no bound is bounded the way a default deployment is."""
    assert DEFAULT_MAX_RESULTS == 3
    assert DEFAULT_MAX_RESULT_CHARS == 2048


def test_the_default_source_name_is_one_identifier_accepts_unchanged() -> None:
    """The constant every unnamed fake carries satisfies §17's own clause."""
    assert DEFAULT_SEARCH_SOURCE_NAME.strip() == DEFAULT_SEARCH_SOURCE_NAME
    assert DEFAULT_SEARCH_SOURCE_NAME.strip()
