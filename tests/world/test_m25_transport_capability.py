"""Milestone 25's exit arm: a tool handed no route has none (ADR-0191 §9, #1427).

One arm, one composition, one fake, four instruments — and every instrument
calibrated in the composition the zero was measured in. :mod:`m25_harness` is the
world; this module is the measurement and the figures it reports.

**Five instruments, five controls.** The fake, the loop creators, the probe's
execution marker, the probe's route detector and the survey over what every
registered tool can reach — each with a positive control in the composition its
zero was read in, which is ADR-0191 §9's general clause rather than five separate
rules.

**Read what the arm claims and not one word more.** Its subject is the *handout*:
an undesignated tool was handed no capability, so it had none to reach. Nothing
here says such a tool could not have opened a connection by another route, and
ADR-0191 §7's third clause forbids reading it that way — a raw ``socket``, and
``loop.sock_connect`` over one, are below every creator this arm wraps and stay the
nets' ground.
"""

from __future__ import annotations

import asyncio
import warnings
from typing import TYPE_CHECKING

import m25_harness as m25

from ai_assistant.core.types import ToolFailureKind, ToolOutcome, TransportEndpoint
from ai_assistant.testing import FakeOutboundTransport, TransportAttempt
from ai_assistant.tools.send_email import SEND_EMAIL

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.protocols import OutboundTransport

#: The endpoint the deployment configured, as the capability sees it once the seam
#: has parsed the text the registration carries.
CONFIGURED: TransportEndpoint = TransportEndpoint(host=m25.HOST, port=m25.PORT, implicit_tls=True)


