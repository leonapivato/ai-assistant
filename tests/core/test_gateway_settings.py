"""ADR-0168 §8's ten figures, two later ones, and ADR-0174 §8's three fields.

The generic guards in ``test_config.py`` already hold every one of these to "a
flag is not a count", "a flag is not a duration" and its own default; what is
here is the part those cannot reach — each field's own range, and the two
cross-field refusals §8 states.

**The block is now twelve figures and the count tripwire says which ADR bought
which.** ADR-0168 §8 named ten and ADR-0172's opening bullet "adds no eleventh";
ADR-0175 §8 is the decision that does, on §8's own ground — "a 'bounded default'
with no figure is two conforming stores handing the same continuation different
history". ADR-0182 §3 buys the twelfth on the same ground, for a bound #1329 found
had no figure at all. A thirteenth is still a figure no ADR names.

**§8's table is not an exclusive enumeration, which is why the twelfth owes it no
supersession.** ADR-0182 §9 works that through: the table "carries no clause saying
the gateway has these fields and no others", and "the corpus has already settled
this in practice twice without a record" — ADR-0174 §8's three fields and ADR-0175
§8's one.

**ADR-0174 §8's three are held apart, because none of them is a figure.** "Three
fields are the whole of what this boundary adds and none of them is a budget: one
is the switch and two are lists the owner writes, because §8 above spends no new
budget — it shares the ones that exist." That separation is what keeps
:func:`test_no_gateway_figure_is_nullable` honest: ``gateway_remote_address`` *is*
nullable, "because it is the switch", and ADR-0168 §8's no-nullable rule "is stated
over the ten fields in that ADR's own table and is untouched".
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings

_GATEWAY_FIELDS = (
    "gateway_port",
    "gateway_session_ttl",
    "gateway_session_idle_timeout",
    "gateway_max_sessions",
    "gateway_max_hub_connections",
    "gateway_max_request_bytes",
    "gateway_record_interval",
    "gateway_read_timeout",
    "gateway_max_browser_connections",
    "gateway_max_pending_connections",
    # ADR-0175 §8's one figure, added to this tuple rather than exempted from it:
    # joining it is what subjects the field to every guard below, and §8 states its
    # range in ADR-0168 §8's own terms — "refused at settings load unless it is
    # strictly positive… not nullable and takes no value meaning 'off'".
    "gateway_notification_budget",
    # ADR-0182 §3's one figure, joined here for the reason ADR-0175 §8's was: §3
    # states its range in ADR-0168 §8's own terms — "refused at settings load unless
    # it is strictly positive, in the ``gt=timedelta(0)`` form… not nullable and
    # takes no value meaning 'off'" — and joining this tuple is what subjects it to
    # every guard below.
    "gateway_bootstrap_ttl",
)

#: ADR-0174 §8's table, which is three fields and no figure: one switch and two
#: lists the owner writes. Held apart from ``_GATEWAY_FIELDS`` above rather than
#: joined to it, because the guards there are ADR-0168 §8's rules about *figures*
#: and none of these three is one.
_REMOTE_BROWSER_FIELDS = (
    "gateway_remote_address",
    "gateway_remote_browser_devices",
    "gateway_remote_host_names",
)


def test_the_figures_are_all_present_with_their_adrs_defaults() -> None:
    """§8's table, transcribed. A default that drifts is two gateways disagreeing."""
    settings = Settings()

    assert settings.gateway_port == 8422
    assert settings.gateway_session_ttl == timedelta(hours=12)
    assert settings.gateway_session_idle_timeout == timedelta(hours=1)
    assert settings.gateway_max_sessions == 8
    assert settings.gateway_max_hub_connections == 8
    assert settings.gateway_max_request_bytes == 1024 * 1024
    assert settings.gateway_record_interval == timedelta(minutes=1)
    assert settings.gateway_read_timeout == timedelta(seconds=30)
    assert settings.gateway_max_browser_connections == 64
    assert settings.gateway_max_pending_connections == 8
    assert settings.gateway_notification_budget == timedelta(seconds=20)
    assert settings.gateway_bootstrap_ttl == timedelta(minutes=10)


def test_the_figures_are_exactly_the_ones_an_adr_names() -> None:
    """A tripwire on the *count*: a `gateway_*` field no ADR names is the
    underdetermination ADR-0168 §8 opens by refusing.

    Ten figures from ADR-0168 §8, none from ADR-0172 ("adds no eleventh"), the
    eleventh from ADR-0175 §8, the twelfth from ADR-0182 §3, and ADR-0174 §8's
    three non-figures. Discovering a sixteenth here is cheaper than in review.
    """
    named = {name for name in Settings.model_fields if name.startswith("gateway_")}

    assert named == set(_GATEWAY_FIELDS) | set(_REMOTE_BROWSER_FIELDS)


