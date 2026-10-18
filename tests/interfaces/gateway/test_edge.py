"""What the gateway accepts as the sign-in edge's assertion (ADR-0327 §6).

Driven against :mod:`gateway_edge`'s fake edge, which signs with a key generated for
the case. Each refusal case changes exactly one thing about an assertion the gateway
otherwise accepts, so a case cannot pass on a different fault than the one it names —
and each asserts **which** fault, because §7:7 records it.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from gateway_edge import AUDIENCE, OMIT, FakeEdge, b64url, segment

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.interfaces.gateway.edge import (
    ASSERTION_HEADER,
    AssertionFault,
    EdgeTerms,
    check_assertion,
    edge_terms,
)
from ai_assistant.interfaces.gateway.records import RefusalCondition

#: One instant every case reads, so a time is a fact of the case and not of the run.
_NOW: Final = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


@pytest.fixture
def edge() -> FakeEdge:
    """One fake edge, with a key of its own."""
    return FakeEdge()


@pytest.fixture
def terms(edge: FakeEdge) -> EdgeTerms:
    """The terms a gateway configured for ``edge`` holds an assertion to."""
    loaded = edge_terms(Settings(**edge.settings()))
    assert loaded is not None
    return loaded


def _check(token: str | None, terms: EdgeTerms, *, now: datetime = _NOW) -> AssertionFault | None:
    return check_assertion(token, terms=terms, now=now)


def test_an_assertion_the_edge_signed_for_this_hub_is_accepted(
    edge: FakeEdge, terms: EdgeTerms
) -> None:
    """§6: signature, issuer, audience, subject and times all hold."""
    assert _check(edge.sign(_NOW), terms) is None


def test_the_header_is_the_one_section_6_names() -> None:
    """§6:1: "carried in exactly one ``Edge-Assertion`` request header"."""
    assert ASSERTION_HEADER == "edge-assertion"


def test_no_assertion_is_its_own_condition(terms: EdgeTerms) -> None:
    """§6:1: "A request carrying none, or more than one, carries no assertion" —
    :meth:`.http.Request.header` answers ``None`` for both."""
    assert _check(None, terms) is AssertionFault.ABSENT


def test_every_fault_is_a_condition_the_record_can_name() -> None:
    """§7:7: the record names which check failed, with these seven values."""
    assert {RefusalCondition(fault.value) for fault in AssertionFault} == {
        RefusalCondition.ASSERTION_ABSENT,
        RefusalCondition.ASSERTION_MALFORMED,
        RefusalCondition.ASSERTION_SIGNATURE,
        RefusalCondition.ASSERTION_ISSUER,
        RefusalCondition.ASSERTION_AUDIENCE,
        RefusalCondition.ASSERTION_SUBJECT,
        RefusalCondition.ASSERTION_TIMES,
    }


# --- the form: a compact JWS whose two halves are JSON objects -----------------------


@pytest.mark.parametrize(
    "token",
    [
        "",
        "one",
        "two.segments",
        "four.segments.in.it",
        "a..c",
        "not base64!.e30.AAAA",
    ],
)
def test_a_token_that_is_not_a_compact_jws_is_malformed(token: str, terms: EdgeTerms) -> None:
    """§6:1: a JSON Web Token in compact JWS form, and nothing else."""
    assert _check(token, terms) is AssertionFault.MALFORMED


def test_padding_is_not_admitted_in_a_segment(edge: FakeEdge, terms: EdgeTerms) -> None:
    """RFC 7515 §2: base64url *without* padding. The standard decoder would accept it,
    and would discard any character outside the alphabet — which is why the alphabet
    is checked first."""
    header, claims, signature = edge.sign(_NOW).split(".")

    assert _check(f"{header}=.{claims}.{signature}", terms) is AssertionFault.MALFORMED
    assert _check(f"{header}.{claims}.{signature}=", terms) is AssertionFault.MALFORMED


@pytest.mark.parametrize("header", [[], "EdDSA", 7, None])
def test_a_header_that_is_not_one_json_object_is_malformed(
    header: Any,
    edge: FakeEdge,
    terms: EdgeTerms,
) -> None:
    """The header is a JSON object (RFC 7515 §4)."""
    _, claims, signature = edge.sign(_NOW).split(".")

    assert _check(f"{segment(header)}.{claims}.{signature}", terms) is AssertionFault.MALFORMED


def test_a_header_member_named_twice_is_malformed(edge: FakeEdge, terms: EdgeTerms) -> None:
    """A member named twice is refused rather than resolved to either one."""
    doubled = b64url(b'{"alg":"none","alg":"EdDSA"}')
    _, claims, _ = edge.sign(_NOW).split(".")
    signed = f"{doubled}.{claims}"
    signature = b64url(edge.key.sign(signed.encode("ascii")))

    assert _check(f"{signed}.{signature}", terms) is AssertionFault.MALFORMED


def test_a_claim_named_twice_is_malformed_even_when_signed(
    edge: FakeEdge, terms: EdgeTerms
) -> None:
    """The edge's own signature over an ambiguous object does not make it unambiguous:
    a parser taking the last ``sub`` would judge one account and another the first."""
    issued = _NOW.timestamp()
    raw = (
        f'{{"iss":"https://signin.example.test","aud":"{AUDIENCE}","sub":"someone-else",'
        f'"sub":"acct_7f3a9c02","iat":{issued},"exp":{issued + 30}}}'
    )
    token = edge.sign_raw({"alg": "EdDSA"}, b64url(raw.encode("utf-8")))

    assert _check(token, terms) is AssertionFault.MALFORMED


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_time_that_is_not_a_json_number_is_malformed(
    constant: str, edge: FakeEdge, terms: EdgeTerms
) -> None:
    """``NaN`` and the infinities are not JSON (RFC 8259 §6), and a time compared
    against one is no comparison — ``exp: Infinity`` would never expire."""
    issued = _NOW.timestamp()
    raw = (
        f'{{"iss":"https://signin.example.test","aud":"{AUDIENCE}",'
        f'"sub":"acct_7f3a9c02","iat":{issued},"exp":{constant}}}'
    )
    token = edge.sign_raw({"alg": "EdDSA"}, b64url(raw.encode("utf-8")))

    assert _check(token, terms) is AssertionFault.MALFORMED


def test_claims_that_are_not_one_json_object_are_malformed(
    edge: FakeEdge, terms: EdgeTerms
) -> None:
    """Signed, and still not a claims set."""
    token = edge.sign_raw({"alg": "EdDSA"}, segment(["iss", "aud"]))

    assert _check(token, terms) is AssertionFault.MALFORMED


def test_a_critical_extension_is_malformed(edge: FakeEdge, terms: EdgeTerms) -> None:
    """RFC 7515 §4.1.11: a ``crit`` naming an extension the recipient does not
    understand invalidates the token, and this recipient understands none."""
    token = edge.sign(_NOW, header={"alg": "EdDSA", "crit": ["b64"], "b64": False})

    assert _check(token, terms) is AssertionFault.MALFORMED


# --- §6:2, §6:3: Ed25519 against the configured keys, and nothing from the token ------


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "none"},
        {"alg": "HS256"},
        {"alg": "ES256"},
        {"alg": "eddsa"},
        {"typ": "JWT"},
    ],
)
def test_a_token_naming_any_other_algorithm_is_refused(
    header: dict[str, Any], edge: FakeEdge, terms: EdgeTerms
) -> None:
    """§6:2: "A token naming any other algorithm, ``none`` included, is refused" — and
    one naming none at all names no algorithm the gateway verifies."""
    token = edge.sign(_NOW, header=header)

    assert _check(token, terms) is AssertionFault.SIGNATURE


def test_an_unsigned_token_is_refused(edge: FakeEdge, terms: EdgeTerms) -> None:
    """The ``none`` attack's other half: an empty signature segment."""
    header, claims, _ = edge.sign(_NOW, header={"alg": "none"}).split(".")

    assert _check(f"{header}.{claims}.", terms) is AssertionFault.MALFORMED


