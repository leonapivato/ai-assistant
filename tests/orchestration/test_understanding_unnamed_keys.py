"""ADR-0339: understanding drops the keys its reply shape does not name before it parses.

The stage alone, over a scripted model and hand-built windows. A key the reply shape does
not name is dropped at every depth before the parse, and a reply refused only for such keys
costs no repair (§2). A reply that proposes an answer is parsed strictly, as before, so a
misspelt ``parts`` or ``unresolved`` beside an answer is still refused and repaired (§2:2).
The types, the repair and the diagnostic record are untouched (§3), and the number of keys
dropped is logged, never which (§4).
"""

from __future__ import annotations

import json
import math
import random
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from structlog.testing import capture_logs

from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.logging import redact_sensitive
from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    DiagnosticKind,
    DiagnosticSource,
    MessageAuthor,
    ProposedActivationUnderstanding,
    ProposedAnswer,
    ProposedReference,
    ProposedRelationship,
    TranscriptMessage,
    UnderstandingGround,
    UnresolvedMatter,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    AskedIn,
    SuppliedWindow,
    TranscriptWindow,
    UnderstandingStage,
    _expected_fields,
    _parsed,
    _read,
    _Sequence,
)
from ai_assistant.testing import FakeDiagnosticSink, FakeModelProvider, default_prompt

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.types import ActivationUnderstanding
    from ai_assistant.orchestration.understanding import ChannelWindow

_UNDERSTANDING = default_prompt(UNDERSTANDING_PROMPT)
AT: Final = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
CONVERSATION: Final = ChannelIdentity(channel_type="conversation", instance_id="c-1")
BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
_NO_WINDOW: Final = SuppliedWindow(ChannelContext())
_ACTIVATION: Final = "7c1e2d3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f"

#: The event the count is logged under, and its code-owned reason (§4:1).
_COUNTED: Final = "understanding_stray_keys"
_REASON: Final = "unnamed_keys_dropped"

#: The statement a parse failure's repair carries, as the stage owns it.
_UNPARSEABLE: Final = "not one JSON object of the required shape"

_MEANING: Final = {"meaning": "The user says yes.", "meaning_ground": "stated"}
_MATTER: Final = {"matter": "Which dates.", "why_it_matters": "Availability varies."}
_MEANING_M: Final = {"meaning": "m", "meaning_ground": "stated"}


def _reply(**fields: Any) -> dict[str, Any]:
    return _MEANING | fields


def _text(value: object) -> str:
    return json.dumps(value)


def _message(position: int, text: str, author: MessageAuthor) -> TranscriptMessage:
    user = author is MessageAuthor.USER
    return TranscriptMessage(
        conversation_id="c-1",
        position=position,
        written_at=AT,
        author=author,
        text=text,
        device_id="phone" if user else None,
        message_id=f"m-{position}" if user else None,
    )


#: The assistant (activation a-1, round r-1) asked a question of two parts, rendered Q1.
_TWO_PARTS: Final = TranscriptWindow(
    CONVERSATION,
    (
        _message(1, "Book a table for six.", MessageAuthor.USER),
        _message(
            2,
            "Shall I book it?\n1. book_table people=5\n2. book_table people=6",
            MessageAuthor.ASSISTANT,
        ),
    ),
    input_messages=(),
    links={1: "a-1", 2: "a-1"},
    asked={2: AskedIn(round="r-1", parts=(1, 2))},
)


async def _understand(
    model: FakeModelProvider,
    *,
    window: ChannelWindow = _NO_WINDOW,
    sink: FakeDiagnosticSink | None = None,
) -> ActivationUnderstanding:
    stage = UnderstandingStage(
        model=model, excerpt_chars=2000, prompt=_UNDERSTANDING, diagnostics=sink
    )
    with diagnosed_activation(_ACTIVATION, clock=lambda: AT):
        return await stage.understand(
            "yes",
            channel=CONVERSATION,
            window=window,
            audience=BOUNDED,
            episodes=(),
            version=1,
            now=lambda: AT,
            deadline=math.inf,
        )


