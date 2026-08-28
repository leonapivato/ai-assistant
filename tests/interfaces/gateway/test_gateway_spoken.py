"""The browser's spoken turn, end to end (ADR-0200 §10).

One route, `POST /ask/spoken`, mapped onto `converse_spoken` beside `/ask` and
`/ask/stream`. What §13's rows ask of this fence is here: the three browser-owned
members and no fourth, the gateway's own deadline, the ordinary size refusal, and a
recording that never travels inside its own refusal (§9).

**Driven through a real socket** for ``test_gateway.py``'s reason: what is under test
is a request a browser makes and a body it renders, and the router, the door and the
admission all sit between the two. The harness is ``test_gateway_streams``' own rather
than a fourth copy of it.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import structlog
from test_gateway_streams import Harness, _harness

from ai_assistant.core.errors import TranscriptionFailedError
from ai_assistant.core.types import (
    ActionPlan,
    CurrentContext,
    Goal,
    MemorySource,
    PlanStep,
    Provenance,
    SpeechFailure,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenDelivery,
    SpokenDeliveryReport,
    SpokenDeliveryState,
    SpokenTurn,
    TimeOfDay,
    TurnOutcome,
    TurnResult,
)
from ai_assistant.interfaces.gateway.http import Request
from ai_assistant.interfaces.gateway.records import RequestClass
from ai_assistant.interfaces.gateway.server import (
    _ASSISTANT_PATHS,
    _STREAMED_SHAPES,
    _TRANSCRIPTION_DETAIL,
    _TURN_BUDGET,
    _outcome_view,
    _Refused,
    _utterance,
)
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import Identifier

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("hermetic_assistant_env")]

#: The instant every scripted value here is stamped with. Fixed rather than read from a
#: clock: nothing here turns on time, and a wall-clock reading would be one more thing a
#: failure could be about.
_INSTANT = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)

#: The path under test, spelled here so a case reads against ADR-0200 §10 rather than
#: against the constant it is checking.
_SPOKEN = "/ask/spoken"

#: A recording a browser could plausibly have made: some octets, base64 as
#: :data:`~ai_assistant.core.types.Base64Audio` fixes it. Its *contents* are never
#: decoded by anything on this path and are not meant to be audio — ADR-0200 §4 is
#: explicit that "no component decodes, re-transcribes or otherwise inspects a
#: rendering", and the same posture is what makes a recording safe to pass around here.
_CLIP = base64.b64encode(b"a recording of the owner asking something").decode("ascii")

#: The same value with its final payload character replaced by one the alphabet does not
#: carry. **Near-valid on purpose** — ADR-0200 §9 names it as "exactly the input an
#: attacker or an unlucky browser produces" — and long enough that finding it in a
#: response or a log record cannot be a coincidence.
_NEAR_VALID = f"{_CLIP[:-2]}!="


def _body(**overrides: Any) -> dict[str, Any]:
    """One well-formed spoken request, with whatever a case wants changed.

    Every member here is the **browser's own**: ADR-0177 §1 requires that "every
    argument expressing what the user asked for is the browser's own — the gateway
    derives none of them, defaults none of them".
    """
    asked: dict[str, Any] = {
        "utterance": {"content": _CLIP, "media_type": "audio/webm;codecs=opus"},
        "plays": ["audio/webm;codecs=opus", "audio/mp4"],
    }
    asked.update(overrides)
    return asked


def _request(path: str, payload: dict[str, Any] | None = None) -> Request:
    """One parsed request, for the classification cases that never reach a socket."""
    return Request(
        method="POST",
        path=path,
        headers=(),
        body=b"" if payload is None else json.dumps(payload).encode(),
    )


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    """A gateway on ADR-0168 §8's own figures, with a session already minted."""
    async with _harness() as one:
        yield one


def _scripted() -> TurnOutcome:
    """One turn with something in every member :func:`_outcome_view` renders.

    The fake's own turn plans nothing, and the case that compares the two entries'
    renderings needs an account with something in it — a rationale and a named step,
    which are what the page lists.
    """
    goal = Goal(
        id="g-1",
        statement="say what is on today",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_INSTANT
        ),
        created_at=_INSTANT,
    )
    return TurnOutcome(
        turn=TurnResult(
            goal=goal,
            context=CurrentContext(
                now=_INSTANT,
                time_of_day=TimeOfDay.AFTERNOON,
                is_weekend=False,
                within_working_hours=True,
            ),
            memories=(),
            plan=ActionPlan(
                id="p-1",
                goal_id=goal.id,
                steps=(PlanStep(id="s-1", intent="read the calendar", capability="read_calendar"),),
                created_at=_INSTANT,
                rationale="reading the calendar is the whole of the plan",
            ),
        ),
        conversation_id="conv-1",
        reply="You have one thing on today.",
    )