def test_a_token_another_key_signed_is_refused(terms: EdgeTerms) -> None:
    """§6:3: "verifies the signature only against the public keys configured"."""
    assert _check(FakeEdge().sign(_NOW), terms) is AssertionFault.SIGNATURE


@pytest.mark.parametrize("member", ["jwk", "jku", "x5u", "x5c", "kid"])
def test_a_member_naming_a_key_decides_nothing(member: str, terms: EdgeTerms) -> None:
    """§6:3: "a ``jwk``, ``jku``, ``x5u``, ``x5c`` or ``kid`` member decides nothing" —
    a token signed by a stranger carrying its own key is a token a stranger signed."""
    stranger = FakeEdge()
    pointer: dict[str, Any] = {
        "jwk": {"kty": "OKP", "crv": "Ed25519", "x": stranger.public_key},
        "jku": "https://attacker.example/keys",
        "x5u": "https://attacker.example/cert",
        "x5c": ["MIIB"],
        "kid": "0",
    }
    token = stranger.sign(_NOW, header={"alg": "EdDSA", member: pointer[member]})

    assert _check(token, terms) is AssertionFault.SIGNATURE


def test_a_member_naming_a_key_does_not_stop_the_configured_key_verifying(
    edge: FakeEdge, terms: EdgeTerms
) -> None:
    """The same members on a token the configured key did sign: still accepted,
    because they are read for nothing."""
    token = edge.sign(_NOW, header={"alg": "EdDSA", "kid": "elsewhere", "jku": "https://x"})

    assert _check(token, terms) is None