def _counted(logs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [one for one in logs if one["event"] == _COUNTED]


def _strictly(text: str) -> ProposedActivationUnderstanding | None:
    """The reply as the stage parsed it before ADR-0339."""
    try:
        return ProposedActivationUnderstanding.model_validate_json(text)
    except ValidationError, ValueError:
        return None


# --- the drop (§2) -----------------------------------------------------------------------


async def test_the_evidence_case_parses_on_the_first_completion() -> None:
    """#3246: a stray ``meaning_grounds`` beside ``meaning_ground`` costs no repair."""
    model = FakeModelProvider.scripted(_text(_reply(meaning_grounds="stated")))

    with capture_logs() as logs:
        understood = await _understand(model)

    assert len(model.calls) == 1
    assert understood.meaning == "The user says yes."
    assert understood.meaning_ground is UnderstandingGround.STATED
    assert understood.grounding_dropped == 0
    assert [one["stray"] for one in _counted(logs)] == [1]


@pytest.mark.parametrize(
    ("reply", "proposal", "dropped"),
    [
        pytest.param(
            _reply(extra={"nested": {"deeper": 1}}),
            ProposedActivationUnderstanding.model_validate(_MEANING),
            1,
            id="top-level-holding-an-object",
        ),
        pytest.param(
            _reply(references=[{"phrase": "yes", "labels": [], "phrases": "yes"}]),
            ProposedActivationUnderstanding.model_validate(
                _MEANING | {"references": [ProposedReference(phrase="yes")]}
            ),
            1,
            id="a-reference",
        ),
        pytest.param(
            _reply(relationships=[{"statement": "s", "ground": "inferred", "grounds": "x"}]),
            ProposedActivationUnderstanding.model_validate(
                _MEANING
                | {
                    "relationships": [
                        ProposedRelationship(statement="s", ground=UnderstandingGround.INFERRED)
                    ]
                }
            ),
            1,
            id="a-relationship",
        ),
        pytest.param(
            _reply(unresolved=[_MATTER | {"why": "x", "how": "y"}]),
            ProposedActivationUnderstanding.model_validate(
                _MEANING | {"unresolved": [UnresolvedMatter.model_validate(_MATTER)]}
            ),
            2,
            id="an-unresolved-matter",
        ),
        pytest.param(
            _reply(
                x=1,
                references=[{"phrase": "a", "y": 2}, {"phrase": "b"}, {"phrase": "c", "z": 3}],
                unresolved=[_MATTER | {"w": 4}],
                answers=[],
            ),
            ProposedActivationUnderstanding.model_validate(
                _MEANING
                | {
                    "references": [{"phrase": "a"}, {"phrase": "b"}, {"phrase": "c"}],
                    "unresolved": [_MATTER],
                }
            ),
            4,
            id="across-every-depth-beside-an-empty-answers",
        ),
    ],
)
async def test_an_unnamed_key_is_dropped_at_every_depth_and_counted(
    reply: dict[str, Any], proposal: ProposedActivationUnderstanding, dropped: int
) -> None:
    """§2:1, §2:6, §4:1: the keys removed, the output parsed, one line counting them all."""
    text = _text(reply)
    model = FakeModelProvider.scripted(text)

    with capture_logs() as logs:
        await _understand(model)

    assert len(model.calls) == 1
    assert _read(text) == (proposal, dropped)
    assert _parsed(text) == proposal
    assert [one["stray"] for one in _counted(logs)] == [dropped]


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(_reply(Meaning="x", MEANING_GROUND="stated"), id="case-is-not-folded"),
        pytest.param(_reply(phrase="yes", ground="stated"), id="named-at-another-position"),
        pytest.param(
            _reply(references=[{"phrase": "yes", "statement": "s", "matter": "m"}]),
            id="named-by-a-sibling-model",
        ),
    ],
)
def test_a_key_is_named_only_by_the_model_expected_where_it_stands(reply: dict[str, Any]) -> None:
    """§2:3: exact names, no folding, no moving; a key named elsewhere is dropped here."""
    proposal, dropped = _read(_text(reply))

    assert proposal is not None
    assert proposal.meaning == _MEANING["meaning"]
    assert proposal.references in ((), (ProposedReference(phrase="yes"),))
    assert dropped == 2


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(_text(_MEANING), id="the-smallest"),
        pytest.param(_text(_reply(references=[{"phrase": "a", "labels": ["H1"]}])), id="whole"),
        pytest.param(_text(_reply(answers=[{"question": "Q1", "parts": [2]}])), id="an-answer"),
        pytest.param(_text(_reply(answers=None)), id="answers-null"),
        pytest.param(_text(_reply(meaning="")), id="a-blank-meaning"),
        pytest.param(_text(_reply(references=[5])), id="a-non-object-element"),
        pytest.param(_text(_reply(references={"phrase": "a"})), id="an-object-for-a-sequence"),
        pytest.param(_text(["a", "list"]), id="a-list"),
        pytest.param("not json", id="prose"),
        pytest.param('{"meaning": "m", "meaning_ground": "stated",}', id="a-trailing-comma"),
    ],
)
def test_a_reply_holding_no_unnamed_key_parses_exactly_as_before(reply: str) -> None:
    """§2:5: the same reply accepted as the same proposal, the same reply refused."""
    assert _read(reply) == (_strictly(reply), 0)


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(_reply(references=[{"phrase": "a", "x": 1}, 5]), id="a-non-object-element"),
        pytest.param(_reply(references="a", x=1), id="a-string-for-a-sequence"),
        pytest.param(_reply(meaning_grounds="stated", meaning_ground=None), id="a-null-required"),
        pytest.param({"meaning_grounds": "stated", "meaning": "m"}, id="a-near-miss-required"),
    ],
)
def test_a_reply_that_still_fails_once_the_keys_are_dropped_is_refused(
    reply: dict[str, Any],
) -> None:
    """§2:4, §2:6: the drop does nothing where no object stands, and the parse judges."""
    assert _read(_text(reply)) == (None, 0)


