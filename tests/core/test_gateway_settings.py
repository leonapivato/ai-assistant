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

#: ADR-0202 §8's table, which is two paths and no figure either. Held apart from both
#: tuples above for ADR-0174 §8's reason and for one of its own: §8 says in terms that
#: "no third field is added and none is owed" — ``gateway_remote_address`` remains the
#: switch, a field by which this listener could serve plain HTTP is what §2 refuses,
#: and a renewal interval is not this system's to hold because §4 makes renewal an
#: owner act.
_REMOTE_TLS_FIELDS = (
    "gateway_remote_tls_certificate",
    "gateway_remote_tls_key",
)

#: ADR-0327's fields: the hosted listener's switch, port, door name and device (§5,
#: §7:2, §10), and the edge's keys, claims and assertion lifetime (§6). Held apart
#: for ADR-0174 §8's reason: §5:8 spends no new budget — the figures ADR-0174 §8:1
#: names are totals across every listener, the hosted one included.
_HOSTED_FIELDS = (
    "gateway_hosted_address",
    "gateway_hosted_port",
    "gateway_hosted_host_name",
    "gateway_hosted_device",
    "gateway_edge_public_keys",
    "gateway_edge_issuer",
    "gateway_edge_audience",
    "gateway_edge_subject",
    "gateway_edge_assertion_max_age",
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
    eleventh from ADR-0175 §8, the twelfth from ADR-0182 §3, ADR-0174 §8's three
    non-figures and ADR-0202 §8's two, and ADR-0327's nine. Discovering a twenty-
    seventh here is cheaper than in review.
    """
    named = {name for name in Settings.model_fields if name.startswith("gateway_")}

    assert named == (
        set(_GATEWAY_FIELDS)
        | set(_REMOTE_BROWSER_FIELDS)
        | set(_REMOTE_TLS_FIELDS)
        | set(_HOSTED_FIELDS)
    )


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

#: The pair ADR-0202 §8 requires beside a configured listener. Neither names a real
#: file and neither has to: §8 splits the check, and ``Settings`` "refuses at load
#: what it can decide without touching the filesystem or importing a subsystem".
#: Existence, custody, permissions, the key matching the certificate, both validity
#: bounds and §6's name check are the gateway's, at start, and are pinned in
#: ``tests/interfaces/gateway/test_gateway_tls.py``.
_CERTIFICATE = "/etc/assistant/laptop.tail2e4542.ts.net.crt"
_KEY = "/etc/assistant/laptop.tail2e4542.ts.net.key"


def _configured_on(**overrides: object) -> Settings:
    """Settings with the remote browser listener on, and the pair that comes with it.

    ADR-0202 §8 refuses ``gateway_remote_address`` set with either path unset, so the
    address alone is no longer a loadable configuration and every case about the
    *other* remote fields goes through here rather than restating two paths.
    """
    overrides.setdefault("gateway_remote_address", _OVERLAY)
    overrides.setdefault("gateway_remote_tls_certificate", _CERTIFICATE)
    overrides.setdefault("gateway_remote_tls_key", _KEY)
    return Settings(**overrides)  # type: ignore[arg-type] # each key is a field of the model


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


def test_both_tls_paths_are_unset_by_default() -> None:
    """ADR-0202 §8: both are "unset by default", and they are the only other nullable
    fields in this block.

    They are nullable for the switch's own reason one field over — a boundary that is
    off unless configured on needs a value meaning off — and ADR-0168 §8's no-nullable
    rule is still stated over the ten fields in that ADR's own table alone.
    """
    settings = Settings()

    assert settings.gateway_remote_tls_certificate is None
    assert settings.gateway_remote_tls_key is None
    assert all(Settings.model_fields[name].default is None for name in _REMOTE_TLS_FIELDS)


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
    assert _configured_on(gateway_remote_address=value).gateway_remote_address == value


def test_the_two_lists_parse_as_comma_separated_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator-facing path: an owner writes one variable, not JSON.

    ``NoDecode`` is what turns pydantic-settings' JSON decoding off for these two
    fields, so an owner writes ``a,b`` rather than ``'["a", "b"]'`` — and a trailing
    comma or a space after one is not an element.
    """
    monkeypatch.setenv("ASSISTANT_GATEWAY_REMOTE_ADDRESS", _OVERLAY)
    monkeypatch.setenv("ASSISTANT_GATEWAY_REMOTE_BROWSER_DEVICES", f"{_PHONE}, nLAPTOP1CNTRL ,")
    monkeypatch.setenv("ASSISTANT_GATEWAY_REMOTE_HOST_NAMES", "phone.example.ts.net")
    monkeypatch.setenv("ASSISTANT_GATEWAY_REMOTE_TLS_CERTIFICATE", _CERTIFICATE)
    monkeypatch.setenv("ASSISTANT_GATEWAY_REMOTE_TLS_KEY", _KEY)

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
    settings = _configured_on()

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
        _configured_on(gateway_remote_browser_devices=(element,))


def test_the_byte_bound_is_not_restated_in_core() -> None:
    """§8: "No component of ``core`` may import that constant, and no lane may restate
    its value in ``core`` to move the check there."

    ``Settings`` therefore admits an over-long identity and the gateway refuses it at
    start, which is golden rule 2 rather than a compromise —
    ``MAX_OVERLAY_IDENTITY_BYTES`` lives in ``ai_assistant.wire.overlay`` and ``core``
    may import nothing in ``ai_assistant`` but itself.
    """
    listed = "n" * 400

    settings = _configured_on(gateway_remote_browser_devices=(listed,))

    assert settings.gateway_remote_browser_devices == (listed,)


def test_a_repeated_device_is_not_refused() -> None:
    """§8: "A repeated element changes nothing and is not refused; order carries no
    meaning"."""
    settings = _configured_on(gateway_remote_browser_devices=(_PHONE, _PHONE))

    assert frozenset(settings.gateway_remote_browser_devices) == {_PHONE}


def test_no_figure_bounds_how_many_devices_may_be_listed() -> None:
    """§8: "No figure bounds the list's length, and none is owed. It is configuration
    the owner writes, it is not supplied by any peer."

    Naming one "would be an eleventh number defending nothing, which is the move
    ADR-0168 §8 itself refused when it declined 'an eighth figure for a queue nothing
    yet needs'".
    """
    many = tuple(f"nDEVICE{index:05d}" for index in range(500))

    settings = _configured_on(gateway_remote_browser_devices=many)

    assert len(settings.gateway_remote_browser_devices) == 500


# --- ADR-0202 §8: the two TLS paths, and the three combinations refused -------


@pytest.mark.parametrize("field", _REMOTE_TLS_FIELDS)
@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_tls_path_is_refused_at_load(field: str, value: str) -> None:
    """§8: ``Settings`` "refuses at load what it can decide without touching the
    filesystem or importing a subsystem: a value that is blank or has no UTF-8
    form".

    A blank path names no file on any machine, so it is decidable here — and an owner
    who wrote one and got silence would have "a configuration that says something the
    running process does not do", which is the failure ADR-0174 §8 refused by name one
    field over.
    """
    other = next(name for name in _REMOTE_TLS_FIELDS if name != field)

    with pytest.raises(ValidationError, match=field):
        Settings(**{"gateway_remote_address": _OVERLAY, field: value, other: _KEY})  # type: ignore[arg-type] # the point of the case


@pytest.mark.parametrize("field", _REMOTE_TLS_FIELDS)
def test_a_tls_path_with_no_utf_8_form_is_refused_at_load(field: str) -> None:
    """§8's other decidable-here condition.

    A lone surrogate is a ``str`` Python holds and UTF-8 cannot express, so a refusal
    naming the path could not itself be written — which is the fault
    ``wire.custody.displayable`` exists to keep out of a refusal's own text, arriving
    from the configuration instead.
    """
    other = next(name for name in _REMOTE_TLS_FIELDS if name != field)

    with pytest.raises(ValidationError, match="no UTF-8 form"):
        Settings(**{"gateway_remote_address": _OVERLAY, field: "/etc/\ud800", other: _KEY})  # type: ignore[arg-type] # the point of the case


@pytest.mark.parametrize("field", _REMOTE_TLS_FIELDS)
def test_half_a_pair_is_refused_as_half_a_pair(field: str) -> None:
    """§8's third refused configuration: "one set while the other is unset".

    Reported as a split pair rather than as one of the other two conditions, because
    telling an owner who wrote one path that the listener is off would name the
    setting they got right. A certificate with no key serves nothing and a key with no
    certificate proves nothing, whichever way round the address is.
    """
    with pytest.raises(ValidationError, match="is set while"):
        Settings(**{"gateway_remote_address": _OVERLAY, field: _CERTIFICATE})  # type: ignore[arg-type] # the point of the case


def test_a_pair_written_about_a_listener_that_is_off_is_refused() -> None:
    """§8's first refused configuration: "either field set while
    ``gateway_remote_address`` is unset".

    The rule ADR-0174 §8 applies to its two lists, for the reason it gives: a
    configuration no reading makes true is refused rather than ignored silently.
    """
    with pytest.raises(ValidationError, match="the listener they would serve is off"):
        Settings(gateway_remote_tls_certificate=_CERTIFICATE, gateway_remote_tls_key=_KEY)


def test_a_listener_configured_on_without_a_pair_is_refused() -> None:
    """§8's second: "either field unset while ``gateway_remote_address`` is set".

    §2 is why there is no third outcome: "A configured remote browser listener serves
    HTTPS and nothing else. No setting makes it serve plain HTTP, and the gateway may
    not fall back to plain HTTP on any condition." So a listener switched on with no
    certificate is not a plain-HTTP listener — it is a configuration with no meaning,
    and the message says which two settings to write.
    """
    with pytest.raises(ValidationError, match="serves HTTPS and nothing else"):
        Settings(gateway_remote_address=_OVERLAY)


def test_neither_path_is_owed_by_a_gateway_with_no_remote_listener() -> None:
    """The default deployment, unchanged: no address, no pair, and nothing refused.

    ADR-0202 §2 leaves ADR-0168 §2's loopback listener untouched — "it speaks plain
    HTTP, it is bound whether or not the remote listener is, and no clause of this ADR
    adds a certificate, a key or a scheme requirement to it".
    """
    settings = Settings()

    assert settings.gateway_remote_address is None
    assert settings.gateway_remote_tls_certificate is None
    assert settings.gateway_remote_tls_key is None


def test_a_tls_path_is_stripped_of_surrounding_space() -> None:
    """The convention every other configured path and element in this block follows:
    an owner who left a space after a comma or before a value wrote the same path."""
    settings = _configured_on(gateway_remote_tls_certificate=f"  {_CERTIFICATE}  ")

    assert settings.gateway_remote_tls_certificate == _CERTIFICATE


def test_settings_does_not_look_at_the_filesystem() -> None:
    """§8: the split is "one check, two places, each where the fact it needs already
    lives", and the reason is golden rule 2 rather than taste — the custody predicate
    is ``wire/custody.py``'s, and a ``Settings`` validator performing the walk would
    be the boundary violation ``lint-imports`` fails on.

    So a path to a file that does not exist **loads**, and the gateway refuses it at
    start. Pinning that here is what stops a later lane moving the check and quietly
    making ``core`` import a subsystem.
    """
    settings = _configured_on(
        gateway_remote_tls_certificate="/nowhere/at/all.crt",
        gateway_remote_tls_key="/nowhere/at/all.key",
    )

    assert settings.gateway_remote_tls_certificate == "/nowhere/at/all.crt"


@pytest.mark.parametrize("field", _REMOTE_TLS_FIELDS)
def test_a_tls_path_carrying_a_nul_is_refused_at_load(field: str) -> None:
    """The third condition decidable from the value alone (ADR-0202 §8).

    Adversarial review found it: a NUL passes the blank and UTF-8 checks and then
    reaches ``Path.stat``, which raises ``ValueError`` rather than ``OSError``,
    because no system call is ever attempted with such a name. The gateway's own
    refusals are phrased around a file it could not read and catch ``OSError``, so
    the operator got a bare traceback where a sentence was owed. No pathname on any
    system may carry one, which is what puts the refusal in this class rather than in
    a second ``except`` at the gateway.
    """
    other = next(name for name in _REMOTE_TLS_FIELDS if name != field)

    with pytest.raises(ValidationError, match="NUL character"):
        Settings(
            **{  # type: ignore[arg-type] # the point of the case
                "gateway_remote_address": _OVERLAY,
                field: "/etc/assistant/cert\x00.pem",
                other: _KEY,
            }
        )


# --- ADR-0327: the hosted listener and the edge in front of it ---------------------

#: A public key in the form ``gateway_edge_public_keys`` takes: the raw 32 bytes in
#: unpadded base64url (RFC 8037's ``x``). Any 32 bytes are a valid value at load; the
#: gateway loads the key at start.
_EDGE_KEY = "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"

#: Every field the hosted listener needs to be on, with values ``Settings`` admits.
_HOSTED_ON: dict[str, object] = {
    "gateway_hosted_address": "127.0.0.1",
    "gateway_hosted_host_name": "door.example.com",
    "gateway_hosted_device": "web-owner",
    "gateway_edge_public_keys": (_EDGE_KEY,),
    "gateway_edge_issuer": "https://signin.example.com",
    "gateway_edge_audience": "hub-owner",
    "gateway_edge_subject": "acct_7f3a9c",
}

#: The five §6:12 names beside the key set, which are set exactly when the switch is.
_HOSTED_COMPANIONS = (
    "gateway_hosted_host_name",
    "gateway_hosted_device",
    "gateway_edge_issuer",
    "gateway_edge_audience",
    "gateway_edge_subject",
)


def _hosted(**overrides: object) -> Settings:
    """Settings with the hosted listener on, and any field replaced."""
    values = {**_HOSTED_ON, **overrides}
    return Settings(**values)  # type: ignore[arg-type] # a mapping of the model's own fields


def test_the_hosted_listener_is_off_unless_it_is_configured_on() -> None:
    """ADR-0327 §5:1: "off unless it is configured on, by ``gateway_hosted_address``.
    Unset, which is the default, means off"."""
    settings = Settings()

    assert settings.gateway_hosted_address is None
    assert settings.gateway_hosted_port == 8423
    assert settings.gateway_edge_public_keys == ()
    assert settings.gateway_edge_assertion_max_age == timedelta(seconds=60)
    for name in _HOSTED_COMPANIONS:
        assert getattr(settings, name) is None, name


def test_a_hosted_listener_configured_whole_loads() -> None:
    """Every §6:12 field set, and the address the box's own loopback."""
    settings = _hosted()

    assert settings.gateway_hosted_address == "127.0.0.1"
    assert settings.gateway_edge_public_keys == (_EDGE_KEY,)


@pytest.mark.parametrize("value", ["127.0.0.1", "127.0.0.9", "::1"])
def test_a_loopback_address_is_admitted_for_the_hosted_listener(value: str) -> None:
    """§5:3: "a literal loopback address"."""
    assert _hosted(gateway_hosted_address=value).gateway_hosted_address == value


@pytest.mark.parametrize("value", ["10.0.0.5", "172.17.0.2", "192.168.1.20", "fd00::5"])
def test_a_private_use_address_is_admitted_for_the_hosted_listener(value: str) -> None:
    """§5:3: "or a literal private-use address (IPv4 RFC 1918, IPv6 unique-local)" —
    the container case, whose port the setup publishes to the host's loopback alone
    (§5:4)."""
    assert _hosted(gateway_hosted_address=value).gateway_hosted_address == value


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("0.0.0.0", "wildcard"),  # noqa: S104 — the refusal under test
        ("::", "wildcard"),
        ("224.0.0.1", "multicast"),
        ("169.254.0.7", "link-local"),
        ("fe80::1", "link-local"),
        ("100.64.0.9", "shared space"),
        ("100.127.255.1", "shared space"),
        ("8.8.8.8", "neither a loopback nor a private-use"),
        ("2001:4860:4860::8888", "neither a loopback nor a private-use"),
        # Reserved blocks `ipaddress` calls private and §5:3 does not name.
        ("192.0.2.1", "neither a loopback nor a private-use"),
        ("198.18.0.1", "neither a loopback nor a private-use"),
        ("::ffff:10.0.0.1", "neither a loopback nor a private-use"),
        ("fd00::5%eth0", "zone index"),
        ("door.example.com", "not an IP address"),
        ("localhost", "not an IP address"),
    ],
)
def test_an_address_adr_0327_forbids_the_hosted_listener_is_refused_at_load(
    value: str, reason: str
) -> None:
    """§5:3: "A wildcard, a multicast address, a link-local address, an address in the
    shared space ``100.64.0.0/10`` that overlays use, and any globally reachable
    address are refused." A name is refused rather than resolved."""
    with pytest.raises(ValidationError, match=reason):
        _hosted(gateway_hosted_address=value)