def test_the_notification_budget_is_far_below_the_hubs_own_ceiling() -> None:
    """ADR-0175 §8: "deliberately far below the hub's own ceiling, and the
    cross-process refusal is why".

    ``hub_max_notification_budget`` is another process's setting and may be another
    machine's, so neither ``Settings`` can validate against the other and §8 forbids
    a load-time check relating them. What replaces the check is a default an order
    of magnitude below, which leaves an owner who tunes one figure a wide margin
    before they meet the other — and meeting it is legible rather than silent.
    """
    settings = Settings()

    assert settings.gateway_notification_budget * 10 <= settings.hub_max_notification_budget


def test_a_notification_budget_above_the_hubs_ceiling_still_loads() -> None:
    """§8: "No load-time check relates it to ``hub_max_notification_budget``…
    and no lane adds one."

    The refusal belongs to the hub, which "refuses a budget above it rather than
    clamping one", and it arrives as a declined request the gateway reports under
    ADR-0168 §9. A settings model that refused the pair here would be one machine
    deciding another machine's configuration.
    """
    settings = Settings(
        gateway_notification_budget=timedelta(hours=1),
        hub_max_notification_budget=timedelta(seconds=30),
    )

    assert settings.gateway_notification_budget == timedelta(hours=1)


@pytest.mark.parametrize("name", _GATEWAY_FIELDS)
def test_no_gateway_figure_is_nullable(name: str) -> None:
    """None takes a value meaning "off" (ADR-0168 §8).

    "A gateway with no session expiry, no session ceiling and no request bound is
    a resident process that a single local caller can exhaust", so ``None`` is not
    the disabled sentinel ADR-0083 §7 allows a scheduler interval — it is a value
    the field does not have.
    """
    with pytest.raises(ValidationError):
        Settings(**{name: None})  # type: ignore[arg-type] # the point of the case


@pytest.mark.parametrize(
    "name",
    ["gateway_max_sessions", "gateway_max_hub_connections", "gateway_max_request_bytes"],
)
@pytest.mark.parametrize("value", [0, -1])
def test_every_integer_figure_is_refused_unless_strictly_positive(name: str, value: int) -> None:
    """§8: "refused at settings load unless it is strictly positive"."""
    with pytest.raises(ValidationError):
        Settings(**{name: value})  # type: ignore[arg-type] # the point of the case


@pytest.mark.parametrize(
    "name",
    [
        "gateway_session_ttl",
        "gateway_session_idle_timeout",
        "gateway_record_interval",
        "gateway_read_timeout",
        "gateway_bootstrap_ttl",
    ],
)
@pytest.mark.parametrize("value", [timedelta(0), timedelta(seconds=-1)])
def test_every_duration_figure_is_refused_unless_strictly_positive(
    name: str, value: timedelta
) -> None:
    """The ``gt=timedelta(0)`` half of §8's rule, for the five durations.

    ADR-0182 §3 restates it for the fifth in the same words — "refused at settings
    load unless it is strictly positive, in the ``gt=timedelta(0)`` form ADR-0083 §7
    adopted and ADR-0168 §8 applied".
    """
    with pytest.raises(ValidationError):
        Settings(**{name: value})  # type: ignore[arg-type] # the point of the case


@pytest.mark.parametrize("value", [0, 1023, 65536, -1])
def test_the_port_is_refused_unless_it_is_a_valid_non_privileged_port(value: int) -> None:
    """§8 refuses ``gateway_port`` "unless it is a valid non-privileged TCP port".

    Below 1024 the listener needs privilege a gateway has no business holding, and
    above 65535 there is no port to bind — both of which arrive as an errno at
    bind rather than as the value the operator was given, which is why load is
    where they surface.
    """
    with pytest.raises(ValidationError):
        Settings(gateway_port=value)


@pytest.mark.parametrize("value", [1024, 8422, 65535])
def test_the_port_admits_the_whole_non_privileged_range(value: int) -> None:
    """The refusal narrows nothing legitimate."""
    assert Settings(gateway_port=value).gateway_port == value


def test_an_idle_bound_above_the_session_lifetime_is_refused() -> None:
    """§8: refused "unless it is no greater than ``gateway_session_ttl``".

    "An idle bound above the absolute lifetime is a limit that can never bind" —
    and a limit that cannot bind is an absent one, not a weaker one, so an
    operator who set it is holding a defence they do not have.
    """
    with pytest.raises(ValidationError, match="can never bind"):
        Settings(
            gateway_session_ttl=timedelta(hours=1), gateway_session_idle_timeout=timedelta(hours=2)
        )


