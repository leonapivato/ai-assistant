"""Observer files for the learning lane's and the overview's tests (ADR-0333 §5:8).

The observer files are written the way the hub writes them: the observer itself runs over
the canonical fakes, its model routes scripted, with ADR-0314's own store as its sink. So
a change to what the observer writes, or to the line the store writes, fails the viewer's
tests that read it. No live model is called and no hub is contacted.

The record holds four episodes the observer learned from, oldest first:

- ``a-kept``: two findings, one a memory created and one the commit step kept nothing of,
  and a third proposal the scout's labels did not resolve, dropped;
- ``a-skipped``: nothing to read, so its attempt's end entry alone;
- ``a-retried``: a scout call that failed, then a second attempt that kept a single
  observation as evidence;
- ``a-alone``: a memory created, and no file of its own in the record (§5:6).

The first three also have their own activation's file, as understanding writes it, so
the overview can show each one's input.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from ai_assistant.core.types import DiagnosticEntry, DiagnosticKind, DiagnosticSource
from ai_assistant.evaluation.diagnostic_record import FileDiagnosticRecord
from ai_assistant.testing import FakeModelProvider

sys.path.insert(0, str(Path(__file__).parent.parent / "orchestration"))
from observer_support import AT, Harness, episode, reply

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import Message

#: What each episode's user said, and so what its own file shows as its input.
SAID: Final = {
    "a-kept": "I prefer window seats when I fly, and I am vegetarian these days.",
    "a-skipped": "",
    "a-retried": "Remind me that the dentist moved to Thursdays.",
    "a-alone": "My sister Imogen lives in Lisbon.",
}

#: The scout's claims, by the episode they come from.
KEPT_CLAIM: Final = "The user prefers window seats."
NOT_KEPT_CLAIM: Final = "The user is vegetarian."
EVIDENCE_CLAIM: Final = "The user's dentist appointments are on Thursdays."
ALONE_CLAIM: Final = "The user's sister Imogen lives in Lisbon."

#: Why the commit step kept nothing of the vegetarian finding, in its own words.
NOT_KEPT_NOTE: Final = "Said in passing about these days; not a lasting preference yet."

_BIG_FILE: Final = 8 * 1024 * 1024


def _claim_of(messages: Sequence[Message]) -> str:
    return str(json.loads(messages[-1].content)["claim"])


class _Routes:
    """The two model routes, each answering from the episode or the claim it is shown."""

    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self.failed_once = False

    def scout(self, messages: Sequence[Message]) -> str:
        self.harness.clock.advance(timedelta(seconds=3))
        leaving = json.loads(messages[-1].content)["leaving"]
        shown = " ".join(str(one.get("text", "")) for one in leaving["parts"])
        if SAID["a-retried"] in shown and not self.failed_once:
            self.failed_once = True
            msg = "the provider timed out"
            raise RuntimeError(msg)
        if SAID["a-kept"] in shown:
            findings = [
                {"claim": KEPT_CLAIM, "rests_on": ["P1"]},
                {"claim": NOT_KEPT_CLAIM, "rests_on": ["P1"]},
                {"claim": "Rests on a label nothing read.", "rests_on": ["P404"]},
            ]
        elif SAID["a-retried"] in shown:
            findings = [{"claim": EVIDENCE_CLAIM, "rests_on": ["P1"]}]
        else:
            findings = [{"claim": ALONE_CLAIM, "rests_on": ["P1"]}]
        return reply(findings=findings)

    def commit(self, messages: Sequence[Message]) -> str:
        self.harness.clock.advance(timedelta(seconds=2))
        claim = _claim_of(messages)
        if claim == NOT_KEPT_CLAIM:
            return reply(action="nothing", note=NOT_KEPT_NOTE)
        if claim == EVIDENCE_CLAIM:
            return reply(action="single_observation", note="Once so far; kept as evidence.")
        return reply(
            action="create",
            wording=claim,
            supports=[
                {
                    "part": "P1",
                    "direction": "for",
                    "backs_as_worded": True,
                    "how_sure": "sure",
                    "note": "The user said so in their own words.",
                }
            ],
            note="A stated fact about the user.",
        )


def _own(activation_id: str, minutes: int) -> list[DiagnosticEntry]:
    """The activation's own file, as understanding and the controller write it."""
    start = AT - timedelta(minutes=minutes)
    payload = {
        "input": {"received_as": "the message the user just sent", "text": SAID[activation_id]}
    }
    rows: list[tuple[DiagnosticSource, DiagnosticKind, int, dict[str, Any]]] = [
        (
            DiagnosticSource.UNDERSTANDING,
            DiagnosticKind.GIVEN,
            10,
            {
                "messages": [
                    {"role": "system", "content": "instruction", "name": None},
                    {"role": "user", "content": json.dumps(payload), "name": None},
                ]
            },
        ),
        (DiagnosticSource.UNDERSTANDING, DiagnosticKind.RETURNED, 900, {"reply": "{}"}),
        (
            DiagnosticSource.CONTROLLER,
            DiagnosticKind.STEP,
            950,
            {
                "stage": "end",
                "due": "nothing_due",
                "started_at": (start + timedelta(milliseconds=950)).isoformat(),
                "ended_at": (start + timedelta(milliseconds=950)).isoformat(),
                "outcome": "done",
            },
        ),
    ]
    return [
        DiagnosticEntry(
            activation_id=activation_id,
            source=source,
            kind=kind,
            recorded_at=start + timedelta(milliseconds=ms),
            body=body,
        )
        for source, kind, ms, body in rows
    ]


async def _learn(directory: Path) -> None:
    record = FileDiagnosticRecord(directory=directory, file_bytes=_BIG_FILE)
    harness = Harness()
    minutes = {"a-kept": 40, "a-skipped": 30, "a-retried": 20, "a-alone": 10}
    await harness.hold(
        *(
            episode(name, at=AT - timedelta(minutes=age), text=SAID[name])
            for name, age in minutes.items()
        ),
        episode("w-1", at=AT - timedelta(minutes=2), text="What time is it?"),
        episode("w-2", at=AT - timedelta(minutes=1), text="Thanks."),
    )
    for name in ("a-kept", "a-skipped", "a-retried"):
        for entry in _own(name, minutes[name]):
            await record.write(entry)
    routes = _Routes(harness)
    observer = harness.observer(
        scout=FakeModelProvider(reply=routes.scout),
        commit=FakeModelProvider(reply=routes.commit),
        diagnostics=record,
    )
    await observer.run()
    harness.clock.advance(timedelta(minutes=5))
    await observer.run()


def write_learning(directory: Path) -> Path:
    """The four episodes' observer files, and three of their own files, in ``directory``.

    Args:
        directory: The record's directory; created where missing.

    Returns:
        The directory.
    """
    directory.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_learn(directory))
    return directory
