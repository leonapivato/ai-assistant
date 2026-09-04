"""The canonical ``QueryComposer`` fake passes the shared conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeQueryComposer``
as a stand-in for a composer: it is held to the same contract the model-backed one
is (ADR-0231 §17). Beyond the binding, what is here is the scripting behaviour the
suite does not reach — the half ADR-0231 §18's arms 4 and 4a will drive at the
servicer, and therefore the half that has to be right before they are written.

**Here and not under ``tests/testing/``**, for the reason ``test_fake_planning.py``
is here: the suite this binds lives beside the production composer in this package,
and pytest's ``prepend`` import mode puts a test module's *own* directory on
``sys.path`` and no other's. A binding one directory over would import
``query_composer_contract`` only in a whole-suite run, and would fail to collect on
its own — leaving the fake's conformance unavailable to exactly the narrowed runs
that most want it. ``tests/conftest.py`` pins ``tests/core`` for the suites with no
owning subsystem package; this one has one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from query_composer_contract import (
    UTTERANCE,
    GatedComposition,
    QueryComposerContract,
    ScriptedComposition,
    ScriptedRefusal,
)

from ai_assistant.core.types import QueryRefusal
from ai_assistant.testing import DEFAULT_COMPOSED_QUERY, DEFAULT_QUERY_MAX_CHARS, FakeQueryComposer

if TYPE_CHECKING:
    from typing import Any

#: A small bound, so the boundary cases compose a handful of characters rather than
#: a paragraph. Nothing in the contract is a function of the figure.
_BOUND: Final = 32


class TestFakeQueryComposerContract(QueryComposerContract):
    """``FakeQueryComposer`` against the shared suite (ADR-0231 §17)."""

    @pytest.fixture
    def composer(self) -> FakeQueryComposer:
        return FakeQueryComposer(max_chars=_BOUND)

    def bound(self) -> int:
        return _BOUND

    def composing(self, query: str) -> ScriptedComposition:
        return ScriptedComposition(
            composer=FakeQueryComposer({UTTERANCE: query}, max_chars=_BOUND),
            utterance=UTTERANCE,
        )

    def refusing(self, refusal: QueryRefusal) -> ScriptedRefusal:
        return ScriptedRefusal(
            composer=FakeQueryComposer(refusals={UTTERANCE: refusal}, max_chars=_BOUND),
            utterance=UTTERANCE,
        )

    def gated(self) -> GatedComposition:
        fake = FakeQueryComposer(max_chars=_BOUND)
        return GatedComposition(composer=fake, utterance=UTTERANCE, arm=fake.suspend_next)


async def test_an_unscripted_utterance_gets_the_default_composition() -> None:
    """The ordinary case: a consumer that does not care what the query says."""
    composer = FakeQueryComposer()

    outcome = await composer.compose("anything at all")

    assert outcome.query == DEFAULT_COMPOSED_QUERY


async def test_a_scripted_utterance_gets_its_own_composition() -> None:
    """What a consumer needs to assert that *this* query reached a searcher."""
    composer = FakeQueryComposer({"where is porto": "porto portugal"})

    assert (await composer.compose("where is porto")).query == "porto portugal"
    assert (await composer.compose("something else")).query == DEFAULT_COMPOSED_QUERY


async def test_a_scripted_refusal_wins_over_a_scripted_composition() -> None:
    """The more specific instruction, and the branch easiest to make untestable.

    A fake that silently preferred the query would leave a consumer's refusal branch
    unreachable in exactly the case a test author is most likely to write by
    accident — scripting both, and expecting the refusal.
    """
    composer = FakeQueryComposer(
        {UTTERANCE: "porto portugal"},
        refusals={UTTERANCE: QueryRefusal.DECLINED},
    )

    outcome = await composer.compose(UTTERANCE)

    assert outcome.refusal is QueryRefusal.DECLINED
    assert outcome.query is None


async def test_every_utterance_it_was_handed_is_recorded_in_call_order() -> None:
    """ADR-0231 §18's arms 4 and 4a read this back at the servicer.

    Recorded on **entry**, so a composition that refused still shows the composer was
    reached — which is what tells a test that a servicing composed and then declined
    apart from one that never composed at all.
    """
    composer = FakeQueryComposer(refusals={"second": QueryRefusal.UNAVAILABLE})

    await composer.compose("first")
    await composer.compose("second")

    assert composer.utterances == ["first", "second"]


async def test_a_scripted_composition_over_the_bound_is_refused_not_truncated() -> None:
    """The fake enforces its own bound, exactly as a configured composer does (§3)."""
    composer = FakeQueryComposer({UTTERANCE: "q" * (_BOUND + 1)}, max_chars=_BOUND)

    outcome = await composer.compose(UTTERANCE)

    assert outcome.refusal is QueryRefusal.TOO_LONG
    assert outcome.query is None


def test_the_default_bound_is_the_one_the_decision_names() -> None:
    """ADR-0231 §5's named default, so a fake with no bound is a default deployment."""
    assert DEFAULT_QUERY_MAX_CHARS == 256


@pytest.mark.parametrize("max_chars", [True, 1.5, "32", None])
def test_a_bound_that_is_not_an_integer_is_refused_at_construction(max_chars: Any) -> None:
    """The type is part of the domain, and the fake must not be the looser of the two.

    ``bool`` is a subclass of ``int`` and ``True`` *means* a bound of one, a reading
    ADR-0231 §5 never gave it; a ``float`` compares against a length perfectly happily
    while meaning a bound nobody configured.
    """
    with pytest.raises(TypeError):
        FakeQueryComposer(max_chars=max_chars)


@pytest.mark.parametrize("max_chars", [0, -1])
def test_a_bound_below_one_is_refused_at_construction(max_chars: int) -> None:
    """A bound that refuses every composition while appearing configured (§5)."""
    with pytest.raises(ValueError, match="at least 1"):
        FakeQueryComposer(max_chars=max_chars)


@pytest.mark.parametrize("unwritable", ["\ud800", "porto \udfff"])
def test_a_scripted_composition_with_no_utf_8_encoding_is_refused(unwritable: str) -> None:
    """The other half of what ``QueryOutcome.query`` accepts, refused at construction.

    A lone surrogate is a ``str`` Python holds happily and cannot encode, so a fake
    scripted with one would raise out of ``compose`` at an arbitrary later call —
    which is the one thing ADR-0231 §3 says never leaves that member.
    """
    with pytest.raises(ValueError, match="UTF-8"):
        FakeQueryComposer({UTTERANCE: unwritable})

    with pytest.raises(ValueError, match="UTF-8"):
        FakeQueryComposer(query=unwritable)


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_a_blank_scripted_composition_is_refused_at_construction(blank: str) -> None:
    """``QueryOutcome`` refuses a blank query, so a fake scripted with one is broken.

    Refused here rather than at the call it would have failed on: a canonical fake
    configurable into a state it cannot answer from is one that fails its own
    conformance suite at an arbitrary later moment, naming the wrong thing.
    """
    with pytest.raises(ValueError, match="non-blank"):
        FakeQueryComposer({UTTERANCE: blank})

    with pytest.raises(ValueError, match="non-blank"):
        FakeQueryComposer(query=blank)


def test_a_second_armed_suspension_is_refused() -> None:
    """Two would make the second a silent no-op (``SuspendableResource``)."""
    composer = FakeQueryComposer()
    composer.suspend_next()

    with pytest.raises(RuntimeError):
        composer.suspend_next()
