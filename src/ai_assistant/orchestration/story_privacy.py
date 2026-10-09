"""The privacy default for a story's page: which of its notes and page a reader sees.

ADR-0303 §3 rules it for now: a note is shown to a reader only where a record placed
for the owner alone may be shown to that reader, whoever wrote it (§3:6), and the
current page only where everything behind it may be shown (§3:7, §3:8). A note rests
on nothing and a line cites nothing, so ADR-0300 §11:1's tests, which read the episode
a note rested on and the notes a line cited, are gone.

**The rule is decided here once, for every reader of a page.** Understanding's short
views are its first reader; the story commands read pages too, and each answers the
same two questions about its own reader — which episodes may that reader be shown,
and may it be shown a record placed for the owner alone — and hands the answers to
:class:`PageVisibility`. What may be shown is decided from identities and those two
answers alone: no note's or line's text is read to decide it.

**Interim, until ADR-0303 §12:3's lane.** :meth:`PageVisibility.page` shows a page
exactly where a record placed for the owner alone may be shown: every note is such a
record (§3:6), so a page that took one in can be shown nowhere wider. The walk §3:7
asks for, over every note and episode behind every version a page's runs read, which
also withholds a page an open or forgotten episode stands behind (§3:8), is that
lane's, with the views it rebuilds. Nothing of ADR-0300's page is live outside a test
hub until the phases' cutover (ADR-0300 §13).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import EpisodicMemory, StoryNote

__all__ = ["PageVisibility", "activation_of"]


def activation_of(record: EpisodicMemory) -> str | None:
    """The activation an episode records, or ``None`` for one that records none.

    Read off the episode's processing record (ADR-0275), never parsed out of its id:
    an episode written before activations were recorded has no processing record,
    and is the episode of no activation a story could hold.
    """
    processing = record.processing_record
    return None if processing is None else processing.activation_id


@dataclass(frozen=True, slots=True)
class PageVisibility:
    """Which of a story's notes, and whether its page, one reader may be shown.

    Attributes:
        activations: The activations whose episodes the reader may be shown: each
            fetched and admitted by the reader's own rule — for a model-facing
            reader never open (ADR-0286 §6) and through its audience predicate, and
            for the owner reading directly every episode the store holds.
        owner_notes: Whether a record placed for the owner alone may be shown to the
            reader, which decides every note (ADR-0303 §3:6) and, until ADR-0303
            §12:3's lane, the page.
    """

    activations: frozenset[str]
    owner_notes: bool

    @classmethod
    def of(cls, episodes: Iterable[EpisodicMemory], *, owner_notes: bool) -> PageVisibility:
        """The visibility for a reader who may be shown exactly ``episodes``.

        Args:
            episodes: The episodes the reader may be shown, already through its
                predicate. One recording no activation contributes nothing.
            owner_notes: Whether a record placed for the owner alone may be shown.

        Returns:
            The reader's visibility.
        """
        return cls(
            activations=frozenset(
                activation for record in episodes if (activation := activation_of(record))
            ),
            owner_notes=owner_notes,
        )

    def note(self, note: StoryNote) -> bool:  # noqa: ARG002 — §3:6 reads nothing of the note
        """Whether ``note`` may be shown: where an owner record may be, whoever wrote it."""
        return self.owner_notes

    def page(self) -> bool:
        """Whether the current page may be shown: for now, where an owner record may be."""
        return self.owner_notes