class _Budgeted(FakeAssistantEngine):
    """An engine that records the deadline it was handed (ADR-0200 §10)."""

    def __init__(self) -> None:
        """Start with no budget seen."""
        super().__init__()
        self.budgets: list[timedelta] = []

    async def converse_spoken(
        self,
        utterance: SpokenAudio,
        *,
        plays: tuple[SpokenAudioFormat, ...],
        timeout: timedelta,  # noqa: ASYNC109 — the Protocol's own signature
        conversation_id: Identifier | None = None,
        delivery: SpokenDeliveryReport | None = None,
    ) -> SpokenTurn:
        """Record the budget, then answer as the canonical fake answers."""
        self.budgets.append(timeout)
        return await super().converse_spoken(
            utterance,
            plays=plays,
            timeout=timeout,
            conversation_id=conversation_id,
            delivery=delivery,
        )


class _Untranscribable(FakeAssistantEngine):
    """An engine whose transcription failed (ADR-0200 §4)."""

    def __init__(self, failure: SpeechFailure, message: str) -> None:
        """Carry the classification and the message this engine will raise with."""
        super().__init__()
        self._failure = failure
        self._message = message

    async def converse_spoken(
        self,
        utterance: SpokenAudio,
        *,
        plays: tuple[SpokenAudioFormat, ...],
        timeout: timedelta,  # noqa: ASYNC109 — the Protocol's own signature
        conversation_id: Identifier | None = None,
        delivery: SpokenDeliveryReport | None = None,
    ) -> SpokenTurn:
        """Fail the way ADR-0200 §4 fails: classified, and chaining nothing."""
        self.calls.append(("converse_spoken", {"plays": plays}))
        raise TranscriptionFailedError(self._message, failure=self._failure) from None


# --- ADR-0200 §10, §12(a): the third entry ------------------------------------


def test_the_spoken_path_names_the_operation_the_adr_admits() -> None:
    """§10: one route, "mapped onto ``converse_spoken`` in ``_ASSISTANT_PATHS`` beside
    ``/ask`` and ``/ask/stream``".

    Checked against the router rather than against a list in this file, so a path added
    without an operation, or an operation without a path, fails at the join instead of
    being asserted true of a copy.
    """
    assert _ASSISTANT_PATHS[("POST", _SPOKEN)] == "converse_spoken"
    assert _ASSISTANT_PATHS[("POST", "/ask")] == "converse"
    assert _ASSISTANT_PATHS[("POST", "/ask/stream")] == "converse_streaming"


def test_the_spoken_turn_is_answered_whole_and_is_not_a_streamed_shape() -> None:
    """§10: "The recording is uploaded complete, in one request, and the rendering comes
    back on that request's response. No WebSocket, no protocol upgrade, no
    ``EventSource`` and no chunked upload."

    The shape being absent from :data:`_STREAMED_SHAPES` is that decision in the one
    table the gateway reads it from — a shape in it is handed a session handle and
    answered with a body written over time, which is precisely what this route is not.
    """
    assert ("POST", _SPOKEN) not in _STREAMED_SHAPES
    assert ("GET", _SPOKEN) not in _ASSISTANT_PATHS


async def test_a_spoken_request_asks_the_assistant_for_something() -> None:
    """ADR-0177 §2: the four request classes do not become five, and a request §1 admits
    "asks the assistant for something" and is therefore ``assistant-request``."""
    async with _harness() as one:
        assert one.gateway._classify(_request(_SPOKEN, _body())) is RequestClass.ASSISTANT


async def test_a_spoken_request_without_a_session_reaches_nothing() -> None:
    """ADR-0168 §1's biconditional, in the direction that matters most: this plainly
    asks the assistant for something, §3 plainly refuses it to a browser with no
    session, so the engine must not be reached."""
    async with _harness() as one:
        status, body = await one.whole("POST", _SPOKEN, _body(), admitted=False)

        assert status == 401
        assert body["fault"] == "no-live-session"
        assert one.engine.calls == []


