#!/usr/bin/env python3
"""Measure the score scale recall's threshold is chosen on (ADR-0281 §3, #2601).

ADR-0281 §3 has the threshold for ``FastEmbedEmbedder`` chosen so that "a short
input carrying no content, such as "yes", "ok" or "same as before", normally keeps
nothing, while a paraphrase of a stored fact keeps it", and has the implementation
record the measurement the value was chosen from. This is that measurement, kept
so it can be run again: a ``SqliteMemoryStore`` over the real embedder is seeded
with :data:`FACTS` and :data:`EPISODES`, and each cue is scored against it with the
store's own ``search``, whose ``score`` is the number recall compares with its
threshold (cosine similarity to the query, in ``[0, 1]``).

Two groups of cues are scored:

- :data:`CONTENT_FREE`: replies that carry nothing to recall by. Each one's figure
  is the **best** score any stored record takes, since recall would keep that record
  if it cleared the threshold.
- :data:`PARAPHRASES`: questions and mentions whose matter is one stored record,
  in other words. Each one's figure is **that record's** score, since recall must
  keep it.

The threshold belongs in the gap between the content-free maximum and the
paraphrase minimum. ``tests/app/test_recall_threshold_measured.py`` pins both sides
against ``RECALL_THRESHOLDS`` from these same lists, so a change of embedder or
model that closes the gap fails there.

Run it with ``uv run python scripts/measure_recall_threshold.py`` for the
on-device embedder, or with ``--hashing`` for the hashing one; it prints the table
as Markdown. The model is the vendored one (ADR-0024), so nothing is downloaded.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import EpisodicMemory, MemoryKind, MemorySource, Provenance
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.models.embeddings import HashingEmbedder
from ai_assistant.models.fastembed_embedder import FastEmbedEmbedder
from ai_assistant.testing import FakeTraceSink
from ai_assistant.testing.memories import memory

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import Embedder
    from ai_assistant.core.types import MemoryRecord

_AT: Final = datetime(2026, 10, 1, 12, tzinfo=UTC)

#: Stored beliefs, keyed by id: the kind of thing a user tells the assistant.
FACTS: Final[dict[str, str]] = {
    "dentist": "The dentist appointment is on Friday at 3pm.",
    "birthday": "Sam's birthday is on March 14.",
    "allergy": "The user is allergic to penicillin.",
    "oil-change": "The car is due for an oil change next month.",
    "rent": "The rent of 1,450 dollars is due on the first of each month.",
    "sister": "The user's sister Maria lives in Lisbon.",
    "standup": "The team standup moves to 9:30 starting next week.",
    "aisle": "The user prefers aisle seats on flights.",
    "wifi": "The Wi-Fi password for the cabin is on the fridge.",
    "marathon": "The user is training for a half marathon in May.",
    "library": "The library books are due back on the 20th.",
    "manager": "The user's manager at work is Priya.",
    "vegetarian": "The user is vegetarian.",
    "gym": "The user goes to the gym on Monday, Wednesday and Friday mornings.",
}

#: Stored episodes, keyed by id: things that happened, as capture words them.
EPISODES: Final[dict[str, str]] = {
    "dinner": "The user asked to book a table for four at the Italian place on Saturday.",
    "plumber": "The plumber fixed the leaking kitchen sink and said the pipe needs replacing.",
    "report": "The user said they were stressed about the quarterly report deadline.",
    "package": "A delivery notice said the package from the bookstore arrives Tuesday.",
    "thermostat": "The thermostat entered eco mode at 18:00.",
    "flight": "The user's flight to Denver was delayed by two hours.",
}

#: Replies that carry nothing to recall by (ADR-0281 §3's "yes", "ok", "same as
#: before", and their kind).
CONTENT_FREE: Final[tuple[str, ...]] = (
    "yes",
    "ok",
    "okay",
    "no",
    "same as before",
    "sounds good",
    "thanks",
    "thank you",
    "sure",
    "got it",
    "go ahead",
    "cool",
    "yep",
    "nope",
    "hmm",
    "do it",
    "that works",
    "never mind",
    "perfect",
    "hi",
    "lol",
    "yes please",
    "as usual",
    "the same again",
)

#: A cue and the id of the stored record whose matter it is, in other words.
PARAPHRASES: Final[tuple[tuple[str, str], ...]] = (
    ("when's my dentist thing", "dentist"),
    ("what day is the dentist again", "dentist"),
    ("when is Sam's birthday", "birthday"),
    ("what am I allergic to", "allergy"),
    ("is the car due for service soon", "oil-change"),
    ("when do I have to pay rent", "rent"),
    ("where does my sister live", "sister"),
    ("what time is standup now", "standup"),
    ("what seat do I like on planes", "aisle"),
    ("what's the wifi password at the cabin", "wifi"),
    ("how's the marathon training going", "marathon"),
    ("when are the library books due", "library"),
    ("who is my boss", "manager"),
    ("can you suggest a recipe I can eat, I don't eat meat", "vegetarian"),
    ("which days do I work out", "gym"),
    ("did we get the dinner reservation for Saturday", "dinner"),
    ("what did the plumber say about the sink", "plumber"),
    ("the quarterly report is stressing me out again", "report"),
    ("when is my book order arriving", "package"),
    ("why did the heating switch to eco", "thermostat"),
    ("is the Denver flight still delayed", "flight"),
)


@dataclass(frozen=True)
class Scored:
    """One cue's figure, and what took it.

    Attributes:
        cue: The cue as searched.
        score: The figure: the best score for a content-free cue, the expected
            record's score for a paraphrase.
        record: The id of the record that took ``score``.
        best: The id of the best-scoring record, which for a paraphrase may be
            another one.
    """

    cue: str
    score: float
    record: str
    best: str


@dataclass(frozen=True)
class Measurement:
    """Both groups' figures, in the lists' order."""

    content_free: tuple[Scored, ...]
    paraphrases: tuple[Scored, ...]

    @property
    def content_free_max(self) -> float:
        """The highest score any content-free cue gives any record."""
        return max(one.score for one in self.content_free)

    @property
    def paraphrase_min(self) -> float:
        """The lowest score a paraphrase gives the record it is about."""
        return min(one.score for one in self.paraphrases)

    @property
    def gap(self) -> float:
        """The paraphrase minimum less the content-free maximum; negative is overlap."""
        return self.paraphrase_min - self.content_free_max


def _records() -> list[MemoryRecord]:
    observed = Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_AT)
    facts: list[MemoryRecord] = [memory(key, text) for key, text in FACTS.items()]
    episodes: list[MemoryRecord] = [
        EpisodicMemory(id=key, content=text, occurred_at=_AT, provenance=observed)
        for key, text in EPISODES.items()
    ]
    return facts + episodes


async def _scores(store: SqliteMemoryStore, cue: str) -> dict[str, float]:
    """Every stored record's score for ``cue``, as recall's search returns it."""
    found = await store.search(
        cue,
        limit=len(FACTS) + len(EPISODES),
        kinds=(MemoryKind.EPISODIC, MemoryKind.MEMORY),
    )
    return {record.id: record.score for record in found.records if record.score is not None}


async def measure(embedder: Embedder) -> Measurement:
    """Seed a store over ``embedder`` and score both groups of cues against it.

    Args:
        embedder: The embedder whose score scale is measured.

    Returns:
        Both groups' figures.
    """
    store = SqliteMemoryStore(
        path=":memory:", embedder=embedder, traces_sink=FakeTraceSink(), now=lambda: _AT
    )
    try:
        for record in _records():
            await store.add(record)
        content_free: list[Scored] = []
        for cue in CONTENT_FREE:
            scores = await _scores(store, cue)
            best = max(scores, key=scores.__getitem__)
            content_free.append(Scored(cue, scores[best], best, best))
        paraphrases: list[Scored] = []
        for cue, expected in PARAPHRASES:
            scores = await _scores(store, cue)
            best = max(scores, key=scores.__getitem__)
            paraphrases.append(Scored(cue, scores.get(expected, 0.0), expected, best))
        return Measurement(tuple(content_free), tuple(paraphrases))
    finally:
        store.close()


def table(measurement: Measurement) -> str:
    """The measurement as the Markdown table the PR records.

    Args:
        measurement: What :func:`measure` returned.

    Returns:
        Two tables, the content-free cues then the paraphrases, each sorted by
        score (highest content-free first, lowest paraphrase first), and a summary
        line with the content-free maximum, the paraphrase minimum and the gap.
    """
    lines = ["| content-free cue | best score | best record |", "|---|---:|---|"]
    lines += [
        f"| {one.cue} | {one.score:.3f} | {one.record} |"
        for one in sorted(measurement.content_free, key=lambda one: -one.score)
    ]
    lines += ["", "| paraphrase cue | its record | score | best record |", "|---|---|---:|---|"]
    lines += [
        f"| {one.cue} | {one.record} | {one.score:.3f} | {one.best} |"
        for one in sorted(measurement.paraphrases, key=lambda one: one.score)
    ]
    lines += [
        "",
        f"content-free max **{measurement.content_free_max:.3f}**, "
        f"paraphrase min **{measurement.paraphrase_min:.3f}**, "
        f"gap **{measurement.gap:.3f}**",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    """Print the measurement's table for the chosen embedder."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--hashing", action="store_true", help="measure the hashing embedder instead"
    )
    args = parser.parse_args(argv)
    embedder: Embedder = HashingEmbedder() if args.hashing else FastEmbedEmbedder()
    print(table(asyncio.run(measure(embedder))))


if __name__ == "__main__":
    main()
