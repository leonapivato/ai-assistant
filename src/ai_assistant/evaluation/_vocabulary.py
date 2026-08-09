"""The emitters' literals, restated here because this package may not import them.

ADR-0120 defines every measure over metric keys and seam labels the emitters
already write: ``memory/traces.py``'s retrieval and decision counts,
``Engine._tracked``'s operation seams, and ``service/configuration.py``'s startup
seam. None of those modules is importable from here — ``evaluation`` "may import
``core`` and nothing else in ``ai_assistant``", enforced by ``lint-imports`` — so
the strings are duplicated, in the shape ``memory/traces.py`` already duplicates
:data:`~ai_assistant.memory.traces.TRACE_NOT_RECORDED` from this package and for
the same reason.

**The duplication is checked rather than trusted.** ``tests/evaluation`` asserts
each constant here against the emitting module's own constant, so a rename on
either side fails the gate instead of silently emptying a population. That test
may import both, because a test is not a subsystem.

**A seam this file does not name is not defaulted into a measure** (ADR-0120 §3).
The two seam sets below are allowlists: a write attributed to a seam on neither
is *unclassified*, counted, and named in the report. "Defaulting an unrecognised
seam into either list would silently absorb a new writer into a measure, which is
how a measure starts meaning something different without anybody deciding it
should."
"""

from __future__ import annotations

from typing import Final

# --- retrieval metric keys (`memory/traces.py`) -------------------------------

#: The ``limit`` the caller asked for.
LIMIT: Final = "limit"

#: The ceiling the KNN was asked for, after the over-fetch multiplier and clamp.
FETCH_K: Final = "fetch_k"

#: The pre-filter candidate count the store fetched.
CANDIDATES: Final = "candidates"

#: How many records the read returned.
RETURNED: Final = "returned"

#: Candidates dropped because their ``kind`` was not among those asked for.
EXCLUDED_KIND: Final = "excluded_kind"

#: Candidates dropped by ADR-0007's ``expires_at``.
EXCLUDED_RETENTION: Final = "excluded_retention"

#: Candidates dropped by ADR-0045 §6's validity window — the one #824 watches.
EXCLUDED_WINDOW: Final = "excluded_window"

#: Candidates dropped by the belief-band predicate. A structural zero under
#: ADR-0113 §2 and read here only because ADR-0120 §2's partition test sums it.
EXCLUDED_BAND: Final = "excluded_band"

#: The four exclusion counters, in the order the partition test sums them.
EXCLUSION_KEYS: Final = (EXCLUDED_KIND, EXCLUDED_RETENTION, EXCLUDED_WINDOW, EXCLUDED_BAND)

#: The eight counts ADR-0120 §7's shortfall watch reads, and the set §2's
#: counter-consistency rule is stated over.
RETRIEVAL_COUNT_KEYS: Final = (LIMIT, FETCH_K, CANDIDATES, RETURNED, *EXCLUSION_KEYS)

# --- write metric keys (`memory/traces.py`) -----------------------------------

#: One key per ``MemoryDecisionKind``. ADR-0120 §2 makes **all six** the
#: eligibility test for a ruling population and a strict, non-empty subset
#: *malformed*, so the tuple is read as a unit and never member by member.
DECISION_KEYS: Final = (
    "decisions_accept",
    "decisions_reject",
    "decisions_reinforce",
    "decisions_supersede",
    "decisions_ask_user",
    "decisions_store_temporary",
)

#: The correction: "a user assertion retires" an attested belief (ADR-0092).
DECISIONS_SUPERSEDE: Final = "decisions_supersede"

#: The agreement: "the incoming record agrees with the target and strengthens it".
DECISIONS_REINFORCE: Final = "decisions_reinforce"

#: Every key ADR-0120 §2 reads as a count, and so constrains to a non-negative
#: integer that is not a ``bool``. A trace carrying any of these as anything else
#: is malformed and enters no population.
COUNT_KEYS: Final = (*DECISION_KEYS, *RETRIEVAL_COUNT_KEYS)

# --- operation seams (`Engine._tracked`) --------------------------------------

#: ADR-0120 §3's **user** set: the operations whose writes originate with the
#: user. ``observe`` is here because "the content originates with the user even
#: though the proposal is the model's" — a supersession reached that way is the
#: user correcting the system through the only route the system offers.
USER_SEAMS: Final = frozenset({"converse", "resume", "observe", "learn", "answer"})

#: ADR-0120 §3's **machine** set: the operations that write on their own
#: initiative. Keeping these out of §4's and §5's numerators is what lets #829's
#: arming of consolidation move a diagnostic instead of a measure.
MACHINE_SEAMS: Final = frozenset({"ingest", "consolidate", "purge_expired", "start"})

#: ADR-0120 §3's **direct** set, a subset of the user set: a user act the user
#: performed, rather than one the observation stage mined out of a conversation.
DIRECT_SEAMS: Final = frozenset({"learn", "answer"})

#: The observation stage, whose reinforcements ADR-0120 §6 excludes from the
#: repeated-explanation rate and reports apart: "successive observation batches
#: overlap by design, so their reinforcements are dominated by the stage
#: re-reading the same episodes".
OBSERVE_SEAM: Final = "observe"

__all__ = [
    "CANDIDATES",
    "COUNT_KEYS",
    "DECISIONS_REINFORCE",
    "DECISIONS_SUPERSEDE",
    "DECISION_KEYS",
    "DIRECT_SEAMS",
    "EXCLUDED_BAND",
    "EXCLUDED_KIND",
    "EXCLUDED_RETENTION",
    "EXCLUDED_WINDOW",
    "EXCLUSION_KEYS",
    "FETCH_K",
    "LIMIT",
    "MACHINE_SEAMS",
    "OBSERVE_SEAM",
    "RETRIEVAL_COUNT_KEYS",
    "RETURNED",
    "USER_SEAMS",
]
