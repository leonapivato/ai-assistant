"""Learning: captures feedback and updates the user model over time.

Observes interactions and explicit/implicit feedback, then writes durable
updates back into `memory` so personalization improves with use. Owns the
feedback loop; it reads outcomes and proposes memory writes, gated by
`permissions`.

Contract: TBD (added here as this subsystem is designed).
"""
