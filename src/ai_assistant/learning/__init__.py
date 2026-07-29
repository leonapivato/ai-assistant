"""Learning: converts feedback into memory-update proposals over time.

Observes explicit (and, later, implicit) feedback and turns it into
:class:`~ai_assistant.core.types.MemoryUpdateProposal`s, so personalization
improves with use. It *proposes* only — the pipeline feeds the proposals to the
memory write-path, which disposes of them via the policy (ADR-0009). No
subsystem here writes memory directly.

The public contracts are the ``FeedbackProcessor`` and ``Observer`` Protocols in
`ai_assistant.core.protocols`. ``RuleBasedFeedbackProcessor`` turns explicit,
user-stated feedback into proposals; ``ModelBackedObserver`` (ADR-0077) does the
same job from the other direction, distilling beliefs out of episodes the user
never commented on — which is what makes accumulation passive rather than
dictated. Neither writes memory: both propose, and a deterministic policy
disposes.
"""

from ai_assistant.learning.observer import (
    DEFAULT_OBSERVATION_BATCH_SIZE,
    DEFAULT_OBSERVATION_MAX_PROPOSALS,
    ModelBackedObserver,
)
from ai_assistant.learning.processor import RuleBasedFeedbackProcessor

__all__ = [
    "DEFAULT_OBSERVATION_BATCH_SIZE",
    "DEFAULT_OBSERVATION_MAX_PROPOSALS",
    "ModelBackedObserver",
    "RuleBasedFeedbackProcessor",
]