def test_the_hosted_port_may_not_be_the_loopback_listeners() -> None:
    """§5:5: "refused at settings load when the hosted listener is on and the port
    equals ``gateway_port``"."""
    with pytest.raises(ValidationError, match="equals gateway_port"):
        _hosted(gateway_port=9000, gateway_hosted_port=9000)


def test_the_hosted_port_is_a_neutral_fact_while_the_listener_is_off() -> None:
    """Neither the port nor the lifetime is among §6:13's stranded settings."""
    settings = Settings(
        gateway_port=9000,
        gateway_hosted_port=9000,
        gateway_edge_assertion_max_age=timedelta(seconds=30),
    )

    assert settings.gateway_hosted_port == 9000


@pytest.mark.parametrize("value", [0, 1023, 65536])
def test_the_hosted_port_is_a_valid_non_privileged_port(value: int) -> None:
    """§5:5: "a valid non-privileged TCP port"."""
    with pytest.raises(ValidationError):
        Settings(gateway_hosted_port=value)


@pytest.mark.parametrize("name", _HOSTED_COMPANIONS)
def test_a_hosted_listener_missing_a_companion_is_refused(name: str) -> None:
    """§6:12: refused "while any of" the five "is unset"."""
    with pytest.raises(ValidationError, match=name):
        _hosted(**{name: None})


