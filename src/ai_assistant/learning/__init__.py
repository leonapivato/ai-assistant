"""Learning: how what the user says about memory reaches it.

The package holds no code. Its first processor, ``RuleBasedFeedbackProcessor``,
retired under ADR-0328 §14:1, together with the ``FeedbackProcessor`` Protocol, its
canonical fake and conformance suite, and the ``FeedbackEvent`` and ``FeedbackKind``
types it consumed: feedback is interpreted by models and never mechanically, and how
it reaches memory is the observer's decision's. Where that observer lives is
ADR-0329's to decide, so the package is kept rather than removed until it does.

Whatever lands here *proposes* only: the memory write path disposes of a proposal
through the policy, and nothing in this package writes memory directly (ADR-0005 §3).
"""
