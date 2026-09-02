"""ADR-0213 §12.18 at the two concrete readers (issue #1836).

§6: "A ``Reader`` states no topics, and no proposal reaching ``IngestionStage``
carries any. A source's own categories, folder, labels, tags or headers are **not**
a route by which a topic reaches a record." §12.18 words the obligation as a test:
"A reader's proposal carries the empty tuple, whatever the source entry contains —
including a source entry whose own fields are named like labels."

ADR-0183 §3's list of what a source may not set did not name topics because topics
did not exist, and §6 adds this axis to it rather than reading the omission as
permission. That matters more here than for the fields already on that list: a topic
drives a **destructive** act in one of §2's deferred consumers, so an adversary who
can place bytes in a source would otherwise be choosing which of the owner's records
a later "forget everything about X" destroys.

**What this adds to what is already pinned.** PR #1832 discharges §12.18 at the seam
§6 words it at — ``tests/orchestration/test_ingestion.py::
test_no_proposal_reaching_this_stage_carries_a_topic`` — over a ``FakeReader``
carrying label-shaped text. A fake states whatever the case hands it, so that arm
pins the *stage*, not the producers: neither ``CalendarReader`` nor ``EmailReader``
passes a ``topics=`` argument today, and nothing said so but the source. A later lane
routing a source's own categories, folder, labels, tags or headers into that field
would pass every check this project ran before this file.

**One module for both readers, not a case appended to each reader's own suite.** The
clause is one rule over the set of producers, and the two readers' modules are each
organised around a different ADR — the calendar's around ADR-0093/0096/0117, the
mail's around ADR-0140 §5's header rules. Stating it once, over both, is what makes a
*third* reader's omission visible here rather than discovered by its absence.

Every field below is one a careless reader would lift: the calendar's ``CATEGORIES``
is RFC 5545's own label list, the message's ``Keywords`` is RFC 5322's, and both
carry a folder property and a literal ``topics:`` line besides. The rendered content
is asserted too, so a reader that simply skipped the entry could not pass by
proposing nothing.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ics_fixtures import NOW as CALENDAR_NOW
from ics_fixtures import calendar, source, utc, vevent
from ics_fixtures import reader as calendar_reader
from mbox_fixtures import NOW as EMAIL_NOW
from mbox_fixtures import envelope, store
from mbox_fixtures import reader as email_reader

if TYPE_CHECKING:
    from pathlib import Path

#: A literal spelling of the field itself, in the one place each source has for free
#: text. Not a plausible entry — deliberately: it is the shape a reader that fed a
#: source's text to a model and stored what came back would find waiting for it.
_LITERAL = 'topics: ["health"]'


async def test_a_calendar_entry_whose_own_fields_are_named_like_labels_states_no_topics(
    tmp_path: Path,
) -> None:
    """``CalendarReader._proposal`` passes no ``topics=``, pinned rather than read.

    ``CATEGORIES`` is the property RFC 5545 provides for exactly the purpose §6
    forbids reading it for, and it is joined here by an ``X-`` folder property, a
    tag-shaped ``SUMMARY`` and the literal field name in the ``DESCRIPTION``. The
    entry sits inside the fixtures' ``[10:00, 14:00)`` window so the case turns on
    what the reader does with the fields rather than on whether it read them at all,
    and the rendered content is asserted because a reader that skipped the entry
    would otherwise satisfy an assertion about an empty list of topics vacuously.
    """
    entry = vevent(
        f"DTSTART:{utc(CALENDAR_NOW)}",
        "DURATION:PT1H",
        "SUMMARY:Tags: sleep",
        "LOCATION:Folder: Health/Sleep",
        "CATEGORIES:health,sleep",
        "X-FOLDER:Health/Sleep",
        f"DESCRIPTION:{_LITERAL}",
    )

    reading = await calendar_reader(source(tmp_path, calendar(entry))).read()

    assert [proposal.proposed.topics for proposal in reading.proposals] == [()]
    content = reading.proposals[0].proposed.content
    assert "Tags: sleep" in content, "the label-shaped entry must have been read, not skipped"


async def test_an_email_whose_own_headers_are_named_like_labels_states_no_topics(
    tmp_path: Path,
) -> None:
    """``EmailReader._proposal`` passes no ``topics=``, pinned rather than read.

    The message carries RFC 5322's own ``Keywords`` header, a folder header of the
    kind every mail store adds, a tag-shaped ``Subject`` and the literal field name
    in the body — which this reader does not even read, and which is here because a
    lane widening it to would meet the clause on the way. Delivered an hour before
    ``NOW`` so it lands inside the fixtures' ``[10:00, 12:00)`` window; the subject
    is asserted in the content for the same reason the calendar case asserts its
    summary.
    """
    message = envelope(
        subject="Tags: sleep",
        delivered_at=EMAIL_NOW - timedelta(hours=1),
        body=_LITERAL,
        extra=("Keywords: health, sleep", "X-Folder: Health/Sleep"),
    )

    reading = await email_reader(store(tmp_path, message)).read()

    assert [proposal.proposed.topics for proposal in reading.proposals] == [()]
    content = reading.proposals[0].proposed.content
    assert "Tags: sleep" in content, "the label-shaped message must have been read, not skipped"