def test_a_hosted_listener_with_no_edge_key_is_refused() -> None:
    """§6:12: "or while ``gateway_edge_public_keys`` is empty"."""
    with pytest.raises(ValidationError, match="gateway_edge_public_keys"):
        _hosted(gateway_edge_public_keys=())


@pytest.mark.parametrize("name", [*_HOSTED_COMPANIONS, "gateway_edge_public_keys"])
def test_an_edge_setting_written_about_a_listener_that_is_off_is_refused(name: str) -> None:
    """§6:13: "A configuration with the hosted listener off is refused at settings load
    while any of those five is set, or while ``gateway_edge_public_keys`` is
    non-empty" — none is ignored silently."""
    with pytest.raises(ValidationError, match=name):
        Settings(**{name: _HOSTED_ON[name]})  # type: ignore[arg-type] # the point of the case


@pytest.mark.parametrize(
    "value",
    [
        "Door.Example.com",
        "door.example.com:443",
        "https://door.example.com",
        "door.example.com/",
        "door.example.com.",
        "door",
        "-door.example.com",
        "203.0.113.4",
        "",
    ],
)
def test_a_door_name_no_browser_would_send_is_refused(value: str) -> None:
    """§7:2 compares the `Host` literally and §7:3 builds the `Origin` from the name,
    so the name is a lower-case DNS name with no scheme, port or path."""
    with pytest.raises(ValidationError, match="gateway_hosted_host_name"):
        _hosted(gateway_hosted_host_name=value)


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("", "blank"),
        ("   ", "blank"),
        ("hub", "hub's own machine"),
        ('web"owner', "quote, a backslash or a control"),
        ("web\\owner", "quote, a backslash or a control"),
        ("web\nowner", "quote, a backslash or a control"),
        ("\ud800", "UTF-8"),
    ],
)
def test_a_hosted_device_the_hub_could_not_accept_is_refused(value: str, reason: str) -> None:
    """§10:3: held to ADR-0298 §1:3's invariant, split as ADR-0174 §8:7 splits the
    check, and "never ``hub``". The byte bound is the gateway's, at start."""
    with pytest.raises(ValidationError, match=reason):
        _hosted(gateway_hosted_device=value)


