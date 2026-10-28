"""An activation whose understanding was repaired, as understanding's own stage records it.

The tagged message is the one ``_tagged_record`` renders, over the same invented records:
always in mind pins ``M1``, and recall's two kept memories are ``M2`` and ``M3``. Here the
stage's structured completer answers twice. The first reply cites ``M9``, which names
nothing shown, so it earns the one repair (ADR-0353 §9:10); the second cites ``M2`` and
``R4``, puts the pinned fact ``M1`` in ``belongs_to`` and ``R1`` in ``meant_for``, none of
which the message shows as a concurrent stimulus or a matter, so code drops ``R4``, ``M1``
and ``R1`` with no repair (§9:11, §9:12). Each response reports its usage and the model
that answered (ADR-0354 §7:2), and the second keeps a thinking summary of its own, as
ADR-0355 will have a structured call's returned entry keep one.

Around it, recall's two runs: the first by the input, the second by the meaning and by a
gap (``understood_gap``), each find naming the cue it was searched by (ADR-0314 §8).
"""

from __future__ import annotations

import asyncio
import itertools
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final
from zoneinfo import ZoneInfo

from _tagged_record import (
    ARRIVED,
    FIRST,
    KEPT_FACTS,
    KEPT_IDS,
    PINNED,
    SECOND,
    WRITTEN,
)

from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActivationRecall,
    BeliefBand,
    ChannelIdentity,
    DiagnosticEntry,
    DiagnosticKind,
    DiagnosticSource,
    MemoryKind,
    MessageAuthor,
    Profile,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    ReplyUsage,
)
from ai_assistant.evaluation.diagnostic_record import FileDiagnosticRecord
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.person_block import KeptInMind, PersonBlock
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    LineMessage,
    TranscriptWindow,
    UnderstandingStage,
)
from ai_assistant.testing import default_prompt
from ai_assistant.testing.diagnostics import FakeDiagnosticSink
from ai_assistant.testing.memories import memory, said_support
from ai_assistant.testing.structured import FakeStructuredCompleter, ScriptedReply

if TYPE_CHECKING:
    from pathlib import Path

#: The activation's id.
INSIGHT: Final = "insight"

#: The model each response says answered, one the viewer keeps rates for.
MODEL: Final = "anthropic:claude-sonnet-5-5"

#: The first reply: it cites a label the message never showed.
FIRST_REPLY: Final = json.dumps({"understanding": "Book the flight.", "cites": ["M2", "M9"]})

#: The repaired reply, its labels each resolving as ADR-0353 §9 has it.
SECOND_REPLY: Final = json.dumps(
    {
        "understanding": "Book the Lisbon flight for the 3rd and tell Ana.",
        "cites": ["M2", "R4", "M2"],
        "belongs_to": ["M1"],
        "meant_for": ["R1"],
    }
)

#: Each response's usage: input counts its cache reads and writes (``ReplyUsage``).
FIRST_USAGE: Final = ReplyUsage(
    input_tokens=12_345, output_tokens=456, cache_read_tokens=10_000, cache_write_tokens=1_000
)
SECOND_USAGE: Final = ReplyUsage(input_tokens=2_000, output_tokens=100)

#: The thinking summary the repaired reply's returned entry keeps as its own field.
THINKING: Final = "The 3rd is the date in the second message."

#: The second run's cues: the meaning, and one gap.
MEANING: Final = "Book the Lisbon flight for the 3rd and tell Ana."
GAP: Final = "which month the 3rd is in"

_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="conn-1/42")


def _person() -> PersonBlock:
    pinned = memory("mem-ana", PINNED, said_support(when=ARRIVED, added_at=ARRIVED))
    return PersonBlock(
        person_id=OWNER_PERSON_ID,
        profile=Profile(name="Maren", time_zone="America/New_York"),
        kept=(KeptInMind(memory=pinned, pinned=True),),
    )


def _kept(record_id: str) -> RecalledItem:
    return RecalledItem(
        kind=MemoryKind.MEMORY,
        id=record_id,
        excerpt="x",
        provenance=RecallProvenance.USER,
        standing=BeliefBand.ASSERTED,
        rests_on_recorded_external_content=False,
        found_by=(RecallCue.ACTIVATION_INPUT,),
    )


