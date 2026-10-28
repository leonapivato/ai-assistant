"""ADR-0339: understanding drops the keys its reply shape does not name before it parses.

The stage alone, over a scripted model and hand-built windows. A key the reply shape does
not name is dropped at every depth before the parse — the top level and each element of
``unclear`` — and a reply refused only for such keys costs no repair (§2). No key exempts
a reply from the drop, ``answers`` included (ADR-0353 §9:14, superseding ADR-0339 §2:2).
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
    ProposedActivationUnderstanding,
    UnclearPoint,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    SuppliedWindow,
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

_MEANING: Final = {"understanding": "The user says yes."}
_POINT: Final = {"gap": "Which dates.", "readings": ["This weekend.", "Next month."]}
_MEANING_M: Final = {"understanding": "m"}


def _reply(**fields: Any) -> dict[str, Any]:
    return _MEANING | fields


def _text(value: object) -> str:
    return json.dumps(value)


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
    """The reply as the stage would parse it with no drop."""
    try:
        return ProposedActivationUnderstanding.model_validate_json(text)
    except ValidationError, ValueError:
        return None


# --- the drop (§2) -----------------------------------------------------------------------


async def test_a_reply_in_the_retired_shape_parses_with_its_retired_keys_dropped() -> None:
    """#3246, ADR-0353 §9:1: a ground, a reference and the rest are keys the shape no
    longer names, dropped on the first completion with no repair."""
    model = FakeModelProvider.scripted(
        _text(_reply(meaning_ground="stated", references=[{"phrase": "yes"}], unresolved=[]))
    )

    with capture_logs() as logs:
        understood = await _understand(model)

    assert len(model.calls) == 1
    assert understood.meaning == "The user says yes."
    assert understood.grounding_dropped == 0
    assert [one["stray"] for one in _counted(logs)] == [3]


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
            _reply(unclear=[_POINT | {"why": "x", "how": "y"}]),
            ProposedActivationUnderstanding.model_validate(
                _MEANING | {"unclear": [UnclearPoint.model_validate(_POINT)]}
            ),
            2,
            id="an-unclear-point",
        ),
        pytest.param(
            _reply(
                x=1,
                unclear=[_POINT | {"y": 2}, _POINT, _POINT | {"z": 3}],
                answers=[{"question": "Q1", "parts": [2]}],
            ),
            ProposedActivationUnderstanding.model_validate(
                _MEANING | {"unclear": [_POINT, _POINT, _POINT]}
            ),
            4,
            id="across-every-depth-beside-an-answer",
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
        pytest.param(_reply(Understanding="x", CITES=["H1"]), id="case-is-not-folded"),
        pytest.param(_reply(gap="yes", readings=["a"]), id="named-at-another-position"),
        pytest.param(
            _reply(unclear=[_POINT | {"understanding": "u", "cites": ["H1"]}]),
            id="named-by-a-sibling-model",
        ),
    ],
)
def test_a_key_is_named_only_by_the_model_expected_where_it_stands(reply: dict[str, Any]) -> None:
    """§2:3: exact names, no folding, no moving; a key named elsewhere is dropped here."""
    proposal, dropped = _read(_text(reply))

    assert proposal is not None
    assert proposal.understanding == _MEANING["understanding"]
    assert proposal.unclear in ((), (UnclearPoint.model_validate(_POINT),))
    assert dropped == 2


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(_text(_MEANING), id="the-smallest"),
        pytest.param(
            _text(
                _reply(cites=["H1"], unclear=[_POINT], belongs_to=["S1"], meant_for=["R1"])
                | {"relayed": True}
            ),
            id="whole",
        ),
        pytest.param(_text(_reply(understanding="")), id="a-blank-understanding"),
        pytest.param(_text(_reply(unclear=[5])), id="a-non-object-element"),
        pytest.param(_text(_reply(unclear=_POINT)), id="an-object-for-a-sequence"),
        pytest.param(_text(_reply(unclear=[{"gap": "g", "readings": []}])), id="no-reading"),
        pytest.param(_text(["a", "list"]), id="a-list"),
        pytest.param("not json", id="prose"),
        pytest.param('{"understanding": "m",}', id="a-trailing-comma"),
    ],
)
def test_a_reply_holding_no_unnamed_key_parses_exactly_as_before(reply: str) -> None:
    """§2:5: the same reply accepted as the same proposal, the same reply refused."""
    assert _read(reply) == (_strictly(reply), 0)


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(_reply(unclear=[_POINT | {"x": 1}, 5]), id="a-non-object-element"),
        pytest.param(_reply(unclear="a", x=1), id="a-string-for-a-sequence"),
        pytest.param({"understandings": "s", "understanding": None}, id="a-null-required"),
        pytest.param({"understandings": "m"}, id="a-near-miss-required"),
        pytest.param(_reply(unclear=[{"gap": "g", "readings": [], "x": 1}]), id="no-reading"),
    ],
)
def test_a_reply_that_still_fails_once_the_keys_are_dropped_is_refused(
    reply: dict[str, Any],
) -> None:
    """§2:4, §2:6: the drop does nothing where no object stands, and the parse judges."""
    assert _read(_text(reply)) == (None, 0)


async def test_a_near_miss_of_a_required_field_still_fails_and_repairs() -> None:
    """§2:3, §3:2: no mapping onto a field; the repair carries the first output unpruned."""
    first = _text({"meaning": "The user says yes.", "meaning_ground": "stated"})
    model = FakeModelProvider.scripted(first, _text(_MEANING))

    with capture_logs() as logs:
        understood = await _understand(model)

    assert len(model.calls) == 2
    repair = model.calls[1].messages
    assert repair[-2].content == first
    assert _UNPARSEABLE in repair[-1].content
    assert "key" not in repair[-1].content
    assert understood.meaning == "The user says yes."
    assert _counted(logs) == []


async def test_a_dropped_key_is_no_label_defect_and_a_label_defect_still_repairs() -> None:
    """§3:2-§3:3: the later checks run on the parsed output, the repair carries it unpruned."""
    first = _text(_reply(cites=["H9"], stray="x"))
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
    text = _text(_reply(meaning_grounds="stated", unclear=[_POINT | {"x": 1}]))
    sink = FakeDiagnosticSink()

    await _understand(FakeModelProvider.scripted(text), sink=sink)

    (returned,) = sink.of(DiagnosticSource.UNDERSTANDING, DiagnosticKind.RETURNED)
    assert returned.model_dump(mode="json")["body"] == {"reply": text}


@pytest.mark.parametrize("depth", [201, 5000, 100_000])
async def test_a_dropped_value_s_depth_never_refuses_the_reply(depth: int) -> None:
    """§2:4-§2:6: the value is skipped, never decoded, so its nesting costs nothing."""
    deep = "[" * depth + "0" + "]" * depth
    text = f'{{"understanding": "The user says yes.", "stray": {deep}}}'
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
        '{\n  "understanding": "m",\n  "x": ' + value + ',\n  "cites": ["H1"],\n'
        '  "unclear": [{"gap": "p", "readings": ["r"], "y": ' + value + "}]\n}"
    )

    assert _read(text) == (
        ProposedActivationUnderstanding.model_validate(
            {"understanding": "m", "cites": ["H1"], "unclear": [{"gap": "p", "readings": ["r"]}]}
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
    text = '{"understanding": "m", "x": ' + value + "}"

    assert _strictly(text) is None
    assert _read(text) == (ProposedActivationUnderstanding.model_validate(_MEANING_M), 1)


def test_an_escaped_key_is_named_by_what_it_says() -> None:
    """§2:3: ``\\u0075nderstanding`` says ``understanding``, as the parse reads it."""
    text = '{"\\u0075nderstanding": "m", "meaning_ground": "stated"}'

    assert _read(text) == (ProposedActivationUnderstanding.model_validate(_MEANING_M), 1)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param('{"understanding": "m", "x": [1}', id="mismatched"),
        pytest.param('{"understanding": "m", "x": [[1]', id="unclosed"),
        pytest.param('{"understanding": "m", "x": "open}', id="open-quote"),
        pytest.param('{"understanding": "m", "x" 1}', id="no-colon"),
        pytest.param('{"understanding": "m", "x": 1} trailing', id="trailing"),
        pytest.param('{"understanding": "m", "x": 1}}', id="extra-close"),
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
        "unclear": _Sequence(UnclearPoint),
    }


class _Aliased(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    named: str = Field(alias="Named")


class _OptionalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    one: UnclearPoint | None = None


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
            return "".join(rng.choice('ab{}[],:"\\ \né') for _ in range(rng.randint(0, 8)))
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
    """``value`` with stray keys at the top level and in each unclear point."""
    added = 0

    def strayed(one: dict[str, Any]) -> dict[str, Any]:
        nonlocal added
        items = list(one.items())
        for _ in range(rng.randint(0, 2)):
            items.insert(rng.randint(0, len(items)), (f"stray_{added}", _random_value(rng)))
            added += 1
        return dict(items)

    top = strayed(value)
    top["unclear"] = [strayed(element) for element in top["unclear"]]
    return top, added


def test_a_reply_parses_as_the_same_reply_with_its_unnamed_keys_removed() -> None:
    """§2:5: over generated replies, pretty-printed or not, the drop is exactly removal."""
    rng = random.Random(3246)  # noqa: S311 — a seeded generator of test cases, not a secret
    base: dict[str, Any] = {
        "understanding": "m",
        "cites": ["H1"],
        "unclear": [_POINT, {"gap": "q", "readings": ["r"]}],
        "belongs_to": ["S1"],
        "meant_for": [],
        "relayed": False,
    }
    for case in range(300):
        reply, added = _with_strays(rng, base)
        text = json.dumps(reply, indent=2 if case % 2 else None, ensure_ascii=case % 3 == 0)
        assert _read(text) == (_strictly(json.dumps(base)), added), text


# --- no key exempts a reply (ADR-0353 §9:14) ----------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(_reply(answers=[{"question": "Q1", "part": [2]}]), id="a-pointer"),
        pytest.param(
            _reply(answers=[{"question": "Q1", "parts": [2]}], unresolved_matters=[]),
            id="a-guard-beside-an-answer",
        ),
        pytest.param(
            '{"understanding": "The user says yes.",'
            ' "answers": [{"question": "Q1"}], "answers": []}',
            id="answers-repeated",
        ),
        pytest.param(_reply(answers={}), id="an-object-for-answers"),
        pytest.param(_reply(answers=None), id="null-answers"),
    ],
)
async def test_answers_in_any_form_is_dropped_and_costs_no_repair(reply: object) -> None:
    """§9:14: ``answers`` is a key the shape does not name, so no value of it makes the
    reply strict; the reply parses on the first completion, recording no pointer."""
    text = reply if isinstance(reply, str) else _text(reply)
    model = FakeModelProvider.scripted(text)

    with capture_logs() as logs:
        understood = await _understand(model)

    proposal, dropped = _read(text)
    assert proposal == ProposedActivationUnderstanding.model_validate(_MEANING)
    assert dropped >= 1
    assert len(model.calls) == 1
    assert "answers" not in understood.model_dump()
    assert [one["stray"] for one in _counted(logs)] == [dropped]


def test_answers_inside_an_unclear_point_is_dropped_too() -> None:
    """§9:14: in each element of ``unclear`` as at the top level."""
    reply = _text(_reply(unclear=[_POINT | {"answers": [{"question": "Q1"}]}]))

    assert _read(reply) == (
        ProposedActivationUnderstanding.model_validate(_MEANING | {"unclear": [_POINT]}),
        1,
    )


# --- the count (§4) -----------------------------------------------------------------------


async def test_the_count_is_logged_with_stage_and_reason_and_survives_redaction() -> None:
    """§4:1-§4:2: code-owned fields alone, and the hub's redaction leaves the number shown.

    A field named for ``key`` would be masked (``core/logging.py``), so the count is
    ``stray``; nothing of the reply, its keys' names included, reaches the line.
    """
    text = _text(_reply(LEAK_TOP="LEAK-VALUE", unclear=[_POINT | {"LEAK_NESTED": {"LEAK": 1}}]))

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
