"""Learning: converts feedback into memory-update proposals over time.

Observes explicit (and, later, implicit) feedback and turns it into
:class:`~ai_assistant.core.types.MemoryUpdateProposal`s, so personalization
improves with use. It *proposes* only — the pipeline feeds the proposals to the
memory write-path, which disposes of them via the policy (ADR-0009). No
subsystem here writes memory directly.

The public contract is the ``FeedbackProcessor`` Protocol in
`ai_assistant.core.protocols`; ``RuleBasedFeedbackProcessor`` is the first,
deterministic implementation.
"""

from ai_assistant.learning.processor import RuleBasedFeedbackProcessor

__all__ = ["RuleBasedFeedbackProcessor"]