async def test_the_answer_is_one_response_on_the_request_the_browser_made(
    harness: Harness,
) -> None:
    """§10 again, driven rather than read off a table: the whole answer arrives with a
    length on the response to the upload, and nothing about it is chunked."""
    reader, headers, status = await harness.send("POST", _SPOKEN, _body())

    assert status == 200
    assert "transfer-encoding" not in headers
    assert headers["content-type"] == ["application/json"]
    assert int(headers["content-length"][0]) > 0
    await reader.readexactly(int(headers["content-length"][0]))


# --- ADR-0200 §10: the three members, and no fourth ---------------------------


async def test_the_three_browser_owned_members_reach_the_engine() -> None:
    """§10: the body carries "the **browser-owned** arguments of §3's signature and no
    others — ``utterance``, ``plays`` and ``conversation_id``".

    ``plays`` reaches the engine **in the order the browser sent it**, because ADR-0200
    §3 makes that order the preference: "the **first** member of ``plays`` that the
    synthesizer's ``formats`` property also names". A gateway that sorted or de-duplicated
    it would be choosing the rendering's format on the browser's behalf.
    """
    engine = FakeAssistantEngine()
    engine.start_conversation("conv-1")
    async with _harness(engine) as one:
        status, _ = await one.whole(
            "POST",
            _SPOKEN,
            _body(plays=["audio/mp4", "audio/webm;codecs=opus"], conversation_id="conv-1"),
        )

        assert status == 200
        assert engine.calls == [
            (
                "converse_spoken",
                {
                    "plays": (SpokenAudioFormat.MP4, SpokenAudioFormat.WEBM_OPUS),
                    "conversation_id": "conv-1",
                    # ADR-0205 §7: the gateway "derives, defaults, composes and
                    # invents no part" of the report, so a body carrying no
                    # `delivery` relays none.
                    "delivery": None,
                },
            )
        ]


async def test_the_recording_reaches_the_engine_byte_for_byte(harness: Harness) -> None:
    """`Base64Audio` is "never normalised: what a caller passed is what crosses the wire"
    (ADR-0200 §9), and an adapter that re-encoded it would be a second spelling of one
    recording."""
    seen: list[SpokenAudio] = []
    original = harness.engine.converse_spoken

    async def recording(utterance: SpokenAudio, **rest: Any) -> SpokenTurn:
        seen.append(utterance)
        return await original(utterance, **rest)

    harness.engine.converse_spoken = recording  # type: ignore[method-assign]
    await harness.whole("POST", _SPOKEN, _body())

    assert [one.content for one in seen] == [_CLIP]
    assert [one.media_type for one in seen] == [SpokenAudioFormat.WEBM_OPUS]


async def test_a_conversation_selector_is_absent_rather_than_defaulted(
    harness: Harness,
) -> None:
    """ADR-0173 §8's meaning unchanged (ADR-0200 §3): omitting the selector asks a
    well-formed question — run in a fresh conversation — and the gateway invents none."""
    status, _ = await harness.whole("POST", _SPOKEN, _body())

    assert status == 200
    assert harness.engine.calls[0][1]["conversation_id"] is None


async def test_plays_absent_is_refused_and_the_engine_is_not_reached(
    harness: Harness,
) -> None:
    """ADR-0200 §3 makes ``plays`` "required with no default", and ADR-0177 §1 has the
    gateway default no argument expressing what the user asked for. What the browser can
    render is a fact only the browser holds."""
    asked = _body()
    del asked["plays"]

    status, body = await harness.whole("POST", _SPOKEN, asked)

    assert status == 400
    assert body == {"fault": "malformed-request"}
    assert harness.engine.calls == []


@pytest.mark.parametrize("value", [["audio/ogg"], "audio/mp4", [7], [{}]])
async def test_plays_that_names_no_member_of_the_vocabulary_is_refused(
    harness: Harness, value: Any
) -> None:
    """A member of no vocabulary is not a format the promoted surface has an answer for,
    so it is refused here rather than relayed — :func:`_members`' rule, unchanged.

    The last two cases are the ones that would otherwise be a ``TypeError`` in this
    process rather than a refusal: JSON carries objects and arrays and neither is
    hashable.
    """
    status, body = await harness.whole("POST", _SPOKEN, _body(plays=value))

    assert status == 400
    assert body == {"fault": "malformed-request"}
    assert harness.engine.calls == []


