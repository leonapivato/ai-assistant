"""Shared wiring for suites that drive ADR-0276's understanding stage end to end."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel

from ai_assistant.core.protocols import StructuredCompleter
from ai_assistant.core.reply_shapes import read_reply, reply_shape_version
from ai_assistant.core.types import ReplyExchange, ReplyFailure, ReplyMode, StructuredReply
from ai_assistant.orchestration.recall import RecallStage
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    RecentEpisodes,
    UnderstandingStage,
    WindowsStage,
)
from ai_assistant.testing import FakeModelProvider, FakeStoryStore, default_prompt
from ai_assistant.testing.structured import DEFAULT_STRUCTURED_MODEL

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import MemoryStore, ModelProvider, StoryStore
    from ai_assistant.core.types import Message

#: The composition root's three values (ADR-0276 §4, §7), restated for the suites that
#: build an engine without it; ``tests/app`` pins that the root wires these same ones.
EPISODE_LIMIT: Final = 10
EXCERPT_CHARS: Final = 2000
VERSION_LIMIT: Final = 8

#: ADR-0281's item limit and budget, restated as above; ``tests/app`` pins the root's.
RECALL_LIMIT: Final = 3
RECALL_BUDGET: Final = timedelta(seconds=2)

#: A threshold for the canonical fake, whose score is the share of the query's terms a
#: record's content holds (ADR-0281 §3: tests set their own for what they search).
FAKE_RECALL_THRESHOLD: Final = 0.5

#: The root's threshold for the vendored on-device embedder, restated for the suite that
#: recalls over it; ``tests/app`` pins that the root wires this same one.
ON_DEVICE_RECALL_THRESHOLD: Final = 0.58

#: The smallest well-formed proposal: a meaning grounded in the input alone.
STATED_PROPOSAL: Final = json.dumps({"understanding": "The input means what it says."})


class TextAsStructured:
    """A completion provider seen as the structured seam the stage asks (ADR-0354 §8:1).

    For suites that drive the stage end to end through a scripted
    :class:`~ai_assistant.core.protocols.ModelProvider`: each structured call is the
    wrapped provider's completion, its reply read by ``core``'s one rule with the shape
    (§3:4), as the canonical structured fake reads a scripted reply. The wrapped
    provider records each call, so a suite reads what the stage sent from it, and a
    failure it raises propagates unchanged.
    """

    def __init__(self, provider: ModelProvider) -> None:
        """Wrap ``provider``, whose completions answer each structured call."""
        self.provider = provider

    async def complete_structured[T: BaseModel](
        self, messages: Sequence[Message], shape: type[T], *, model: str | None = None
    ) -> StructuredReply[T]:
        """Complete through the wrapped provider and read the reply as ``shape``."""
        del model
        reply = (await self.provider.complete(messages)).content
        exchange = ReplyExchange(
            reply=reply,
            model=DEFAULT_STRUCTURED_MODEL,
            mode=ReplyMode.NATIVE,
            finish_reason="stop",
            shape=shape.__name__,
            shape_version=reply_shape_version(shape),
        )
        read = read_reply(shape, reply)
        if isinstance(read, ReplyFailure):
            return StructuredReply(failure=read, exchange=exchange)
        return StructuredReply(value=read, exchange=exchange)


def understanding_stage(
    *, model: ModelProvider | StructuredCompleter | None = None
) -> UnderstandingStage:
    """The stage the composition root builds, over a scripted model; it reads no store.

    A completion provider is seen as the structured seam (:class:`TextAsStructured`).
    """
    if model is None:
        model = FakeModelProvider(reply=STATED_PROPOSAL)
    return UnderstandingStage(
        model=model if isinstance(model, StructuredCompleter) else TextAsStructured(model),
        excerpt_chars=EXCERPT_CHARS,
        prompt=default_prompt(UNDERSTANDING_PROMPT),
    )


def windows_stage(memory: MemoryStore) -> WindowsStage:
    """The windows stage the composition root builds, its selector over ``memory``."""
    return WindowsStage(episodes=RecentEpisodes(memory=memory, limit=EPISODE_LIMIT))


def recall_stage(
    memory: MemoryStore,
    *,
    threshold: float = FAKE_RECALL_THRESHOLD,
    stories: StoryStore | None = None,
) -> RecallStage:
    """The recall stage the composition root builds, over ``memory`` and ``stories``.

    An empty story store where none is named, so every kept episode belongs to no story.
    """
    return RecallStage(
        memory=memory,
        stories=FakeStoryStore() if stories is None else stories,
        threshold=threshold,
        limit=RECALL_LIMIT,
        budget=RECALL_BUDGET,
    )


# --- reading the rendered message (ADR-0353 §2, §3) -------------------------------------

#: A text tag of ADR-0353 §3:2, empty or holding text, its attributes as written.
_TEXT_TAG: Final = re.compile(
    r"<(said|received|task|message|understood|response|memory|summary|note|latest)"
    r'((?: [a-z_]+="[^"]*")*)(?:/>|>(.*?)</\1>)',
    re.DOTALL,
)
#: A container of §3:3 and the tags it holds.
_CONTAINER: Final = re.compile(r'<(stimulus|matter)((?: [a-z_]+="[^"]*")*)>\n(.*?)</\1>', re.DOTALL)
_ATTRIBUTE: Final = re.compile(r'([a-z_]+)="([^"]*)"')


def unescaped(text: str) -> str:
    """A rendered value as it was before §3:5's escaping."""
    return (
        text.replace("&#35;", "#")
        .replace("&quot;", '"')
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


@dataclass(frozen=True)
class Tag:
    """One text tag as rendered: its name, its attributes unescaped, its text or ``None``."""

    name: str
    attributes: dict[str, str]
    text: str | None

    def get(self, key: str) -> str | None:
        """One attribute's value, or ``None`` where it carries none."""
        return self.attributes.get(key)


@dataclass(frozen=True)
class Container:
    """One container as rendered: its attributes and the tags it holds, in order."""

    name: str
    attributes: dict[str, str]
    tags: list[Tag] = field(default_factory=list)

    @property
    def label(self) -> str | None:
        """Its label, where it carries one."""
        return self.attributes.get("label")

    def get(self, key: str) -> str | None:
        """One attribute's value, or ``None`` where it carries none."""
        return self.attributes.get(key)


def _attributes(written: str) -> dict[str, str]:
    return {key: unescaped(value) for key, value in _ATTRIBUTE.findall(written)}


def _tags(body: str) -> list[Tag]:
    return [
        Tag(
            m.group(1),
            _attributes(m.group(2)),
            None if m.group(3) is None else unescaped(m.group(3)),
        )
        for m in _TEXT_TAG.finditer(body)
    ]


class Rendered:
    """Understanding's user message read back by its sections, tags and containers."""

    def __init__(self, content: str) -> None:
        """Split ``content`` into its sections, each under its heading's words."""
        self.content = content
        self.sections: dict[str, str] = {}
        heading: str | None = None
        lines: list[str] = []
        for line in content.split("\n"):
            if line.startswith("#"):
                if heading is not None:
                    self.sections[heading] = "\n".join(lines).strip("\n")
                heading = line.lstrip("#").strip()
                lines = []
            else:
                lines.append(line)
        if heading is not None:
            self.sections[heading] = "\n".join(lines).strip("\n")

    def headings(self) -> list[str]:
        """The section headings, in the order they render."""
        return list(self.sections)

    def section(self, heading: str) -> str:
        """One section's body, as rendered."""
        return self.sections[heading]

    def tags(self, heading: str, name: str | None = None) -> list[Tag]:
        """Every text tag a section renders, its containers' included, in order."""
        found = _tags(self.sections[heading])
        return [one for one in found if name is None or one.name == name]

    def containers(self, heading: str) -> list[Container]:
        """Every container a section renders, in order."""
        return [
            Container(m.group(1), _attributes(m.group(2)), _tags(m.group(3)))
            for m in _CONTAINER.finditer(self.sections[heading])
        ]

    def labelled(self, heading: str) -> list[str]:
        """Every label a section's items carry, in order."""
        held = self.sections[heading]
        return [unescaped(one) for one in re.findall(r' label="([^"]*)"', held)]

    @property
    def stimulus(self) -> str:
        """The stimulus's own words: the texts of its tags, joined by line breaks."""
        return "\n".join(one.text or "" for one in self.tags("The stimulus"))

    def concurrent(self) -> list[dict[str, str]]:
        """Each concurrent stimulus: its attributes, and ``input``, its texts joined."""
        return [
            {**one.attributes, "input": " ".join(tag.text or "" for tag in one.tags)}
            for one in self.containers("Concurrent stimuli")
        ]


def rendered(messages: Sequence[Message]) -> Rendered:
    """The understanding call's user message, read back (its second message)."""
    return Rendered(messages[1].content)