async def test_a_near_miss_of_a_required_field_still_fails_and_repairs() -> None:
    """§2:3, §3:2: no mapping onto a field; the repair carries the first output unpruned."""
    first = _text({"meaning": "The user says yes.", "meaning_grounds": "stated"})
    model = FakeModelProvider.scripted(first, _text(_MEANING))

    with capture_logs() as logs:
        understood = await _understand(model)

    assert len(model.calls) == 2
    repair = model.calls[1].messages
    assert repair[-2].content == first
    assert _UNPARSEABLE in repair[-1].content
    assert "key" not in repair[-1].content
    assert understood.meaning_ground is UnderstandingGround.STATED
    assert _counted(logs) == []


async def test_a_dropped_key_is_no_grounding_defect_and_a_label_defect_still_repairs() -> None:
    """§3:2-§3:3: the later checks run on the parsed output, the repair carries it unpruned."""
    first = _text(_reply(meaning_ground="supplied", meaning_labels=["H9"], stray="x"))
    model = FakeModelProvider.scripted(first, _text(_MEANING))

    with capture_logs() as logs:
        understood = await _understand(model)

    assert len(model.calls) == 2
    assert model.calls[1].messages[-2].content == first
    assert "H9" in model.calls[1].messages[-1].content
    assert understood.grounding_dropped == 0
    assert [one["stray"] for one in _counted(logs)] == [1]


async def test_the_diagnostic_entry_keeps_the_reply_as_the_model_returned_it() -> None:
    """§3:4, ADR-0314 §4:1: stray keys included."""
    text = _text(_reply(meaning_grounds="stated", references=[{"phrase": "a", "x": 1}]))
    sink = FakeDiagnosticSink()

    await _understand(FakeModelProvider.scripted(text), sink=sink)

    (returned,) = sink.of(DiagnosticSource.UNDERSTANDING, DiagnosticKind.RETURNED)
    assert returned.model_dump(mode="json")["body"] == {"reply": text}