async def test_an_empty_plays_is_refused_by_the_promoted_surface_and_not_here(
    harness: Harness,
) -> None:
    """ADR-0200 §3 refuses an empty ``plays`` "locally, before any I/O" at the promoted
    surface, so every client gets one answer and a second rule at this layer could only
    differ from it — :func:`_uses`' precedent, one surface over.

    That the refusal came from *there* is what the fault name says: ``rejected`` is
    :func:`_relay_fault`'s name for a call the surface itself would not take.
    """
    status, body = await harness.whole("POST", _SPOKEN, _body(plays=[]))

    assert status == 400
    assert body["fault"] == "rejected"
    assert "plays" in body["detail"]


# --- ADR-0200 §10, §13: the deadline is the gateway's and no browser value reaches it --


async def test_a_body_carrying_a_timeout_is_answered_with_the_gateways_own_budget() -> None:
    """§13's ``§10 (deadline)`` row, first half: "a test posting a body that also carries
    ``timeout``, asserting the engine is called with the gateway's own budget and that
    the body's value reaches neither the call nor the response".

    §10 makes it **never read** rather than refused: "No other assistant route inspects a
    member it does not use", so rejecting one key on one route would be machinery this
    surface does not otherwise have. What ADR-0177 §1's fifth clause forbids is a browser
    value *reaching* the deadline, and a member nothing reads reaches nothing.
    """
    engine = _Budgeted()
    async with _harness(engine) as one:
        status, body = await one.whole(
            "POST", _SPOKEN, _body(timeout=1, timeout_seconds=1, budget=1)
        )

        assert status == 200
        assert engine.budgets == [_TURN_BUDGET]
        assert "timeout" not in json.dumps(body)


async def test_a_timeout_too_large_for_the_request_bound_is_the_ordinary_size_refusal() -> None:
    """§13's ``§10 (deadline)`` row, second half: "a second posting a ``timeout`` large
    enough to breach ``gateway_max_request_bytes``, asserting the ordinary size refusal
    and no call".

    §10's fourth clause is what this pins: "A body is bounded whole by
    ``gateway_max_request_bytes`` before any member of it is read, so a body big enough to
    breach that bound is refused on its **size** — exactly as it would be were the surplus
    bytes in ``utterance``, in a member no clause names, or in whitespace. That refusal is
    about the bytes and says nothing about the member carrying them; no ``timeout`` is read
    on that path either."
    """
    async with _harness(gateway_max_request_bytes=4096) as one:
        status, body = await one.whole("POST", _SPOKEN, _body(timeout="9" * 8192))

        assert status == 413
        assert body == {"fault": "request-too-large", "limit": "gateway_max_request_bytes"}
        assert one.engine.calls == []


async def test_the_same_bound_refuses_an_oversized_recording_on_its_size() -> None:
    """The clause's own "exactly as it would be were the surplus bytes in ``utterance``",
    driven — so the refusal is demonstrably about the bytes rather than about the member.
    """
    oversized = base64.b64encode(b"x" * 8192).decode("ascii")
    async with _harness(gateway_max_request_bytes=4096) as one:
        status, body = await one.whole(
            "POST",
            _SPOKEN,
            _body(utterance={"content": oversized, "media_type": "audio/mp4"}),
        )

        assert status == 413
        assert body["fault"] == "request-too-large"
        assert one.engine.calls == []


async def test_a_member_no_clause_names_is_read_by_nothing_and_refuses_nothing(
    harness: Harness,
) -> None:
    """§10: the gateway "reads those three members from the body by name and reads no
    fourth". A surface that refused an unnamed member would be inspecting one it does not
    use, which no other assistant route does."""
    status, _ = await harness.whole("POST", _SPOKEN, _body(audience="private", speak=False))

    assert status == 200
    assert [name for name, _ in harness.engine.calls] == ["converse_spoken"]
    assert set(harness.engine.calls[0][1]) == {"plays", "conversation_id", "delivery"}


# --- ADR-0200 §9: a refused recording never travels inside the refusal ---------


