"""ADR-0121 §1's agreement predicate, shared by the policy and the writer.

Two records **agree** when a reader can see that they say the same thing without
any judgement being exercised. ADR-0121 §1 fixes that as a *syntactic* predicate
over the records themselves, so that the policy choosing a ruling and the writer
verifying it compute the same answer from the same inputs — with no store read,
no model call and no scoring.

**The predicate reads ``kind`` and ``content`` and nothing else** (§1). Never a
retrieval score, a ``Provenance`` field, a validity window, a band, an embedding,
or any value obtained from a ``ModelProvider``. That is what makes it able to
license the fold §5 permits: a fold onto a record the user gave us, admitted at
the writer boundary on a determination rather than on a similarity signal.

**The four transformations are exactly the ones that change no word.** They admit
``"I prefer window seats"`` against ``"I prefer  Window Seats"`` and admit nothing
else — not a trailing full stop, not a dropped article, not a synonym. Stemming,
synonym expansion, stop-word removal and every embedding comparison are excluded, and
their exclusion is the point rather than a simplification. Each of them decides
that two *different* strings mean the same thing, which is a judgement, and a
judgement is what this predicate must not contain — the failure mode of a false
agreement is folding a contradiction into the record it contradicts, at that
record's own id.

**Held in `memory` and duplicated into `ai_assistant.testing`, not shared with
it** (§6, golden rule 1). The canonical ``MemoryWriter`` fake may not import this
subsystem, which is why ADR-0121 states the predicate normatively rather than
leaving one implementation to define it.

**Within `memory` it is one module, and that is not a weakening of ADR-0038 §2a.**
What §2a requires is that the safety property be *recomputed at the boundary that
performs the write*, because "a policy reaches ``MemoryIngestor`` through an
injected seam" and an arbitrary conforming policy may not have computed it at all.
``MemoryIngestor`` does recompute it, over the target it holds and the proposal it
was given, and refuses when it does not hold whatever the ruling says (ADR-0121
§5). Two *copies* of the predicate would add nothing to that and would add a way
for the two to disagree — which for this predicate is the one failure §1 forbids.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_assistant.core.types import MemoryRecord


def normalised(content: str) -> str:
    """Apply ADR-0121 §1's four transformations to ``content``, in order.

    Unicode NFC normalisation, Unicode case folding, replacement of every maximal
    run of Unicode whitespace by a single space, and removal of leading and
    trailing whitespace. ``str.split()`` with no argument performs the last two
    together and does so over *Unicode* whitespace, which is what the clause says;
    a ``" "``-keyed split or a ``strip()`` over ASCII would leave a no-break space
    or an ideographic space deciding that two identical sentences differ.

    **No transformation is applied that the clause does not name**, and in
    particular the result is not re-normalised after case folding. Case folding
    can leave a string outside NFC, and re-normalising would be a fifth
    transformation this repository would then have to justify; the clause fixes
    the order and stops.

    Args:
        content: A record's ``content`` string.

    Returns:
        The comparison form. Meaningful only against another string put through
        this same function — it is not a canonical rendering and nothing stores it.
    """
    return " ".join(unicodedata.normalize("NFC", content).casefold().split())


def agrees(left: MemoryRecord, right: MemoryRecord) -> bool:
    """Whether ``left`` and ``right`` agree under ADR-0121 §1.

    Equality of ``kind`` and of ``content`` under :func:`normalised`. ``kind`` is
    compared as the discriminator the records carry rather than through
    :class:`~ai_assistant.core.types.MemoryKind`, because the clause is stated over
    the records' own values and a round-trip through the enum would add a failure
    mode (an unmappable value) to a predicate whose whole worth is that it cannot
    fail to decide.

    **Symmetric and total.** Nothing here reads which record is the target and
    which the proposal, so the policy's call and the writer's call cannot disagree
    by arguing them in a different order.

    Args:
        left: One record.
        right: The other.

    Returns:
        Whether a reader can see that the two say the same thing, without any
        judgement being exercised.
    """
    return left.kind == right.kind and normalised(left.content) == normalised(right.content)