def test_an_idle_bound_equal_to_the_session_lifetime_is_admitted() -> None:
    """ "No greater than" is the bound, so equal is admitted and only above refused."""
    settings = Settings(
        gateway_session_ttl=timedelta(hours=3), gateway_session_idle_timeout=timedelta(hours=3)
    )

    assert settings.gateway_session_idle_timeout == settings.gateway_session_ttl


def test_a_pending_ceiling_above_the_connection_ceiling_is_refused() -> None:
    """§8's second ordering, on its first one's reason exactly."""
    with pytest.raises(ValidationError, match="can never bind"):
        Settings(gateway_max_browser_connections=4, gateway_max_pending_connections=5)


def test_a_pending_ceiling_equal_to_the_connection_ceiling_is_admitted() -> None:
    """Equal binds — every connection may be unadmitted at once, which is coherent."""
    settings = Settings(gateway_max_browser_connections=4, gateway_max_pending_connections=4)

    assert settings.gateway_max_pending_connections == 4


def test_the_gateway_figures_parse_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator-facing path, which is the only one a deployment reaches."""
    monkeypatch.setenv("ASSISTANT_GATEWAY_PORT", "9001")
    monkeypatch.setenv("ASSISTANT_GATEWAY_SESSION_TTL", "PT2H")
    monkeypatch.setenv("ASSISTANT_GATEWAY_MAX_SESSIONS", "3")

    settings = Settings()

    assert settings.gateway_port == 9001
    assert settings.gateway_session_ttl == timedelta(hours=2)
    assert settings.gateway_max_sessions == 3


# --- ADR-0174 §8: the remote browser listener's three fields -----------------

_OVERLAY = "100.64.0.9"
_PHONE = "nPHONE01CNTRL"


def test_the_remote_browser_listener_is_off_unless_it_is_configured_on() -> None:
    """ADR-0174 §2: "The remote browser listener is **off unless it is configured
    on**. A gateway with no remote-browser-listener configuration binds only
    ADR-0168 §2's loopback listener."

    The address is the switch, exactly as ``hub_remote_address`` is for the hub's
    own remote listener, and for the reason §8 gives: "A boundary that is off unless
    configured on needs a value meaning off."
    """
    settings = Settings()

    assert settings.gateway_remote_address is None
    assert settings.gateway_remote_browser_devices == ()
    assert settings.gateway_remote_host_names == ()


def test_the_switch_is_the_one_gateway_field_that_is_nullable() -> None:
    """ADR-0168 §8's no-nullable rule is "stated over the ten fields in that ADR's own
    table and is untouched"; ADR-0174 §8 adds the one exception and says why.

    Asserted as an exception rather than left implicit, because the rule and its
    exception are one sentence apart in §8 and a reader meeting only the rule would
    call this field a defect.
    """
    nullable = {
        name
        for name in (*_GATEWAY_FIELDS, *_REMOTE_BROWSER_FIELDS)
        if Settings.model_fields[name].default is None
    }

    assert nullable == {"gateway_remote_address"}


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("0.0.0.0", "wildcard"),  # noqa: S104 — the value being refused is the point
        ("::", "wildcard"),
        ("127.0.0.1", "loopback"),
        ("::1", "loopback"),
        ("169.254.7.7", "link-local"),
        ("224.0.0.1", "multicast"),
        ("8.8.8.8", "public internet"),
        ("2606:4700:4700::1111", "public internet"),
        ("gateway.example.ts.net", "not an IP address"),
    ],
)
def test_an_address_adr_0174_forbids_the_browser_listener_is_refused_at_load(
    value: str, reason: str
) -> None:
    """§8: "the five refusals ``hub_remote_address`` already carries, in the same
    shape and for the same reasons (ADR-0124 §2)", plus the name refusal that comes
    with them.

    The loopback case is the one this listener has that the hub's does not: the
    gateway already binds ``127.0.0.1``, so a second listener there would be a
    duplicate rather than a second door — and ADR-0174 §2 keeps the loopback
    listener ADR-0168 §2's alone.
    """
    with pytest.raises(ValidationError, match=reason):
        Settings(gateway_remote_address=value)


@pytest.mark.parametrize("value", ["100.64.0.9", "fd7a:115c:a1e0::42", "10.1.2.3"])
def test_an_overlay_address_is_admitted_for_the_browser_listener(value: str) -> None:
    """The discriminating half: a validator that refused everything would pass above.

    The LAN address is admitted here on purpose. Nothing decidable from the string
    tells a LAN address from an overlay one, so ADR-0174 §2's physical-interface
    clause is closed before the bind instead, by the overlay agent — which is
    ADR-0124 §2's own split, and is pinned in
    ``tests/interfaces/gateway/test_remote_listener.py``.
    """
    assert Settings(gateway_remote_address=value).gateway_remote_address == value


def test_the_two_lists_parse_as_comma_separated_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator-facing path: an owner writes one variable, not JSON.

    ``NoDecode`` is what turns pydantic-settings' JSON decoding off for these two
    fields, so an owner writes ``a,b`` rather than ``'["a", "b"]'`` — and a trailing
    comma or a space after one is not an element.
    """
    monkeypatch.setenv("ASSISTANT_GATEWAY_REMOTE_ADDRESS", _OVERLAY)
    monkeypatch.setenv("ASSISTANT_GATEWAY_REMOTE_BROWSER_DEVICES", f"{_PHONE}, nLAPTOP1CNTRL ,")
    monkeypatch.setenv("ASSISTANT_GATEWAY_REMOTE_HOST_NAMES", "phone.example.ts.net")

    settings = Settings()

    assert settings.gateway_remote_browser_devices == (_PHONE, "nLAPTOP1CNTRL")
    assert settings.gateway_remote_host_names == ("phone.example.ts.net",)