@pytest.mark.parametrize("depth", [201, 5000, 100_000])
async def test_a_dropped_value_s_depth_never_refuses_the_reply(depth: int) -> None:
    """§2:4-§2:6: the value is skipped, never decoded, so its nesting costs nothing."""
    deep = "[" * depth + "0" + "]" * depth
    text = f'{{"meaning": "The user says yes.", "stray": {deep}, "meaning_ground": "stated"}}'
    model = FakeModelProvider.scripted(text)

    with capture_logs() as logs:
        understood = await _understand(model)

    assert len(model.calls) == 1
    assert understood.meaning == "The user says yes."
    assert [one["stray"] for one in _counted(logs)] == [1]


@pytest.mark.parametrize(
    "value",
    [
        pytest.param('"a } ] , \\" { [ quoted"', id="a-string-holding-brackets-and-quotes"),
        pytest.param('{"a": ["}", "]", {"b": "\\"}"}]}', id="nested-strings-holding-brackets"),
        pytest.param("-1.5e+10", id="a-number"),
        pytest.param("null", id="null"),
        pytest.param('"' + "x" * 200_000 + '"', id="a-long-string"),
    ],
)
def test_a_dropped_value_is_delimited_by_its_quotes_and_brackets(value: str) -> None:
    """§2:4: whatever the value holds, the member ends where its own JSON value ends."""
    text = (
        '{\n  "meaning": "m",\n  "x": ' + value + ',\n  "meaning_ground": "stated",\n'
        '  "references": [{"phrase": "p", "y": ' + value + "}]\n}"
    )

    assert _read(text) == (
        ProposedActivationUnderstanding.model_validate(
            {"meaning": "m", "meaning_ground": "stated", "references": [{"phrase": "p"}]}
        ),
        2,
    )


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("[1,,2]", id="a-doubled-comma"),
        pytest.param("NaN", id="a-literal-json-has-not"),
        pytest.param('{"a" 1}', id="an-object-missing-its-colon"),
    ],
)
def test_what_a_dropped_value_holds_is_never_validated(value: str) -> None:
    """§2:4: delimited by its brackets and quotes, never read, so its content is moot.

    The same reply with the key and its value removed parses (§2:5).
    """
    text = '{"meaning": "m", "meaning_ground": "stated", "x": ' + value + "}"

    assert _strictly(text) is None
    assert _read(text) == (ProposedActivationUnderstanding.model_validate(_MEANING_M), 1)


def test_an_escaped_key_is_named_by_what_it_says() -> None:
    """§2:3: ``\\u006deaning`` says ``meaning``, as the parse reads it, so it is kept."""
    text = '{"\\u006deaning": "m", "meaning_ground": "stated", "\\u0078": 1}'

    assert _read(text) == (ProposedActivationUnderstanding.model_validate(_MEANING_M), 1)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param('{"meaning": "m", "meaning_ground": "stated", "x": [1}', id="mismatched"),
        pytest.param('{"meaning": "m", "meaning_ground": "stated", "x": [[1]', id="unclosed"),
        pytest.param('{"meaning": "m", "meaning_ground": "stated", "x": "open}', id="open-quote"),
        pytest.param('{"meaning": "m", "meaning_ground": "stated", "x" 1}', id="no-colon"),
        pytest.param(
            '{"meaning": "m", "meaning_ground": "stated", "x": 1} trailing', id="trailing"
        ),
        pytest.param('{"meaning": "m", "meaning_ground": "stated", "x": 1}}', id="extra-close"),
    ],
)
def test_a_reply_whose_members_cannot_be_delimited_drops_nothing(text: str) -> None:
    """The walk reads only what it can delimit: otherwise the parse judges, as before."""
    assert _read(text) == (_strictly(text), 0) == (None, 0)


