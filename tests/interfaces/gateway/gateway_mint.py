"""Performing the gateway's mint act in a test, and reading what it disclosed.

A plain module beside ``gateway_timing`` and for the same reason: ``mypy`` refuses
a second ``conftest.py`` where the test tree carries no packages.

**Every mint goes through here rather than through a call each case writes**,
because ADR-0182 §1 makes the mint an *ordered* act — mint a candidate, disclose
it, and only on a successful disclosure promote it — and a case that wanted only a
value would otherwise be free to skip the disclosure and hold a candidate that
admits nothing. Passing a discloser is what makes each of those cases exercise the
order the ADR fixes; the cases that are *about* the order pass their own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.interfaces.gateway.server import MintAct

if TYPE_CHECKING:
    from ai_assistant.interfaces.gateway.server import Disclosure, Gateway

#: A mint act for a case that is not about how the disposition was installed.
#: A fixed process id rather than this one's: nothing here signals anything, and a
#: reading of ``os.getpid`` would be one more thing a failure could be about.
ACT = MintAct(signal="SIGUSR1", pid=4242)


def mint_bootstrap(gateway: Gateway, *, act: MintAct | None = ACT) -> Disclosure:
    """Perform one mint act and return what it disclosed.

    Args:
        gateway: The gateway to mint at.
        act: The act to name in the disclosure, or ``None`` for a gateway that
            could not install one (ADR-0182 §1).

    Returns:
        The disclosure that promoted the value.
    """
    disclosed: list[Disclosure] = []
    gateway.mint_bootstrap(disclosed.append, act=act)
    return disclosed[-1]


def bootstrap_value(gateway: Gateway) -> str:
    """The value one mint act disclosed, for a case that needs only that."""
    return mint_bootstrap(gateway).value
