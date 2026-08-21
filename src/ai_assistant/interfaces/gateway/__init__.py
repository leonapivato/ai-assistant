"""The browser gateway — a second interface adapter (ADR-0168, ADR-0172).

It lives in ``interfaces`` because that is what ADR-0168 §1 rules it is: "a
gateway is an interface adapter, its code belongs in `interfaces` on golden rule
3's own terms", reached by "a subcommand of the existing `assistant` console
script, not a new one". That is the first time ADR-0084 §6's own-console-script
rule has been examined and found not to fire — the rule is about where code must
live, and a gateway has no reason to import ``service``.
"""

from __future__ import annotations

from ai_assistant.interfaces.gateway.server import Gateway, packaged_bundle, run_gateway

__all__ = ["Gateway", "packaged_bundle", "run_gateway"]
