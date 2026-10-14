"""ADR-0213 §12.18 at the concrete reader (issue #1836).

§6: "A ``Reader`` states no topics, and no proposal reaching ``IngestionStage`` carries
any. A source's own categories, folder, labels, tags or headers are **not** a route by
which a topic reaches a record." §12.18 words the obligation as a test: "A reader's
proposal carries the empty tuple, whatever the source entry contains — including a
source entry whose own fields are named like labels." The stage is retired (ADR-0294
§1); the reader half of the clause is what stands, and this module is where it is
pinned.

ADR-0183 §3's list of what a source may not set did not name topics because topics
did not exist, and §6 adds this axis to it rather than reading the omission as
permission. That matters more here than for the fields already on that list: a topic
drives a **destructive** act in one of §2's deferred consumers, so an adversary who
can place bytes in a source would otherwise be choosing which of the owner's records
a later "forget everything about X" destroys.

**What this pins.** PR #1832 discharged §12.18 at the stage §6 words it at, over a
``FakeReader`` carrying label-shaped text, and that arm left with the stage. A fake
states whatever the case hands it, so it pinned the *stage*, not the producer:
``CalendarReader`` passes no ``topics=`` argument today, and nothing said so but the
source. A later lane routing a source's own categories, folder, labels, tags or
headers into that field would pass every check this project ran before this file.

**One module for the clause, not a case appended to the reader's own suite.** The
clause is one rule over the set of producers, and the calendar's module is organised
around ADR-0093/0096/0117 rather than around it. Stating it here is what makes a
*next* reader's omission visible rather than discovered by its absence.

Every field below is one a careless reader would lift: ``CATEGORIES`` is RFC 5545's
own label list, and the entry carries a folder property and a literal ``topics:``
line besides. The rendered content
is asserted too, so a reader that simply skipped the entry could not pass by
proposing nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ics_fixtures import NOW as CALENDAR_NOW
from ics_fixtures import calendar, source, utc, vevent
from ics_fixtures import reader as calendar_reader

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