@pytest.mark.parametrize("name", ["gateway_remote_browser_devices", "gateway_remote_host_names"])
def test_a_list_written_about_a_listener_that_is_off_is_refused(name: str) -> None:
    """§8: "Either list being non-empty while ``gateway_remote_address`` is unset is
    **refused at settings load**."

    Both are permissions rather than neutral facts, which is why they are refused
    where ``hub_remote_port`` and ``client_overlay_agent_socket`` are documented as
    ignored: "an owner who wrote one and got silence has a configuration that says
    something the running process does not do".
    """
    with pytest.raises(ValidationError, match="gateway_remote_address is"):
        Settings(**{name: ("nSOMEDEVICE",)})  # type: ignore[arg-type] # the point of the case


def test_both_lists_may_be_empty_while_the_listener_is_on() -> None:
    """The default a gateway configured on gets, and §8 states what it means: "a
    gateway configured on serves its assets and mints no remote session until the
    owner names a device", and "serves the address it bound and nothing else"."""
    settings = Settings(gateway_remote_address=_OVERLAY)

    assert settings.gateway_remote_browser_devices == ()
    assert settings.gateway_remote_host_names == ()


@pytest.mark.parametrize("element", ["", "   ", "\ud800"])
def test_a_listed_device_settings_can_decide_is_unsatisfiable_is_refused(element: str) -> None:
    """§8's half of the split check: ``Settings`` "refuses at load what it can decide
    without importing anything: an element that is blank or has no UTF-8 form".

    An identity failing the invariant is one the agent can never report, so without
    this "the owner's named device is refused at every exchange with nothing saying
    why: the configuration would be silently unsatisfiable".
    """
    with pytest.raises(ValidationError, match="gateway_remote_browser_devices"):
        Settings(gateway_remote_address=_OVERLAY, gateway_remote_browser_devices=(element,))


def test_the_byte_bound_is_not_restated_in_core() -> None:
    """§8: "No component of ``core`` may import that constant, and no lane may restate
    its value in ``core`` to move the check there."

    ``Settings`` therefore admits an over-long identity and the gateway refuses it at
    start, which is golden rule 2 rather than a compromise —
    ``MAX_OVERLAY_IDENTITY_BYTES`` lives in ``ai_assistant.wire.overlay`` and ``core``
    may import nothing in ``ai_assistant`` but itself.
    """
    listed = "n" * 400

    settings = Settings(gateway_remote_address=_OVERLAY, gateway_remote_browser_devices=(listed,))

    assert settings.gateway_remote_browser_devices == (listed,)


def test_a_repeated_device_is_not_refused() -> None:
    """§8: "A repeated element changes nothing and is not refused; order carries no
    meaning"."""
    settings = Settings(
        gateway_remote_address=_OVERLAY, gateway_remote_browser_devices=(_PHONE, _PHONE)
    )

    assert frozenset(settings.gateway_remote_browser_devices) == {_PHONE}


def test_no_figure_bounds_how_many_devices_may_be_listed() -> None:
    """§8: "No figure bounds the list's length, and none is owed. It is configuration
    the owner writes, it is not supplied by any peer."

    Naming one "would be an eleventh number defending nothing, which is the move
    ADR-0168 §8 itself refused when it declined 'an eighth figure for a queue nothing
    yet needs'".
    """
    many = tuple(f"nDEVICE{index:05d}" for index in range(500))

    settings = Settings(gateway_remote_address=_OVERLAY, gateway_remote_browser_devices=many)

    assert len(settings.gateway_remote_browser_devices) == 500