def test_the_hosted_device_may_not_be_a_listed_remote_device() -> None:
    """§10:4: the name is "held by no other device the hub knows" — one that the
    remote listener also names is one this configuration already knows of."""
    with pytest.raises(ValidationError, match="gateway_remote_browser_devices"):
        _hosted(
            gateway_remote_address="100.64.0.9",
            gateway_remote_browser_devices=("web-owner",),
            gateway_remote_tls_certificate="/etc/assistant/cert.pem",
            gateway_remote_tls_key="/etc/assistant/key.pem",
        )


@pytest.mark.parametrize(
    "value",
    [
        "not base64!",
        "AAAA",
        "A" * 44,
        _EDGE_KEY + "=",
        "-----BEGIN PUBLIC KEY-----",
    ],
)
def test_an_edge_key_that_is_not_one_ed25519_public_key_is_refused(value: str) -> None:
    """§6:4: "a set of Ed25519 public keys" — each the raw 32 bytes, unpadded base64url."""
    with pytest.raises(ValidationError, match="gateway_edge_public_keys"):
        _hosted(gateway_edge_public_keys=(value,))


def test_the_edge_keys_parse_as_comma_separated_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rotation adds a key beside the old one (§6:5), so the set is a list."""
    second = "A" * 43
    for name, value in _HOSTED_ON.items():
        if name != "gateway_edge_public_keys":
            monkeypatch.setenv(f"ASSISTANT_{name.upper()}", str(value))
    monkeypatch.setenv("ASSISTANT_GATEWAY_EDGE_PUBLIC_KEYS", f"{_EDGE_KEY}, {second}")

    assert Settings().gateway_edge_public_keys == (_EDGE_KEY, second)


@pytest.mark.parametrize("name", ["gateway_edge_issuer", "gateway_edge_audience"])
@pytest.mark.parametrize("value", ["", "  "])
def test_a_blank_claim_is_refused(name: str, value: str) -> None:
    """§6:6, §6:7: compared literally, so a blank one could never be equalled."""
    with pytest.raises(ValidationError, match=name):
        _hosted(**{name: value})


def test_a_subject_that_is_an_email_address_is_refused() -> None:
    """§6:9: "the edge's opaque, stable identifier for the hosted owner's account, not
    an email address or any other contact detail"."""
    with pytest.raises(ValidationError, match="email") as refused:
        _hosted(gateway_edge_subject="person@example.com")
    # §7:8 keeps the subject out of every record, so the refusal does not echo it.
    assert "person@example.com" not in str(refused.value).split("input_value")[0]