def test_the_walk_follows_every_model_the_shape_holds() -> None:
    """§2:1: the shape as ``core/types.py`` defines it, read when the reply is read."""
    expected = _expected_fields(ProposedActivationUnderstanding)

    assert set(expected) == set(ProposedActivationUnderstanding.model_fields)
    assert {name: one for name, one in expected.items() if one is not None} == {
        "references": _Sequence(ProposedReference),
        "relationships": _Sequence(ProposedRelationship),
        "unresolved": _Sequence(UnresolvedMatter),
        "answers": _Sequence(ProposedAnswer),
    }


class _Aliased(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    named: str = Field(alias="Named")


class _OptionalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    one: UnresolvedMatter | None = None


@pytest.mark.parametrize("shape", [_Aliased, _OptionalModel])
def test_a_shape_the_walk_cannot_follow_is_refused_loudly(shape: type[BaseModel]) -> None:
    """A later field in a form the walk does not follow fails, never escapes the drop."""
    with pytest.raises(TypeError):
        _expected_fields(shape)


def _random_value(rng: random.Random, depth: int = 0) -> object:
    """Any JSON value, nested, its strings holding the characters a delimiter reads."""
    kinds = ["string", "number", "literal"] + (["array", "object"] if depth < 4 else [])
    match rng.choice(kinds):
        case "string":
            return "".join(rng.choice('ab{}[],:"\\ \n\u00e9') for _ in range(rng.randint(0, 8)))
        case "number":
            return rng.choice([0, -1, 2.5, 1e300, 10**30])
        case "literal":
            return rng.choice([True, False, None])
        case "array":
            return [_random_value(rng, depth + 1) for _ in range(rng.randint(0, 3))]
        case _:
            return {
                f"k{index}": _random_value(rng, depth + 1) for index in range(rng.randint(0, 3))
            }


def _with_strays(rng: random.Random, value: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """``value`` with stray keys at the top level and in each sequence's elements."""
    added = 0

    def strayed(one: dict[str, Any]) -> dict[str, Any]:
        nonlocal added
        items = list(one.items())
        for _ in range(rng.randint(0, 2)):
            items.insert(rng.randint(0, len(items)), (f"stray_{added}", _random_value(rng)))
            added += 1
        return dict(items)

    top = strayed(value)
    for name in ("references", "relationships", "unresolved"):
        if name in top:
            top[name] = [strayed(element) for element in top[name]]
    return top, added


def test_a_reply_parses_as_the_same_reply_with_its_unnamed_keys_removed() -> None:
    """§2:5: over generated replies, pretty-printed or not, the drop is exactly removal."""
    rng = random.Random(3246)  # noqa: S311 — a seeded generator of test cases, not a secret
    base: dict[str, Any] = {
        "meaning": "m",
        "meaning_ground": "supplied",
        "meaning_labels": ["H1"],
        "references": [{"phrase": "p", "labels": ["H1"]}, {"phrase": "q"}],
        "relationships": [{"statement": "s", "ground": "inferred"}],
        "unresolved": [_MATTER],
        "answers": [],
    }
    for case in range(300):
        reply, added = _with_strays(rng, base)
        text = json.dumps(reply, indent=2 if case % 2 else None, ensure_ascii=case % 3 == 0)
        assert _read(text) == (_strictly(json.dumps(base)), added), text


# --- a reply proposing an answer (§2:2) ---------------------------------------------------


@pytest.mark.parametrize(
    "first",
    [
        pytest.param(
            _reply(answers=[{"question": "Q1", "part": [2]}]),
            id="part-for-parts",
        ),
        pytest.param(
            _reply(answers=[{"question": "Q1", "parts": [2]}], unresolved_matters=[_MATTER]),
            id="unresolved-matters-beside-an-answer",
        ),
    ],
)
async def test_a_partial_yes_with_a_misspelt_guard_is_still_refused_and_repaired(
    first: dict[str, Any],
) -> None:
    """§2:2, §5: no dropped key reads as a yes to every part, or a yes no matter guards.

    The suite's reader, which is the stage's, refuses the same reply, as it did before.
    """
    text = _text(first)
    model = FakeModelProvider.scripted(
        text, _text(_reply(answers=[{"question": "Q1", "parts": [2]}]))
    )

    with capture_logs() as logs:
        understood = await _understand(model, window=_TWO_PARTS)

    assert _read(text) == (_strictly(text), 0) == (None, 0)
    assert len(model.calls) == 2
    assert model.calls[1].messages[-2].content == text
    assert _UNPARSEABLE in model.calls[1].messages[-1].content
    (answer,) = understood.answers
    assert answer.parts == (2,)
    assert _counted(logs) == []


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(
            '{"meaning": "m", "meaning_ground": "stated", "x": 1,'
            ' "answers": [{"question": "Q1"}], "answers": []}',
            id="an-earlier-answers-proposes-one",
        ),
        pytest.param(
            '{"meaning": "m", "meaning_ground": "stated", "x": 1,'
            ' "answers": [], "answers": [{"question": "Q1"}]}',
            id="a-later-answers-proposes-one",
        ),
        pytest.param(_text(_reply(answers={}, x=1)), id="an-object-for-answers"),
        pytest.param(_text(_reply(answers=None, x=1)), id="null-answers"),
        pytest.param(_text(_reply(answers=[{}], x=1)), id="an-empty-answer"),
    ],
)
def test_any_answers_value_but_an_empty_array_leaves_the_reply_strict(reply: str) -> None:
    """§2:2: every value the top level holds under ``answers``, a repeated key's included."""
    assert _read(reply) == (_strictly(reply), 0) == (None, 0)