def test_a_tampered_claim_breaks_the_signature(edge: FakeEdge, terms: EdgeTerms) -> None:
    """The signature covers the claims as encoded."""
    header, _, signature = edge.sign(_NOW).split(".")
    forged = segment({"iss": "x", "aud": AUDIENCE, "sub": "x", "iat": _NOW.timestamp(), "exp": 9e9})

    assert _check(f"{header}.{forged}.{signature}", terms) is AssertionFault.SIGNATURE


def test_a_signature_of_the_wrong_length_is_refused(edge: FakeEdge, terms: EdgeTerms) -> None:
    """An Ed25519 signature is 64 bytes (RFC 8032 §5.1.6)."""
    header, claims, _ = edge.sign(_NOW).split(".")

    assert _check(f"{header}.{claims}.{b64url(bytes(63))}", terms) is AssertionFault.SIGNATURE


def test_any_configured_key_may_verify_it() -> None:
    """§6:3: "the assertion verifies when one of them verifies it" — which is what lets
    the operator rotate by adding the new key before removing the old (§6:5)."""
    old, new = FakeEdge(), FakeEdge()
    terms = edge_terms(
        Settings(**old.settings(gateway_edge_public_keys=(old.public_key, new.public_key)))
    )
    assert terms is not None

    assert _check(old.sign(_NOW), terms) is None
    assert _check(new.sign(_NOW), terms) is None


# --- §6:6 to §6:8: issuer, audience and subject, literally -------------------------


@pytest.mark.parametrize(
    "iss", ["https://signin.example.test/", "HTTPS://signin.example.test", 7, OMIT]
)
def test_another_issuer_is_refused(iss: object, edge: FakeEdge, terms: EdgeTerms) -> None:
    """§6:6: "``iss`` claim equals ``gateway_edge_issuer``, compared literally"."""
    assert _check(edge.sign(_NOW, iss=iss), terms) is AssertionFault.ISSUER


@pytest.mark.parametrize("aud", ["hub-owner-02", "HUB-OWNER-01", OMIT, None])
def test_another_audience_is_refused(aud: object, edge: FakeEdge, terms: EdgeTerms) -> None:
    """§6:7: a single string equal to ``gateway_edge_audience``."""
    assert _check(edge.sign(_NOW, aud=aud), terms) is AssertionFault.AUDIENCE


def test_an_audience_that_is_a_list_is_refused_even_holding_this_one(
    edge: FakeEdge, terms: EdgeTerms
) -> None:
    """§6:7: "An ``aud`` that is a list is refused, so one assertion never admits to two
    hubs" — a list of one is a list."""
    assert _check(edge.sign(_NOW, aud=[AUDIENCE]), terms) is AssertionFault.AUDIENCE
    assert _check(edge.sign(_NOW, aud=[AUDIENCE, "other"]), terms) is AssertionFault.AUDIENCE