@pytest.mark.parametrize(
    "value", [timedelta(0), timedelta(seconds=-1), timedelta(minutes=5, microseconds=1)]
)
def test_the_assertion_lifetime_is_positive_and_at_most_five_minutes(value: timedelta) -> None:
    """§6:11: "refused at settings load unless it is strictly positive and no greater
    than five minutes"."""
    with pytest.raises(ValidationError):
        Settings(gateway_edge_assertion_max_age=value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (timedelta(minutes=5), timedelta(minutes=5)),
        (60, timedelta(minutes=1)),
        ("PT1M", timedelta(minutes=1)),
        ("00:01:00", timedelta(minutes=1)),
    ],
)
def test_the_assertion_lifetime_takes_every_form_a_duration_takes(
    value: object, expected: timedelta
) -> None:
    """The forms ``test_config.py`` pins for every duration at an hour, at a minute —
    the hour is above this field's ceiling (§6:11)."""
    settings = Settings(gateway_edge_assertion_max_age=value)  # type: ignore[arg-type] # the point of the case

    assert settings.gateway_edge_assertion_max_age == expected


def test_the_assertion_lifetime_parses_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator's spelling, ISO-8601."""
    monkeypatch.setenv("ASSISTANT_GATEWAY_EDGE_ASSERTION_MAX_AGE", "PT2M")

    assert Settings().gateway_edge_assertion_max_age == timedelta(minutes=2)