@pytest.mark.parametrize(
    "utterance",
    [
        {"content": _NEAR_VALID, "media_type": "audio/webm;codecs=opus"},
        {"content": _CLIP, "media_type": "audio/ogg"},
        {"content": _CLIP},
        {"content": _CLIP, "media_type": "audio/mp4", "duration": 3},
    ],
    ids=["near-valid-base64", "unknown-container", "no-container", "a-member-too-many"],
)
async def test_a_recording_the_surface_will_not_take_is_refused_without_the_recording(
    harness: Harness, utterance: dict[str, Any]
) -> None:
    """§9's last clause, at the entry point it names: "the gateway's body parse" is one
    of the places that constructs a ``SpokenAudio`` from a value it did not author, and
    "each such entry point catches the construction failure and raises a project-owned
    refusal ``from None``, carrying no input value and no chained cause".

    The clip is in the request and must be in nothing that comes back: a pydantic
    ``ValidationError`` "carries the rejected **input** whatever the message says", which
    is why a refusal built out of one would carry a recording back out.
    """
    status, body = await harness.whole("POST", _SPOKEN, _body(utterance=utterance))

    assert status == 400
    assert body["fault"] == "recording-unusable"
    rendered = json.dumps(body)
    assert _NEAR_VALID not in rendered
    assert _CLIP not in rendered
    assert harness.engine.calls == []


async def test_a_refused_recording_reaches_neither_log_tier(harness: Harness) -> None:
    """§9's "nor either log tier", and ADR-0200 §8's rule that nothing on this path
    retains audio anywhere."""
    with structlog.testing.capture_logs() as records:
        await harness.whole(
            "POST",
            _SPOKEN,
            _body(utterance={"content": _NEAR_VALID, "media_type": "audio/mp4"}),
        )

    written = json.dumps(records)
    assert _NEAR_VALID not in written
    assert _CLIP[:-2] not in written


def test_the_refusal_the_body_parse_raises_chains_nothing() -> None:
    """§9: "``from None``, carrying no input value and no chained cause".

    Read at the reader rather than through a socket, because a chained cause is not
    something an HTTP response can show: the hazard §9 names is an object left reachable
    as ``__cause__`` and rendered in a traceback.
    """
    with pytest.raises(_Refused) as raised:
        _utterance({"utterance": {"content": _NEAR_VALID, "media_type": "audio/mp4"}})

    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
    assert _NEAR_VALID not in json.dumps(raised.value.response.body.decode())


@pytest.mark.parametrize("utterance", ["a recording", 7, None, [], True])
async def test_an_utterance_that_is_not_a_json_object_is_the_shape_disagreement(
    harness: Harness, utterance: Any
) -> None:
    """A member that is absent or is not an object says the page and the gateway disagree
    about the shape, which is what ``malformed-request`` reports (ADR-0168 §10) — unlike a
    recording the browser encoded and this gateway would not take."""
    status, body = await harness.whole("POST", _SPOKEN, _body(utterance=utterance))

    assert status == 400
    assert body == {"fault": "malformed-request"}
    assert harness.engine.calls == []


# --- ADR-0200 §4: what comes back ---------------------------------------------


async def test_the_answer_carries_the_transcript_the_hub_heard(harness: Harness) -> None:
    """§4's disclosure clause: "``heard`` is disclosed to the caller on every call that
    produced a transcript. A push-to-talk surface that cannot show the user what it heard
    cannot be corrected by them."

    Byte for byte, leading and trailing spaces included — "nothing on this path strips,
    trims, case-folds or otherwise normalises it".
    """
    harness.engine.spoken_transcript = "  what is on today  "

    status, body = await harness.whole("POST", _SPOKEN, _body())

    assert status == 200
    assert body["turn"]["heard"] == "  what is on today  "


async def test_the_turn_inside_a_spoken_answer_is_the_view_the_other_entries_render() -> None:
    """The projection extends :func:`_outcome_view` rather than forking it.

    ADR-0200 §4: the ``outcome`` "is an ordinary ``TurnOutcome``… This call composes a
    turn; it does not create a second kind of one." A second rendering of one would be the
    second place #1337's failure can happen — a member added to the turn's view reaching
    two of the three ask entries and not the third.
    """
    outcome = _scripted()
    engine = FakeAssistantEngine()
    engine.turn_outcome = outcome
    async with _harness(engine) as one:
        _, spoken = await one.whole("POST", _SPOKEN, _body())
        _, typed = await one.whole("POST", "/ask", {"utterance": "what is on today"})

        assert spoken["turn"]["outcome"] == _outcome_view(outcome)
        assert spoken["turn"]["outcome"] == typed["outcome"]


