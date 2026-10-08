"""ADR-0300 §11's privacy default: which of a story page's lines and notes a reader sees.

Until privacy is designed, a note is shown to a reader only where the episode it
rests on may be shown to that reader, and a note the user wrote directly only where a
record placed for the owner alone may be shown. A line is shown only where every note
it cites may be shown, so a line copying the user's direct note carries that note's
restriction (§11:1).

**The rule is decided here once, for every reader of a page.** Understanding's short
views (§6) are its first reader; where the matter stands (§8), the story commands and
planning (§10) read pages too, and each answers the same two questions about its own
reader — which episodes may that reader be shown, and may it be shown a record placed
for the owner alone — and hands the answers to :class:`PageVisibility`. What may be
shown is decided from identities and those two answers alone: no note's or line's text
is read to decide it.

**Undecidable is withheld.** A line citing a note the reader's caller did not hand
in — one the store no longer holds on this story, or one never looked up — is not
shown, because nothing establishes that its citation may be. A note resting on an
episode that is open, forgotten or refused by the reader's predicate is withheld the
same way: its caller hands in no episode for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from ai_assistant.core.types import EpisodicMemory, StoryNote, StoryNoteId, StoryPageLine

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
    """Which of a page's notes and lines one reader may be shown (ADR-0300 §11:1).

    Attributes:
        activations: The activations whose episodes the reader may be shown: each
            fetched and admitted by the reader's own rule — for a model-facing
            reader never open (ADR-0286 §6) and through its audience predicate, and
            for the owner reading directly every episode the store holds.
        owner_notes: Whether a record placed for the owner alone may be shown to the
            reader, which decides every note the user wrote directly.
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

    def note(self, note: StoryNote) -> bool:
        """Whether ``note`` may be shown: its episode may, or, unrested, an owner record may."""
        if note.rests_on is None:
            return self.owner_notes
        return note.rests_on in self.activations

    def line(self, line: StoryPageLine, notes: Mapping[StoryNoteId, StoryNote]) -> bool:
        """Whether ``line`` may be shown: every note it cites is in ``notes`` and may be."""
        return all(
            (cited := notes.get(note_id)) is not None and self.note(cited) for note_id in line.cites
        )
