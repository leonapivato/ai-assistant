"""ADR-0354 §8, §12:6: understanding asks its reply as a structured call, and reads the value.

The stage alone, over the canonical structured fake: every completion is one
``complete_structured`` call with the proposal as its shape; a value goes to the label
checks as a parsed output does; ``invalid``, ``empty`` and ``cut`` each cost the one repair,
an empty first reply's repair carrying no assistant turn, and the same failure on the
repair raises :class:`UnderstandingError`; ``refused`` raises
:class:`ModelContentFilterError` with no repair, after its returned entry is written; and
ADR-0339's drop and its log line are gone (§10:1).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from structlog.testing import capture_logs

from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.errors import ModelContentFilterError, ModelError, UnderstandingError
from ai_assistant.core.types import (
    ChannelContext,
    ChannelContextItem,
    ChannelIdentity,
    DiagnosticKind,
    DiagnosticSource,
    ProposedActivationUnderstanding,
    ReplyFailure,
    Role,
)
from ai_assistant.orchestration import understanding
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    SuppliedWindow,
    UnderstandingStage,
)
from ai_assistant.testing import FakeDiagnosticSink, default_prompt
from ai_assistant.testing.structured import FakeStructuredCompleter, ScriptedReply

AT: Final = datetime(2026, 10, 26, 19, 51, tzinfo=UTC)
EVENTS: Final = ChannelIdentity(channel_type="informational_event", instance_id="parks")
WINDOW: Final = SuppliedWindow(ChannelContext(history=(ChannelContextItem(text="Trip plans"),)))


def _proposal(**fields: Any) -> str:
    return json.dumps({"understanding": "A park closed."} | fields)


async def _understand(
    model: FakeStructuredCompleter, *, sink: FakeDiagnosticSink | None = None
) -> Any:
    stage = UnderstandingStage(
        model=model,
        excerpt_chars=2000,
        prompt=default_prompt(UNDERSTANDING_PROMPT),
        diagnostics=sink,
    )
    with diagnosed_activation("a-0", clock=lambda: AT):
        return await stage.understand(
            "Riverside is closed.",
            channel=EVENTS,
            window=WINDOW,
            audience=BoundedAudienceSupply(speakable_attested_sources=frozenset()),
            episodes=None,
            version=1,
            now=lambda: AT,
            deadline=asyncio.get_running_loop().time() + 60,
        )


async def test_every_call_is_one_structured_call_with_the_proposal_as_its_shape() -> None:
    """§8:1: the first completion and the repair alike."""
    model = FakeStructuredCompleter.scripted(_proposal(cites=["H9"]), _proposal(cites=["H1"]))

    understood = await _understand(model)

    assert [call.shape for call in model.calls] == [ProposedActivationUnderstanding] * 2
    assert [call.model for call in model.calls] == [None, None]  # §6:2: no route override
    assert understood.meaning == "A park closed."


async def test_a_value_goes_to_the_label_checks_as_a_parsed_output() -> None:
    """§8:2: a label resolving to nothing earns the one repair, as before the move."""
    model = FakeStructuredCompleter.scripted(_proposal(cites=["H7"]), _proposal(cites=["H1"]))

    understood = await _understand(model)

    assert len(model.calls) == 2
    statement = model.calls[1].messages[-1].content
    assert '"H7"' in statement
    assert [one.kind for one in understood.meaning_referents] == ["channel_item"]


@pytest.mark.parametrize(
    ("first", "kind"),
    [
        pytest.param("not json", ReplyFailure.INVALID, id="invalid"),
        pytest.param(
            ScriptedReply(text='{"understanding": "A p', failure=ReplyFailure.CUT),
            ReplyFailure.CUT,
            id="cut",
        ),
        pytest.param("   ", ReplyFailure.EMPTY, id="empty"),
    ],
)
async def test_a_reply_that_does_not_parse_costs_the_one_repair_naming_its_kind(
    first: str | ScriptedReply, kind: ReplyFailure
) -> None:
    """§8:3: the repair carries the first reply's text, or no assistant turn where empty,
    then the code-owned statement naming the failure's kind."""
    model = FakeStructuredCompleter.scripted(first, _proposal())

    understood = await _understand(model)

    assert len(model.calls) == 2
    repair = model.calls[1].messages
    statement = repair[-1]
    assert statement.role is Role.USER
    assert f"({kind.value})" in statement.content
    if kind is ReplyFailure.EMPTY:
        assert [one.role for one in repair] == [Role.SYSTEM, Role.USER, Role.USER]
    else:
        assert repair[2].role is Role.ASSISTANT
        assert repair[2].content == (first if isinstance(first, str) else first.text)
    assert understood.meaning == "A park closed."


@pytest.mark.parametrize(
    "second",
    [
        pytest.param("not json", id="invalid"),
        pytest.param("", id="empty"),
        pytest.param(ScriptedReply(text="{", failure=ReplyFailure.CUT), id="cut"),
    ],
)
async def test_the_same_failure_on_the_repair_raises(second: str | ScriptedReply) -> None:
    """§8:3, ADR-0276 §6:3: a second reply that does not parse raises, with no third call."""
    model = FakeStructuredCompleter.scripted("not json", second)

    with pytest.raises(UnderstandingError):
        await _understand(model)

    assert len(model.calls) == 2


@pytest.mark.parametrize("at", ["first", "repair"])
async def test_a_refusal_raises_content_filter_with_no_repair_after_its_entry(at: str) -> None:
    """§8:4: no repair; the returned entry is written first, its kind named."""
    refused = ScriptedReply(failure=ReplyFailure.REFUSED, refusal="Declined.")
    script = (refused,) if at == "first" else (_proposal(cites=["H9"]), refused)
    model = FakeStructuredCompleter.scripted(*script)
    sink = FakeDiagnosticSink()

    with pytest.raises(ModelContentFilterError):
        await _understand(model, sink=sink)

    assert len(model.calls) == len(script)
    returned = sink.of(DiagnosticSource.UNDERSTANDING, DiagnosticKind.RETURNED)[-1]
    body = returned.model_dump(mode="json")["body"]
    assert (body["failure"], body["refusal"]) == ("refused", "Declined.")


async def test_a_raised_model_error_propagates_unchanged() -> None:
    """§8:5: a failure the seam raises is the provider's, and propagates as it is."""
    model = FakeStructuredCompleter.scripted(ModelError("the provider is down"))

    with pytest.raises(ModelError, match="the provider is down"):
        await _understand(model)


async def test_the_drop_of_unnamed_keys_and_its_log_line_are_gone() -> None:
    """§10:1: a key the shape does not name makes the reply ``invalid``; nothing drops it,
    and nothing logs a count of dropped keys."""
    model = FakeStructuredCompleter.scripted(_proposal(answers=[]), _proposal())

    with capture_logs() as logs:
        understood = await _understand(model)

    assert len(model.calls) == 2
    assert "(invalid)" in model.calls[1].messages[-1].content
    assert "answers" not in understood.model_dump()
    assert not [one for one in logs if one["event"] == "understanding_stray_keys"]
    assert not hasattr(understanding, "_pruned_reply")
    assert not hasattr(understanding, "_parsed")