async def test_a_recording_that_carried_no_words_is_not_an_error() -> None:
    """§4: "``heard`` is ``None`` **exactly when** ``outcome`` is ``None``, and that pair
    is the recording that carried no words… It is not an error and no exception is raised
    for it."

    So it comes back ``200`` with four members a page can read, and not as a fault.
    """
    engine = FakeAssistantEngine()
    engine.spoken_transcript = "   "
    async with _harness(engine) as one:
        status, body = await one.whole("POST", _SPOKEN, _body())

        assert status == 200
        assert body["turn"] == {
            "heard": None,
            "outcome": None,
            "spoken": None,
            "spoken_degraded": False,
            # ADR-0205 §1: `episode_id` is `None` "exactly when the call recorded no
            # turn", and a recording that carried no words is the first of the two
            # shapes it names.
            "episode_id": None,
        }


async def test_an_answer_that_could_not_be_spoken_is_a_degradation_and_not_a_fault() -> None:
    """§4: ``spoken_degraded`` is ``True`` "exactly when an answer existed and speaking it
    did not complete", an empty format intersection among the four cases — and the answer
    still travels, because "an answer the caller can read is worth more than a rendering".

    The flag is **carried** rather than inferred from a ``None`` ``spoken``, because §4
    gives ``spoken`` two ``None`` shapes and only one of them is this.
    """
    engine = FakeAssistantEngine()
    engine.spoken_formats = frozenset()
    async with _harness(engine) as one:
        status, body = await one.whole("POST", _SPOKEN, _body())

        assert status == 200
        assert body["turn"]["spoken"] is None
        assert body["turn"]["spoken_degraded"] is True
        assert body["turn"]["outcome"]["reply"]


async def test_a_rendering_crosses_as_the_two_members_adr_0200_gives_it(
    harness: Harness,
) -> None:
    """§9: a ``SpokenAudio`` has "exactly two members", and its base64 is "never
    normalised". Nothing here decodes it — §4 forbids any component inspecting a
    rendering — so what is asserted is byte identity with what the engine returned."""
    rendered: list[SpokenTurn] = []
    original = harness.engine.converse_spoken

    async def keeping(utterance: SpokenAudio, **rest: Any) -> SpokenTurn:
        turn = await original(utterance, **rest)
        rendered.append(turn)
        return turn

    harness.engine.converse_spoken = keeping  # type: ignore[method-assign]
    _, body = await harness.whole("POST", _SPOKEN, _body())

    spoken = rendered[0].spoken
    assert spoken is not None
    assert body["turn"]["spoken"] == {
        "content": spoken.content,
        "media_type": spoken.media_type.value,
    }


async def test_the_engine_renders_in_the_first_format_the_browser_named_that_it_has() -> None:
    """§3: "the **first** member of ``plays`` that the synthesizer's ``formats`` property
    also names" — which the gateway neither computes nor overrides. What this pins at this
    layer is that the browser's preference order survives the trip."""
    engine = FakeAssistantEngine()
    engine.spoken_formats = frozenset({SpokenAudioFormat.MP4})
    async with _harness(engine) as one:
        _, body = await one.whole(
            "POST", _SPOKEN, _body(plays=["audio/webm;codecs=opus", "audio/mp4"])
        )

        assert body["turn"]["spoken"]["media_type"] == "audio/mp4"


# --- ADR-0200 §4, §8: a transcription failure -------------------------------


@pytest.mark.parametrize("failure", list(SpeechFailure))
async def test_a_transcription_failure_carries_its_classification(
    failure: SpeechFailure,
) -> None:
    """§4 puts a ``SpeechFailure`` on the error precisely because the seam's own exception
    does not cross: it is raised ``from None``, so "what a caller can act on travels here
    instead".

    A gateway that flattened it into ``assistant-declined`` would leave the page inferring
    the classification from prose — the inference ADR-0151 §7 forbids one surface over,
    for the same reason.
    """
    engine = _Untranscribable(failure, "transcription failed")
    async with _harness(engine) as one:
        status, body = await one.whole("POST", _SPOKEN, _body())

        assert status == 422
        assert body["fault"] == "transcription-failed"
        assert body["failure"] == failure.value
        assert body["detail"] == _TRANSCRIPTION_DETAIL[failure]


async def test_a_transcription_failure_renders_no_message_this_project_did_not_author() -> None:
    """ADR-0200 §8: "No component on this path writes an exception message it did not
    author… and not into a surfaced error", and that binds "whatever handler renders an
    exception that escapes them" — this one.

    The message here stands in for one an implementation could have interpolated a
    recording into. It reaches the response's rendering nowhere.
    """
    engine = _Untranscribable(SpeechFailure.UNCLASSIFIED, f"could not decode {_CLIP}")
    async with _harness(engine) as one:
        status, body = await one.whole("POST", _SPOKEN, _body())

        assert status == 422
        assert _CLIP not in json.dumps(body)


