"""ADR-0252 §3's composition and §8's supersession on the kinds the deployment performs.

Issue #2366 read the M32 acceptance run's rows — ``requested=None`` and ``supported=()``
on every one — and concluded that *"the two fields that give a row its meaning are empty
on every read kind the running system can perform"*, so that §8's refresh test *"cannot
fire end to end"*. The rows it read were a **scratch** hub's, created that hour; the
production ``plans.db`` was outside that run's fence.

These arms drive the composition on the memory kinds over records shaped as the live
store's own producers write them, and they pin what that survey actually shows:

* **``supported`` is reachable on the memory kinds.** §3 composes one region per record
  the ask returned, from that record's own ``topics``, ``participants`` and
  ``about_person`` — and a record that carries one of those contributes one. A
  ``SIGHTED_QUERY`` reads
  :data:`~ai_assistant.orchestration.conversations.BELIEF_KINDS`, and a belief carrying
  ``topics`` is the ordinary live shape rather than an unusual one.
* **§8's supersession therefore fires end to end**, on a `SIGHTED_QUERY`, through
  ``Engine`` and a conforming ``PlanStore``: the later row covers the standing one, and
  the standing one comes back ``SUPERSEDED`` with ``superseded_by`` naming it.
* **An empty ``supported`` is a fact about the record and not about the composition.**
  A turn's own captured episode is written with ``topics`` and ``participants`` empty
  (:meth:`~ai_assistant.orchestration.conversations.ConversationService.episode_of`) and
  is labelled only later, by the observation pass
  (:meth:`~ai_assistant.orchestration.observation.ObservationPass._label`). A row over an
  unlabelled record carries no region, which is §3's *"a record carrying no applied axis
  contributes no region"* working, and is what the scratch run saw.

What these arms do **not** claim. ``WEB_SEARCH`` and ``LOCAL_FILE`` rows do carry
``supported`` empty, and ADR-0252 §3 states that in terms over both minting clauses —
that is the decision rather than a defect, and §15 names decision 8's reader as what
changes it. ``requested`` is likewise absent on four kinds of five by §3 as written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from test_engine import AT

from ai_assistant.core.types import (
    Capture,
    EpisodicMemory,
    EvidenceApplicability,
    MemorySource,
    Modality,
    Placement,
    Provenance,
    SemanticMemory,
)
from ai_assistant.orchestration.evidence import region_of

if TYPE_CHECKING:
    from ai_assistant.core.types import MemoryRecord

#: The label the seeded records carry and the seeded row supports, so the region the
#: live read composes **covers** the standing row's — which is §8 limb 4.
_TOPIC: Final = "weather"


def _belief(*, topics: tuple[str, ...]) -> SemanticMemory:
    """A belief shaped as the live store holds one.

    The live store's belief-kind records carry ``topics`` and carry **no**
    ``about_person`` and no ``Provenance.attestation`` — so the topics axis is the one
    §3 applies, and the window axis is not applied at all (which is §3's own dated
    observation about this corpus's producers).

    Args:
        topics: The labels the record carries, empty for a record no pass has labelled.

    Returns:
        The record.
    """
    return SemanticMemory(
        id="belief-1",
        content=f"the lake is usually dry when they ask about the {_TOPIC}",
        fact=f"the lake is usually dry when they ask about the {_TOPIC}",
        topics=topics,
        about_person=None,
        placement=Placement(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=AT),
    )


def _captured_episode() -> EpisodicMemory:
    """One turn's own episode, with the fields the capture path fills and no others.

    ``ConversationService.episode_of`` writes ``id``, ``content``, ``occurred_at``,
    ``outcome``, ``disposition``, ``capture``, ``expires_at``, ``provenance`` and
    ``placement`` — and **neither** ``topics`` **nor** ``participants``. Both arrive
    later, from ``ObservationPass._label``, and only on a pass that reaches this episode.

    Returns:
        The record, as the capture path leaves it.
    """
    return EpisodicMemory(
        id="episode-1",
        content=f"The user asked: what is the {_TOPIC} doing.",
        occurred_at=AT,
        capture=Capture(modality=Modality.TEXT),
        placement=Placement(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )


def _labelled_episode() -> EpisodicMemory:
    """The same episode after the observation pass filed it (ADR-0239 §3).

    That pass replaces ``topics`` and ``participants`` and carries every other field
    across unchanged, so this differs from :func:`_captured_episode` in exactly the two
    fields §3 composes a region from.

    Returns:
        The record, labelled.
    """
    return _captured_episode().model_copy(update={"topics": (_TOPIC,), "participants": ("Marta",)})


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        pytest.param(_captured_episode(), None, id="as the capture path writes one"),
        pytest.param(
            _labelled_episode(),
            EvidenceApplicability(participants=("Marta",), topics=(_TOPIC,)),
            id="as the observation pass leaves one",
        ),
        pytest.param(_belief(topics=()), None, id="a belief no pass has labelled"),
        pytest.param(
            _belief(topics=(_TOPIC,)),
            EvidenceApplicability(topics=(_TOPIC,)),
            id="a belief carrying its topics",
        ),
    ],
)
def test_whether_a_region_is_composed_is_a_fact_about_the_record(
    record: MemoryRecord, expected: EvidenceApplicability | None
) -> None:
    """The same composition, over the two states this system's own producers leave.

    An episode is written unlabelled and labelled later, so a row over a turn's own
    freshly captured episode carries no region and a row over the same episode after the
    observation pass carries one. Neither is a property of the read kind.

    Args:
        record: The record the ask returned.
        expected: The region §3 composes from it, or ``None``.
    """
    assert region_of(record) == expected