@pytest.mark.parametrize("sub", ["acct_7f3a9c03", "ACCT_7F3A9C02", "acct_7f3a9c02 ", OMIT, 0])
def test_another_subject_is_refused(sub: object, edge: FakeEdge, terms: EdgeTerms) -> None:
    """§6:8: "``sub`` claim equals ``gateway_edge_subject``, compared literally" — so
    the edge's other accounts, including the operator's, are refused here (§13:1)."""
    assert _check(edge.sign(_NOW, sub=sub), terms) is AssertionFault.SUBJECT


# --- §6:10: the times, with no leeway --------------------------------------------------


def test_an_assertion_issued_in_the_future_is_refused(edge: FakeEdge, terms: EdgeTerms) -> None:
    """§6:10: "``iat`` is not after the gateway's present time". No leeway: one second
    ahead is ahead."""
    token = edge.sign(_NOW + timedelta(seconds=1))

    assert _check(token, terms) is AssertionFault.TIMES


def test_an_assertion_issued_now_is_accepted(edge: FakeEdge, terms: EdgeTerms) -> None:
    """``iat`` equal to the present is not after it."""
    assert _check(edge.sign(_NOW), terms, now=_NOW) is None


def test_an_expired_assertion_is_refused(edge: FakeEdge, terms: EdgeTerms) -> None:
    """§6:10: "``exp`` is after it" — so ``exp`` equal to the present has expired."""
    token = edge.sign(_NOW, lifetime=30)

    assert _check(token, terms, now=_NOW + timedelta(seconds=29)) is None
    assert _check(token, terms, now=_NOW + timedelta(seconds=30)) is AssertionFault.TIMES
    assert _check(token, terms, now=_NOW + timedelta(seconds=31)) is AssertionFault.TIMES


def test_an_assertion_not_yet_valid_is_refused(edge: FakeEdge, terms: EdgeTerms) -> None:
    """§6:10: "any ``nbf`` it carries is not after it"."""
    later = edge.sign(_NOW, extra={"nbf": (_NOW + timedelta(seconds=5)).timestamp()})
    now = edge.sign(_NOW, extra={"nbf": _NOW.timestamp()})

    assert _check(later, terms) is AssertionFault.TIMES
    assert _check(now, terms) is None


@pytest.mark.parametrize("claim", ["iat", "exp"])
def test_an_assertion_missing_a_time_is_refused(
    claim: str, edge: FakeEdge, terms: EdgeTerms
) -> None:
    """§6:10: "accepted only when it carries ``iat`` and ``exp``"."""
    if claim == "iat":
        token = edge.sign(_NOW, iat=OMIT, exp=_NOW.timestamp() + 30)
    else:
        token = edge.sign(_NOW, exp=OMIT)

    assert _check(token, terms) is AssertionFault.TIMES


@pytest.mark.parametrize("value", [True, "1760788800", {}, [1]])
def test_a_time_that_is_not_a_number_is_refused(
    value: object, edge: FakeEdge, terms: EdgeTerms
) -> None:
    """A NumericDate is a number (RFC 7519 §2); ``True`` is an ``int`` to Python and a
    date to nobody."""
    token = edge.sign(_NOW, exp=value)

    assert _check(token, terms) is AssertionFault.TIMES


@pytest.mark.parametrize("value", [True, "x"])
def test_a_not_before_that_is_not_a_number_is_refused(
    value: object, edge: FakeEdge, terms: EdgeTerms
) -> None:
    """An ``nbf`` the gateway cannot read is not one it may ignore."""
    assert _check(edge.sign(_NOW, extra={"nbf": value}), terms) is AssertionFault.TIMES


def test_an_assertion_living_longer_than_the_bound_is_refused(
    edge: FakeEdge, terms: EdgeTerms
) -> None:
    """§6:10: "``exp`` is no more than ``gateway_edge_assertion_max_age`` after ``iat``"
    — sixty seconds by default (§6:11)."""
    assert _check(edge.sign(_NOW, lifetime=60), terms) is None
    assert _check(edge.sign(_NOW, lifetime=60.001), terms) is AssertionFault.TIMES
    assert _check(edge.sign(_NOW, lifetime=3600), terms) is AssertionFault.TIMES