async def test_a_declined_spoken_turn_is_still_the_hubs_own_condition() -> None:
    """Everything ADR-0200 §4 does not classify is ADR-0168 §9's three conditions,
    unchanged: a hub that received the request and declined it is ``assistant-declined``
    and never a transport failure."""
    engine = FakeAssistantEngine()
    async with _harness(engine) as one:
        status, body = await one.whole("POST", _SPOKEN, _body(conversation_id="conv-nope"))

        assert status == 422
        assert body["fault"] == "assistant-declined"


# --- ADR-0205 §7: the fourth body member --------------------------------------


def _report(**overrides: Any) -> dict[str, Any]:
    """One well-formed report, with whatever a case wants changed."""
    delivery: dict[str, Any] = {
        "state": "interrupted",
        "played_microseconds": "3200000",
        "rendered_microseconds": "9800000",
    }
    delivery.update(overrides)
    return {"episode_id": "conv:conv-1:1", "delivery": delivery}


async def test_the_fourth_browser_owned_member_reaches_the_engine_whole() -> None:
    """§7: the body carries "``utterance``, ``plays``, ``conversation_id`` and
    ``delivery``", and the gateway "derives, defaults, composes and invents no part"
    of the report — so what reaches the engine is the value the page sent, rebuilt
    into the promoted surface's own type and not into a second shape.
    """
    engine = FakeAssistantEngine()
    engine.start_conversation("conv-1")
    async with _harness(engine) as one:
        status, _ = await one.whole(
            "POST", _SPOKEN, _body(conversation_id="conv-1", delivery=_report())
        )

        assert status == 200
        relayed = engine.calls[0][1]["delivery"]
        assert relayed == SpokenDeliveryReport(
            episode_id="conv:conv-1:1",
            delivery=SpokenDelivery(
                state=SpokenDeliveryState.INTERRUPTED,
                played=timedelta(seconds=3, milliseconds=200),
                rendered=timedelta(seconds=9, milliseconds=800),
            ),
        )


async def test_the_gateway_reads_no_fifth_member() -> None:
    """§7 keeps ADR-0200 §10's clause with the count moved by one: "The gateway reads
    those four members by name and reads no fifth." A member no clause names is read
    by nothing and refuses nothing, exactly as before.
    """
    engine = FakeAssistantEngine()
    engine.start_conversation("conv-1")
    async with _harness(engine) as one:
        status, _ = await one.whole(
            "POST",
            _SPOKEN,
            _body(conversation_id="conv-1", delivery=_report(), heard_by="the kitchen"),
        )

        assert status == 200
        assert set(engine.calls[0][1]) == {"plays", "conversation_id", "delivery"}


async def test_the_turn_view_discloses_the_episode_the_next_report_will_name() -> None:
    """§7: the page sends "the one the response carrying that rendering disclosed and
    never one it derived, counted or guessed" — so the id has to cross for there to be
    one to send.
    """
    engine = FakeAssistantEngine()
    async with _harness(engine) as one:
        status, body = await one.whole("POST", _SPOKEN, _body())

        assert status == 200
        assert body["turn"]["episode_id"] == "conv:c-1:1"


@pytest.mark.parametrize(
    "sent",
    [
        pytest.param("not-an-object", id="not-an-object"),
        pytest.param({"episode_id": "conv:conv-1:1"}, id="no-nested-delivery"),
        pytest.param(
            {"episode_id": "conv:conv-1:1", "delivery": "interrupted"}, id="nested-not-an-object"
        ),
        pytest.param({"delivery": {"state": "complete"}}, id="no-episode-id"),
        pytest.param(_report(state="shouted"), id="state-of-no-vocabulary"),
        pytest.param(_report(played_microseconds="3.2"), id="duration-not-an-integer"),
    ],
)
async def test_a_report_the_page_and_the_gateway_disagree_about_is_malformed(
    harness: Harness, sent: Any
) -> None:
    """§7: a member "that is not a JSON object", a missing or non-object nested
    ``delivery``, and a member of no vocabulary at all are the page and the gateway
    disagreeing about the **shape** — which is what :func:`_malformed` reports
    (ADR-0168 §10), exactly as the same shapes are reported on ``plays``.
    """
    status, body = await harness.whole(
        "POST", _SPOKEN, _body(conversation_id="conv-1", delivery=sent)
    )

    assert status == 400
    assert body["fault"] == "malformed-request"
    assert harness.engine.calls == [], "nothing was relayed"


