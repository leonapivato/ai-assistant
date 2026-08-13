"""The emitters' literals, restated here because this package may not import them.

ADR-0120 defines every measure over metric keys and seam labels the emitters
already write: ``memory/traces.py``'s retrieval and decision counts,
``Engine._tracked``'s operation seams, and ``service/configuration.py``'s startup
seam. ADR-0141 adds a fourth to that list, ``memory/notification_traces.py``, and
its §10 requires exactly this treatment of it: "``evaluation`` may import only
``core``, so the emitter's keys are duplicated by construction and the test is what
keeps the two copies honest". None of those modules is importable from here —
``evaluation`` "may import ``core`` and nothing else in ``ai_assistant``", enforced
by ``lint-imports`` — so the strings are duplicated, in the shape
``memory/traces.py`` already duplicates
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

from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    DROP_CONDITIONS,
    INTERRUPT_CONDITIONS,
    NotificationCondition,
    NotificationDispositionKind,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

# --- retrieval metric keys (`memory/traces.py`) -------------------------------

#: The ``limit`` the caller asked for.
LIMIT: Final = "limit"

#: The ceiling the KNN was asked for: the caller's ``limit``, clamped to
#: sqlite-vec's own ``k`` ceiling and nothing else. There is no over-fetch
#: multiplier to apply — ADR-0128 §1 binds every eligibility predicate before the
#: ranking cut, so every candidate the KNN returns is already eligible and an
#: over-fetch could buy nothing. This comment described the multiplier for a while
#: after the emitter stopped applying one (#926).
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

#: The eight counts ADR-0120 §2's counter-consistency rule is stated over. They
#: were also what §7's #824 shortfall watch read; ADR-0128 §3 retired that watch
#: and left §2's rule standing unchanged, so the set outlives its second reader.
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
#:
#: **One member per ingestion source, because ADR-0142 §4 gives each source its own
#: operation and therefore its own seam.** Both write on their own initiative
#: exactly as the single ``ingest`` did, so this is that rename's mechanical
#: consequence rather than a re-classification. A seam on neither set is dropped
#: from every measure into ``unclassified`` (:func:`~ai_assistant.evaluation._stream.classify`),
#: which fails safe and fails silently — so a third source's lane owes this set a
#: member, and #1076 records that ADR-0142 §5's own cost measurement does not
#: mention this file.
MACHINE_SEAMS: Final = frozenset(
    {"ingest_calendar", "ingest_email", "consolidate", "purge_expired", "start"}
)

#: ADR-0120 §3's **direct** set, a subset of the user set: a user act the user
#: performed, rather than one the observation stage mined out of a conversation.
DIRECT_SEAMS: Final = frozenset({"learn", "answer"})

#: The observation stage, whose reinforcements ADR-0120 §6 excludes from the
#: repeated-explanation rate and reports apart: "successive observation batches
#: overlap by design, so their reinforcements are dominated by the stage
#: re-reading the same episodes".
OBSERVE_SEAM: Final = "observe"

# --- notification ruling seams and keys (`memory/notification_traces.py`) -----

#: ADR-0141 §3's two ruling seams, ``NotificationStore.admit`` and
#: ``NotificationStore.reconsider`` — "ADR-0130 §3's atomic act, in both the shapes
#: it takes". §5 makes them an allowlist for the same reason ADR-0120 §3 makes the
#: operation seams one: "a later lane may add a third ruling seam, and defaulting
#: an unrecognised one into the offer or the reconsideration population would
#: silently absorb it into a diagnostic. The count that rises is the prompt to
#: classify it."
NOTIFICATION_ADMIT_SEAM: Final = "notification_admit"
NOTIFICATION_RECONSIDER_SEAM: Final = "notification_reconsider"

#: §4's three disposition keys, one per :class:`NotificationDispositionKind`. A
#: completed ruling carries **all three**, each ``0`` or ``1``, "written by one
#: statement so they are observed and lost together" — which is what satisfies
#: ADR-0119 §5's denominator rule without an external count: §6's numerator and its
#: denominator come from one statement, so one loss takes both.
NOTIFICATION_DISPOSITION_KEYS: Final[Mapping[NotificationDispositionKind, str]] = {
    NotificationDispositionKind.INTERRUPT: "ruled_interrupt",
    NotificationDispositionKind.HOLD: "ruled_hold",
    NotificationDispositionKind.DROP: "ruled_drop",
}

#: §4's eight condition keys, one per :class:`NotificationCondition`. Each carries
#: ``1`` when the proposition its member names held at the ruling instant — "the
#: enumeration's own propositions, not their negations", which is why ``EXPIRED``
#: and ``PERISHABLE`` are both ``0`` on a candidate declaring no expiry at all
#: rather than being opposites.
#:
#: Keyed on the enumeration rather than listed as bare strings, because §4 and §5
#: state the roster's **two halves** over ``DROP_CONDITIONS`` and
#: ``INTERRUPT_CONDITIONS`` by name — a drop key is carried by every completed
#: ruling and an interrupt key by every non-``DROP`` one. Deriving the split from
#: ``core``'s own tuples, which this package may import, means it is not a second
#: grouping to keep honest against ADR-0130 §5; only the *strings* are duplicated,
#: which is the whole of what golden rule 1 forces.
NOTIFICATION_CONDITION_KEYS: Final[Mapping[NotificationCondition, str]] = {
    NotificationCondition.EXPIRED: "condition_expired",
    NotificationCondition.REACH_OFF: "condition_reach_off",
    NotificationCondition.DUPLICATE: "condition_duplicate",
    NotificationCondition.AT_CAP: "condition_at_cap",
    NotificationCondition.PERISHABLE: "condition_perishable",
    NotificationCondition.REACH_INTERRUPT: "condition_reach_interrupt",
    NotificationCondition.QUIET_WINDOW: "condition_quiet_window",
    NotificationCondition.BUDGET: "condition_budget",
}

#: The four keys §4 requires on **every** completed ruling, in ADR-0130 §5's order.
DROP_CONDITION_KEYS: Final = tuple(
    NOTIFICATION_CONDITION_KEYS[condition] for condition in DROP_CONDITIONS
)

#: The four keys §4 requires on every ruling that was **not** ``DROP``, and forbids
#: on one that was, in ADR-0130 §5's order.
INTERRUPT_CONDITION_KEYS: Final = tuple(
    NOTIFICATION_CONDITION_KEYS[condition] for condition in INTERRUPT_CONDITIONS
)

#: How long the record had been held when a reconsideration interrupted it (§4).
#: **Not a count**, and §4 says so explicitly: a finite, non-negative ``int`` or
#: ``float`` that is not a ``bool``, where every other key here is a count. So
#: §5's count rule does not reach it and :data:`NOTIFICATION_COUNT_KEYS` excludes it.
HELD_SECONDS: Final = "held_seconds"

#: Every key §4 reads as a **count**: the three disposition keys and the eight
#: condition keys. §5's malformed rule is stated over exactly these — "a key §4
#: reads as a count carries a value that is not a non-negative integer, or is a
#: ``bool``" — and ADR-0120 §2's own count predicate serves both ADRs, "so one
#: predicate serves both".
NOTIFICATION_COUNT_KEYS: Final = (
    *NOTIFICATION_DISPOSITION_KEYS.values(),
    *NOTIFICATION_CONDITION_KEYS.values(),
)

#: **All twelve** keys §4 defines, which is the set §5's *incomplete* state is
#: decided over: a trace carrying none of them "records a crossing that raised
#: before the ruling committed". Defined over the disposition keys alone the state
#: would match more than the path it names — a trace bearing a corrupt condition
#: value and no disposition would be decided there and never reach the tests that
#: would have called it malformed, "so emitter corruption would be reported as an
#: ordinary pre-ruling fault and stream health could not tell an outage from a
#: defect" (§5, seventh round).
NOTIFICATION_METRIC_KEYS: Final = (*NOTIFICATION_COUNT_KEYS, HELD_SECONDS)

__all__ = [
    "CANDIDATES",
    "COUNT_KEYS",
    "DECISIONS_REINFORCE",
    "DECISIONS_SUPERSEDE",
    "DECISION_KEYS",
    "DIRECT_SEAMS",
    "DROP_CONDITION_KEYS",
    "EXCLUDED_BAND",
    "EXCLUDED_KIND",
    "EXCLUDED_RETENTION",
    "EXCLUDED_WINDOW",
    "EXCLUSION_KEYS",
    "FETCH_K",
    "HELD_SECONDS",
    "INTERRUPT_CONDITION_KEYS",
    "LIMIT",
    "MACHINE_SEAMS",
    "NOTIFICATION_ADMIT_SEAM",
    "NOTIFICATION_CONDITION_KEYS",
    "NOTIFICATION_COUNT_KEYS",
    "NOTIFICATION_DISPOSITION_KEYS",
    "NOTIFICATION_METRIC_KEYS",
    "NOTIFICATION_RECONSIDER_SEAM",
    "OBSERVE_SEAM",
    "RETRIEVAL_COUNT_KEYS",
    "RETURNED",
    "USER_SEAMS",
]