async def test_the_exit_arm_an_undesignated_tool_has_no_route(tmp_path: Path) -> None:
    """The milestone-25 exit, in one arm over one composition (ADR-0191 §9).

    The order is the argument. The loop instruments are installed **before** the
    composition is built, so the build itself is inside what they measure; each is
    calibrated on the active loop and reset, so a zero read afterwards is a zero
    from an instrument that has been seen to fire; the handout is read out of the
    composition by identity rather than assumed; the probe is driven and its own
    execution marker is asserted before its zero is accepted; and the fake's
    positive control comes last, so nothing before it could have been the thing
    that made the fake move.

    Every assertion below reads a record one of this arm's own instruments made.
    None of them is a source scan, an import-graph check or a text search — which
    is what #1427 means by "the fake transport, not a grep", and what
    ``tests/tools/test_egress_seam.py`` deliberately is instead.
    """
    creators = m25.LoopCreators()
    try:
        # 1. Calibrate **each** instrument. A calibration of one creator says
        #    nothing about another creator's wrapper (ADR-0191 §9), so the arm
        #    asserts the set it demonstrated rather than a boolean.
        assert await creators.calibrate() == sorted(m25.OFF_DEVICE_CREATORS)
        assert creators.calls == []

        # The connected account, minted by the shipped provisioning act through
        # the objects the composition root wires (ADR-0151 §5). It runs first
        # because a reference cannot be named in configuration before the act that
        # mints it has run, and it leaves the credential where the *measured*
        # deployment's own keyring face will read it.
        backing = m25.Backing()
        reference = await m25.provision(tmp_path, backing)

        capability = FakeOutboundTransport().serve(m25.channel())
        composition = m25.build(
            tmp_path, capability=capability, connection=reference, backing=backing
        )
        try:
            # 2. The handout, established rather than assumed: the transport the
            #    production root gave the designated seam **is** this fake, and it
            #    is the only one in the composition.
            assert m25.the_capability_the_root_handed_out(composition) is capability
            assert m25.every_tool_that_can_reach_a_transport(composition) == {
                SEND_EMAIL.id: capability
            }
            assert list(capability.attempts) == []

            # 3. The negative arm. The probe is a registered, selected, invoked
            #    tool that reaches for a route at the world and finds none.
            probe = m25.UndesignatedProbe(route=None)
            m25.register_probe(composition, probe)
            result = await m25.drive_the_probe(composition)

            # The execution marker, read **before** the zero is accepted: a probe
            # that was never registered, was not selected, or was reduced to a
            # no-op records zero for a reason that is not the property.
            assert probe.reached_for_a_route is True
            assert probe.route is None
            # Read off the composition rather than off the probe's own report:
            # the probe is registered here, and what the survey says is that
            # nothing it holds reaches a transport. Adversarial review pressed
            # twice on the probe reporting its own zero, which is right — a
            # self-report is an arrangement, and this is a reading.
            reaching = m25.every_tool_that_can_reach_a_transport(composition)

            assert reaching == {SEND_EMAIL.id: capability}
            assert result.outcome is ToolOutcome.FAILED
            assert result.failure is not None
            assert result.failure.kind is ToolFailureKind.INTERNAL

            # The two zeros, from two instruments that have each been seen to
            # fire. Snapshotted, because the two controls below deliberately move
            # the fake and this is the reading the exit is stated over.
            undesignated = list(capability.attempts)

            assert undesignated == []
            assert creators.calls == []

            # 4. The positive control for the fake, over the same fake in the
            #    same composition and through that composition's **own**
            #    registered seam. Without it the zero above is satisfied by a
            #    recorder nothing could ever reach.
            await m25.drive_a_bound_call(composition, reference)

            assert list(capability.attempts) == [TransportAttempt(endpoint=CONFIGURED, served=True)]
            # The control moves the connection instrument by nothing, because the
            # fake opens nothing — which is what makes the two records independent.
            assert creators.calls == []

            # 5. The positive control for the **probe**, and it comes last for the
            #    same reason the fake's does. The identical callable, registered
            #    under its own id in this same composition and driven through the
            #    same invocation seam — but handed the capability. It finds a
            #    route and reaches an endpoint of its own choosing with it, so the
            #    zero at step 3 is a zero from a detector that has been seen to
            #    fire rather than one that could never have fired. Adversarial
            #    review found the uncontrolled detector on round 6.
            armed = m25.UndesignatedProbe(route=capability)
            m25.register_probe(composition, armed, m25.ARMED_PROBE)
            control = await m25.drive_the_probe(composition, m25.ARMED_PROBE)

            # ...and the survey instrument's own positive control: a second
            # registered tool holding a transport is exactly the regression it
            # exists to catch, so it must see this one.
            assert m25.every_tool_that_can_reach_a_transport(composition) == {
                SEND_EMAIL.id: capability,
                m25.ARMED_PROBE.id: capability,
            }
            assert armed.reached_for_a_route is True
            assert armed.route is capability
            assert armed.opened == m25.PROBE_ENDPOINT
            assert control.outcome is ToolOutcome.SUCCEEDED
            assert list(capability.attempts) == [
                TransportAttempt(endpoint=CONFIGURED, served=True),
                TransportAttempt(endpoint=m25.PROBE_ENDPOINT, served=True),
            ]
            assert creators.calls == []
        finally:
            await composition.engine.aclose()
    finally:
        creators.remove()

    _report(
        probe=probe,
        armed=armed,
        reaching=reaching,
        undesignated=undesignated,
        creators=creators,
    )


