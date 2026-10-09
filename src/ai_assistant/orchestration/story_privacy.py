"""The privacy minimum for a story's notes and summary: which of them a reader sees.

ADR-0304 §4 rules it until privacy is designed. A story's notes and its summary are
records placed for the owner alone, whoever wrote them. A note is shown to a reader
only where such a record may be shown to that reader (ADR-0303 §3:9), and the summary
on the same rule (ADR-0304 §4:1). Where the summary may not be shown, none of it is,
and the reader is told that a summary was withheld (§4:2).

**Nothing behind a summary decides it** (§4:3). No rule walks a version log, and no
episode or note a version took in withholds a summary, forgotten or not: whether a
summary may be shown is one question about the reader, answered without reading any
record. ADR-0303 §3:10-§3:12's walk over what stands behind a summary is retired with
the withholding it decided.

**The rule is decided here once, for every reader of a summary**: understanding's short
views and the owner's story summary view today, and planning's views once the phases
build them. The owner reading directly may always be shown a record placed for the
owner alone; a model-facing reader may where its pass's audience admits one. The
tidy-up and the matters pass are no readers here: they apply no reader's rule (§4:4).
Nothing of ADR-0300's summary is live outside a test hub until the phases' cutover
(ADR-0300 §13).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_assistant.core.types import EpisodicMemory, StoryNote

__all__ = ["SummaryVisibility", "activation_of"]


def activation_of(record: EpisodicMemory) -> str | None:
    """The activation an episode records, or ``None`` for one that records none.

    Read off the episode's processing record (ADR-0275), never parsed out of its id:
    an episode written before activations were recorded has no processing record,
    and is the episode of no activation a story could hold.
    """
    processing = record.processing_record
    return None if processing is None else processing.activation_id


@dataclass(frozen=True, slots=True)
class SummaryVisibility:
    """Whether one reader may be shown a story's notes and its summary (ADR-0304 §4).

    Attributes:
        owner_records: Whether a record placed for the owner alone may be shown to
            the reader, which decides every note (ADR-0303 §3:9) and the summary
            (ADR-0304 §4:1) alike.
    """

    owner_records: bool

    def note(self, note: StoryNote) -> bool:  # noqa: ARG002 — §3:9 reads nothing of the note
        """Whether ``note`` may be shown: where an owner record may be, whoever wrote it."""
        return self.owner_records

    def summary(self) -> bool:
        """Whether the summary may be shown: where an owner record may be (ADR-0304 §4:1).

        Nothing behind it is read (§4:3): no version, no episode and no note it took in
        decides it.
        """
        return self.owner_records
