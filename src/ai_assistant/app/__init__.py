"""The composition root: the one place concrete subsystems are wired (ADR-0042 §2).

This package is the classic composition root — the single layer, at the
application's entry point, licensed to import the concrete subsystem
implementations, name them, and assemble them into a ready
:class:`~ai_assistant.orchestration.Engine` façade. Every other layer depends on
contracts; only here are ``SqliteMemoryStore``, ``ModelBackedPlanner``,
``ThresholdActionPolicy`` and the rest constructed.

It exists as its own package because **both** natural homes are barred (ADR-0042
§2): ``orchestration`` may import no concrete subsystem (ADR-0022 §1), and an
``interfaces`` adapter must depend only on contracts (ADR-0007). Being a distinct
package is also what lets the ``interfaces``-may-not-import-subsystems guard be
well-formed (ADR-0042 §6).

Because it imports concrete subsystems, this package joins the source lists of the
existing ``lint-imports`` contracts — provider SDKs confined to ``models``, testing
doubles confined to tests — so it gains no licence those forbid (ADR-0042
§Consequences).

The entry point is :func:`build_engine`. :func:`ensure_model_credentials` sits
beside it for the one caller that needs a startup answer ``build_engine``
deliberately does not give (issue #530, ADR-0083 §3).
"""

from __future__ import annotations

from ai_assistant.app.composition import build_engine, ensure_model_credentials

__all__ = ["build_engine", "ensure_model_credentials"]