@pytest.mark.parametrize(
    "delivery",
    [
        pytest.param(
            {"state": "complete", "played_microseconds": "1", "rendered_microseconds": "2"},
            id="complete-below",
        ),
        pytest.param(
            {"state": "interrupted", "played_microseconds": "2", "rendered_microseconds": "2"},
            id="interrupted-equal",
        ),
        pytest.param({"state": "complete", "rendered_microseconds": "2"}, id="duration-missing"),
        pytest.param(
            {"state": "unknown", "rendered_microseconds": "2"}, id="unknown-with-a-duration"
        ),
    ],
)
async def test_a_report_outside_the_partition_is_refused_end_to_end(
    harness: Harness, delivery: dict[str, Any]
) -> None:
    """§2's partition, "at validation and again end to end through the route" (§9).

    §7's own condition rather than ``malformed-request``: the shape is one the page
    and the gateway agree on, and what fails is the *measurement*. The refusal is
    "a project-owned refusal carrying no input value and no chained cause", so the
    episode id the page sent — a durable name of one of this owner's turns — is
    nowhere in the body.
    """
    status, body = await harness.whole(
        "POST",
        _SPOKEN,
        _body(
            conversation_id="conv-1", delivery={"episode_id": "conv:secret:9", "delivery": delivery}
        ),
    )

    assert status == 400
    assert body["fault"] == "delivery-unusable"
    assert "conv:secret:9" not in json.dumps(body), "no input value travels in the refusal"
    assert harness.engine.calls == [], "nothing was relayed"


async def test_an_unknown_report_is_refused_by_the_promoted_surface() -> None:
    """§2: "``UNKNOWN`` is a value the hub writes and never one a caller supplies",
    refused "locally, before any I/O" **at the promoted surface**.

    So this gateway decides nothing about it — a second rule here could only differ
    from the one every client already gets — and the answer the browser sees is the
    hub's own refusal, ADR-0168 §9's ``rejected``.
    """
    engine = FakeAssistantEngine()
    engine.start_conversation("conv-1")
    async with _harness(engine) as one:
        status, body = await one.whole(
            "POST",
            _SPOKEN,
            _body(
                conversation_id="conv-1",
                delivery={"episode_id": "conv:conv-1:1", "delivery": {"state": "unknown"}},
            ),
        )

        assert status == 400
        assert body["fault"] == "rejected"


async def test_a_report_beside_no_conversation_is_refused_by_the_promoted_surface() -> None:
    """§1's other local refusal, likewise the surface's rather than this adapter's."""
    engine = FakeAssistantEngine()
    async with _harness(engine) as one:
        status, body = await one.whole("POST", _SPOKEN, _body(delivery=_report()))

        assert status == 400
        assert body["fault"] == "rejected"


async def test_an_explicit_null_delivery_is_the_absence_json_has_a_word_for() -> None:
    """Adversarial review, round 1, ``blocker`` — **waived**, with the grounds here.

    The finding reads ADR-0205 §7's "a present member that is not a JSON object is
    malformed" as reaching ``null``. This surface already decided that question for
    the member sitting immediately beside this one in the same body:
    :func:`~ai_assistant.interfaces.gateway.server._optional_string` treats an
    explicit ``null`` as the absence it is, saying so in its own words — "JSON has a
    way of saying 'no selector' and a client using it is not getting the type wrong"
    — and ``conversation_id`` is read through it on this very route.

    So refusing ``delivery: null`` would make one optional member of one body
    disagree with every other optional member on the surface, including its
    neighbour. §7's clause is about a report the gateway "cannot parse into a
    ``SpokenDeliveryReport``"; a ``null`` asks it to parse none, which is the sentence
    before it — "Where the body carries no ``delivery``, no ``delivery`` reaches
    ``converse_spoken``".

    Pinned rather than argued, so the reading is asserted where a later editor meets
    it.
    """
    engine = FakeAssistantEngine()
    engine.start_conversation("conv-1")
    async with _harness(engine) as one:
        status, _ = await one.whole("POST", _SPOKEN, _body(conversation_id="conv-1", delivery=None))

        assert status == 200
        assert engine.calls[0][1]["delivery"] is None, "no report reached the surface"
