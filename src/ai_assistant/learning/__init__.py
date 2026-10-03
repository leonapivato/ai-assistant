"""Learning: converts feedback into memory-update proposals over time.

Observes explicit (and, later, implicit) feedback and turns it into
:class:`~ai_assistant.core.types.MemoryUpdateProposal`s, so personalization
improves with use. It *proposes* only — the pipeline feeds the proposals to the
memory write-path, which disposes of them via the policy (ADR-0009). No
subsystem here writes memory directly.

The public contract is the ``FeedbackProcessor`` Protocol in
`ai_assistant.core.protocols`. ``RuleBasedFeedbackProcessor`` turns explicit,
user-stated feedback into proposals, and writes nothing: it proposes, and a
deterministic policy disposes. Nothing here distils beliefs out of episodes.
ADR-0285 retired the observer that did, and adds no producer in its place.
"""

from ai_assistant.learning.processor import RuleBasedFeedbackProcessor

__all__ = [
    "RuleBasedFeedbackProcessor",
]