async def understanding_entries() -> tuple[DiagnosticEntry, ...]:
    """Understanding's two calls' entries, as its own stage writes them, a second apart."""
    sink = FakeDiagnosticSink()
    stage = UnderstandingStage(
        model=FakeStructuredCompleter.scripted(
            ScriptedReply(text=FIRST_REPLY, usage=FIRST_USAGE, model=MODEL),
            ScriptedReply(text=SECOND_REPLY, usage=SECOND_USAGE, model=MODEL),
        ),
        excerpt_chars=2000,
        prompt=default_prompt(UNDERSTANDING_PROMPT),
        diagnostics=sink,
    )
    window = TranscriptWindow(
        _LINE,
        (),
        input_messages=(
            LineMessage(position=7, written_at=WRITTEN, author=MessageAuthor.USER, text=FIRST),
            LineMessage(
                position=8,
                written_at=ARRIVED,
                author=MessageAuthor.USER,
                text=SECOND,
                replies_to=7,
            ),
        ),
    )
    recalled = tuple(
        memory(one, fact, said_support(when=ARRIVED, added_at=ARRIVED))
        for one, fact in zip(KEPT_IDS, KEPT_FACTS, strict=True)
    )
    ticks = itertools.count(10)
    with diagnosed_activation(INSIGHT, clock=lambda: ARRIVED + timedelta(seconds=next(ticks))):
        await stage.understand(
            f"{FIRST}\n\n{SECOND}",
            channel=_LINE,
            window=window,
            audience=BoundedAudienceSupply(speakable_attested_sources=frozenset()),
            episodes=(),
            version=1,
            now=lambda: ARRIVED,
            deadline=asyncio.get_running_loop().time() + 60,
            recall=ActivationRecall(
                outcome=RecallOutcome.FOUND,
                cues=(RecallCue.ACTIVATION_INPUT,),
                items=tuple(_kept(one) for one in KEPT_IDS),
            ),
            recalled=recalled,
            person=_person(),
            zone=ZoneInfo("America/New_York"),
            own_zone=True,
            received_at=ARRIVED,
        )
    return sink.of(DiagnosticSource.UNDERSTANDING)


def _find(cue: str, found: str, band: str, *, admitted: bool) -> dict[str, Any]:
    return {"id": found, "score": 0.5, "band": band, "cue": cue, "admitted": admitted}


def _recall(run: str, cues: list[dict[str, Any]], returned: dict[str, Any]) -> list[Any]:
    return [(DiagnosticKind.GIVEN, {"run": run, "cues": cues}), (DiagnosticKind.RETURNED, returned)]


#: Recall's first run, before understanding: its two kept memories and one find not kept.
FIRST_RUN: Final = _recall(
    "first",
    [{"text": FIRST, "kinds": ["activation_input"]}],
    {
        "outcome": "found",
        "finds": [
            _find(FIRST, KEPT_IDS[0], "asserted", admitted=True),
            _find(FIRST, KEPT_IDS[1], "asserted", admitted=True),
            _find(FIRST, "mem-weather", "derived", admitted=False),
        ],
        "kept": [{"id": one, "score": 0.5, "found_by": ["activation_input"]} for one in KEPT_IDS],
    },
)

#: Recall's second run, after: the meaning finds one memory, the gap another, kept both.
SECOND_RUN: Final = _recall(
    "second",
    [
        {"text": MEANING, "kinds": ["understood_meaning"]},
        {"text": GAP, "kinds": ["understood_gap"]},
    ],
    {
        "outcome": "found",
        "finds": [
            _find(MEANING, "mem-trip", "asserted", admitted=True),
            _find(GAP, "mem-may", "asserted", admitted=True),
            _find(GAP, "mem-june", "derived", admitted=False),
            _find("a cue the given entry never listed", "mem-odd", "asserted", admitted=True),
        ],
        "kept": [
            {"id": "mem-trip", "score": 0.5, "found_by": ["understood_meaning"]},
            {"id": "mem-may", "score": 0.5, "found_by": ["understood_gap"]},
        ],
    },
)


def write_insight(directory: Path) -> Path:
    """The repaired activation, written by ADR-0314's store into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    asyncio.run(_write(directory))
    return directory


async def _write(directory: Path) -> None:
    """Recall's first run, understanding's two calls, then recall's second run."""
    store = FileDiagnosticRecord(directory=directory, file_bytes=8 * 1024 * 1024)

    async def recall(rows: list[Any], second: int) -> None:
        for n, (kind, body) in enumerate(rows):
            await store.write(
                DiagnosticEntry(
                    activation_id=INSIGHT,
                    source=DiagnosticSource.RECALL,
                    kind=kind,
                    recorded_at=ARRIVED + timedelta(seconds=second + n),
                    body=body,
                )
            )

    await recall(FIRST_RUN, 1)
    entries = list(await understanding_entries())
    # ADR-0355's field, on the repaired call's returned entry: the stage writes none yet.
    last = entries[-1]
    entries[-1] = last.model_copy(update={"body": {**last.body, "thinking": THINKING}})
    for entry in entries:
        await store.write(entry)
    # The controller's step for the run, holding both calls (ADR-0314 §4).
    started, ended = ARRIVED + timedelta(seconds=9), ARRIVED + timedelta(seconds=30)
    await store.write(
        DiagnosticEntry(
            activation_id=INSIGHT,
            source=DiagnosticSource.CONTROLLER,
            kind=DiagnosticKind.STEP,
            recorded_at=ended,
            body={
                "stage": "understanding",
                "due": "not_understood",
                "started_at": started.isoformat(),
                "ended_at": ended.isoformat(),
                "outcome": "done",
            },
        )
    )
    await recall(SECOND_RUN, 60)