async def test_every_creator_the_running_loop_exposes_is_classified() -> None:
    """Naming one creator does not discharge §9's clause, so none is left unnamed.

    ADR-0191 §9 requires **every** creator the running loop exposes that can reach
    off the device, "at minimum ``create_connection`` and ``create_datagram_endpoint``".
    A hand-written pair would silently stop being every one of them the day the
    standard library grew a third, so the partition is asserted against the live
    loop instead: a creator this module has not sorted into one of the four sets
    fails the gate rather than escaping the arm.

    The exclusions are ADR-0191's own and not this arm's convenience. A Unix domain
    socket does not leave the device (ADR-0084 §1), so it is not ADR-0017 §1's
    subject and §5's exclusion of local IPC governs; a server creator accepts an
    inbound connection rather than reaching for one, which is §5's structural
    reason for leaving ADR-0124's and ADR-0174's listener halves out; and a future
    or a task makes no socket at all.
    """
    loop = asyncio.get_running_loop()
    exposed = {name for name in dir(loop) if name.startswith("create_")}
    classified = (
        m25.OFF_DEVICE_CREATORS | m25.ON_DEVICE_CREATORS | m25.INBOUND_CREATORS | m25.LOCAL_CREATORS
    )

    assert exposed >= m25.OFF_DEVICE_CREATORS
    assert exposed - classified == set(), (
        f"{sorted(exposed - classified)} are creators on the running loop that this "
        f"arm has not classified. ADR-0191 §9 wants every one that can reach off "
        f"the device instrumented; decide which set each belongs to."
    )


async def test_a_deployment_that_configures_no_integration_registers_no_egress_tool(
    tmp_path: Path,
) -> None:
    """§3: an unconfigured deployment registers no tool that could reach the world.

    **Read through the registry, which is the surface a plan actually reaches**,
    and claiming no more than that. An earlier draft of this case also asserted the
    fake's empty attempt list and a zero from the loop instruments, which
    adversarial review pointed out establish nothing here: a regression that
    constructed a transport and handed it to something inert leaves all three
    readings unchanged. What *does* measure the construction is a direct instrument
    on the composition root, and it lives beside the root it instruments —
    ``tests/app/test_composition.py``'s
    ``test_a_deployment_with_no_integration_constructs_no_transport``.
    """
    composition = m25.build(tmp_path, capability=FakeOutboundTransport())
    try:
        assert await m25.registry(composition).get("send_email") is None
    finally:
        await composition.engine.aclose()


def _report(
    *,
    probe: m25.UndesignatedProbe,
    armed: m25.UndesignatedProbe,
    reaching: dict[str, OutboundTransport],
    undesignated: list[TransportAttempt],
    creators: m25.LoopCreators,
) -> None:
    """Report the arm's figures the way milestones 23 and 24 report theirs.

    A milestone arm that only passes tells the operator ruling its exit nothing
    about *what* was measured, so the figures are emitted with their denominators
    and their must-be-zero conditions.

    Args:
        probe: The undesignated probe, for its execution marker.
        armed: The same probe handed the capability, for the detector's control.
        reaching: Which registered tools could reach a transport at the moment the
            probe had run, which is the survey's reading of the handout.
        undesignated: The fake's attempt record **as it stood** when the probe had
            run and before either control was driven, which is the reading the
            exit is stated over.
        creators: The loop instruments, for what they saw.
    """
    warnings.warn(
        "\n\nmilestone 25 — the transport capability's exit (ADR-0191 §9, #1427)\n"
        f"  probe execution marker    {int(probe.reached_for_a_route)} of 1  "
        "the undesignated tool ran as far as acquiring a route; must be one\n"
        f"  routes found by the probe {int(probe.route is not None)} of 1  "
        "capabilities it could obtain having been handed none; must be zero\n"
        f"  undesignated attempts     {len(undesignated)} of 1  attempts the "
        "probe put on the fake having been handed no route; must be zero\n"
        f"  detector control          {int(armed.opened is not None)} of 1  "
        "endpoints the same probe reached once handed one; must be one\n"
        f"  tools reaching a route    {len(reaching)}  registered tools that can "
        f"reach a transport ({', '.join(sorted(reaching))}); must be the "
        "designated seam alone\n"
        f"  loop creator calls        {len(creators.calls)} of "
        f"{len(m25.OFF_DEVICE_CREATORS)}  off-device creators called outside the "
        "calibration; must be zero\n"
        "  positive control          1 of 1  attempts the seam's bound call put "
        "on the fake; must be one\n",
        stacklevel=2,
    )