def test_empty_answers_repeated_still_take_the_drop() -> None:
    """§2:2: every value is an empty array, so the reply proposes no answer."""
    reply = '{"meaning": "m", "meaning_ground": "stated", "x": 1, "answers": [], "answers": []}'
    proposal, dropped = _read(reply)

    assert proposal is not None
    assert proposal.answers == ()
    assert dropped == 1


def test_answers_below_the_top_level_does_not_make_the_reply_strict() -> None:
    """§2:2 reads the top level: an ``answers`` inside a reference is a key it drops."""
    reply = _text(_reply(references=[{"phrase": "a", "answers": [{"question": "Q1"}]}]))

    assert _read(reply) == (
        ProposedActivationUnderstanding.model_validate(
            _MEANING | {"references": [{"phrase": "a"}]}
        ),
        1,
    )


async def test_the_drop_is_decided_separately_for_the_repair() -> None:
    """§2:2: a strict first output repaired by one the drop applies to."""
    first = _text(_reply(answers=[{"question": "Q1", "part": [2]}]))
    second = _text(_reply(answers=[], answer=[{"question": "Q1", "parts": [2]}]))
    model = FakeModelProvider.scripted(first, second)

    with capture_logs() as logs:
        understood = await _understand(model, window=_TWO_PARTS)

    assert len(model.calls) == 2
    assert understood.answers == ()
    assert [one["stray"] for one in _counted(logs)] == [1]


# --- the count (§4) -----------------------------------------------------------------------


async def test_the_count_is_logged_with_stage_and_reason_and_survives_redaction() -> None:
    """§4:1-§4:2: code-owned fields alone, and the hub's redaction leaves the number shown.

    A field named for ``key`` would be masked (``core/logging.py``), so the count is
    ``stray``; nothing of the reply, its keys' names included, reaches the line.
    """
    text = _text(
        _reply(LEAK_TOP="LEAK-VALUE", references=[{"phrase": "a", "LEAK_NESTED": {"LEAK": 1}}])
    )

    with capture_logs() as logs:
        await _understand(FakeModelProvider.scripted(text))

    (line,) = _counted(logs)
    assert line == {
        "event": _COUNTED,
        "log_level": "info",
        "stage": "understanding",
        "reason": _REASON,
        "stray": 2,
    }
    assert redact_sensitive(None, "info", dict(line))["stray"] == 2
    assert "LEAK" not in repr(logs)


async def test_an_output_with_nothing_dropped_logs_no_count() -> None:
    """§4:1: no line where the drop removed nothing."""
    with capture_logs() as logs:
        await _understand(FakeModelProvider.scripted(_text(_MEANING)))

    assert _counted(logs) == []