def test_the_lifetime_bound_is_the_configured_one(edge: FakeEdge) -> None:
    """§6:11's figure, read from the setting."""
    terms = edge_terms(
        Settings(**edge.settings(gateway_edge_assertion_max_age=timedelta(seconds=10)))
    )
    assert terms is not None

    assert _check(edge.sign(_NOW, lifetime=10), terms) is None
    assert _check(edge.sign(_NOW, lifetime=11), terms) is AssertionFault.TIMES


def test_the_order_is_signature_before_any_claim(terms: EdgeTerms) -> None:
    """A stranger's token with every claim wrong is refused on its signature: nothing
    an unauthenticated peer wrote into the claims is read at all."""
    token = FakeEdge().sign(_NOW, iss="x", aud="y", sub="z", lifetime=1e9)

    assert _check(token, terms) is AssertionFault.SIGNATURE


# --- §6:14: no failure admits anything --------------------------------------------


class _Exploding:
    """A key whose verification raises something no one planned for."""

    def verify(self, signature: bytes, data: bytes) -> None:
        msg = "the library broke"
        raise RuntimeError(msg)


def test_a_failure_the_check_did_not_foresee_is_a_refusal(edge: FakeEdge) -> None:
    """§6:14: "A gateway that cannot verify an assertion, for any reason, refuses the
    request. No failure of the check admits anything." """
    terms = EdgeTerms(
        keys=(_Exploding(),),  # type: ignore[arg-type] # the point of the case
        issuer="i",
        audience="a",
        subject="s",
        max_age=timedelta(seconds=60),
    )

    assert _check(edge.sign(_NOW), terms) is AssertionFault.MALFORMED


def test_a_refusal_carries_nothing_of_the_token(edge: FakeEdge, terms: EdgeTerms) -> None:
    """§9:2: the gateway places none "into any error or diagnostic". The check answers
    with a fault, which is a fixed value, and never with anything built from the
    token."""
    token = edge.sign(_NOW, sub="someone-else")
    fault = _check(token, terms)

    assert fault is AssertionFault.SUBJECT
    for part in token.split("."):
        assert part not in repr(fault)


# --- the terms, read once from configuration -----------------------------------------


def test_no_terms_where_the_hosted_listener_is_off() -> None:
    """§5:1: off unless configured on, so nothing is read."""
    assert edge_terms(Settings()) is None


def test_the_terms_never_show_the_subject(terms: EdgeTerms) -> None:
    """§7:8: no record carries the subject, and a repr is how one would get into a
    diagnostic by accident."""
    assert "acct_7f3a9c02" not in repr(terms)
    assert "acct_7f3a9c02" not in str(terms)


def test_a_key_the_library_cannot_load_is_refused_at_start(
    monkeypatch: pytest.MonkeyPatch, edge: FakeEdge
) -> None:
    """§6:4: a set of Ed25519 public keys. ``Settings`` refuses one of the wrong length;
    a key ``cryptography`` will not load is refused here, before anything binds."""
    settings = Settings(**edge.settings())

    def refuse(_raw: bytes) -> None:
        msg = "not a point"
        raise ValueError(msg)

    monkeypatch.setattr(
        "ai_assistant.interfaces.gateway.edge.Ed25519PublicKey.from_public_bytes", refuse
    )
    with pytest.raises(ConfigurationError, match="gateway_edge_public_keys"):
        edge_terms(settings)


def test_a_key_is_the_raw_32_bytes_and_nothing_wrapped_around_them() -> None:
    """The form the setting takes (RFC 8037 §2's ``x``), decoded to the key the edge
    holds the private half of."""
    private = Ed25519PrivateKey.generate()
    edge = FakeEdge(key=private)
    raw = base64.urlsafe_b64decode(edge.public_key + "=")

    assert len(raw) == 32
    assert json.loads(json.dumps(edge.public_key)) == edge.public_key
