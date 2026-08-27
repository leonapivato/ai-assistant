"""The value types the speech seams exchange (ADR-0200 §9).

Two properties carry the section: base64 that is *padded, standard and canonical*
— so one recording has exactly one spelling — and a value that is **never
normalised**, so what a caller passed is what crosses the wire and what
``decoded()`` reverses.

The rejection cases are written one per class of defect rather than as a table of
strings, because each names a different way a decoder could disagree with a peer,
and a reader should be able to see which one is missing if one ever is.
"""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import SpokenAudio, SpokenAudioFormat

#: Three octets, so the canonical encoding needs no padding at all.
_UNPADDED_SOURCE = b"abc"

#: One octet, so the canonical encoding ends in two padding characters — the
#: final group whose unused bits are what the canonicality clause is about.
_SHORT_SOURCE = b"a"


def _audio(content: str) -> SpokenAudio:
    return SpokenAudio(content=content, media_type=SpokenAudioFormat.WEBM_OPUS)


# --- what a recording is -----------------------------------------------------


def test_the_two_members_are_the_whole_of_it() -> None:
    assert set(SpokenAudio.model_fields) == {"content", "media_type"}


def test_it_is_frozen_and_forbids_extra_members() -> None:
    audio = _audio(base64.b64encode(_UNPADDED_SOURCE).decode("ascii"))

    with pytest.raises(ValidationError):
        audio.content = "QUJD"
    with pytest.raises(ValidationError):
        SpokenAudio(content="QUJD", media_type=SpokenAudioFormat.MP4, sample_rate=48000)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "source",
    [b"a", b"ab", b"abc", b"abcd", bytes(range(256)), b"\x1aE\xdf\xa3webm-ish header"],
    ids=["one", "two", "three", "four", "every-octet", "container-header"],
)
def test_decoding_returns_exactly_the_octets_encoded(source: bytes) -> None:
    # The byte-identity round trip ADR-0200 §9 asks for, over every final-group
    # remainder — the one place a base64 implementation can differ.
    audio = _audio(base64.b64encode(source).decode("ascii"))

    assert audio.decoded() == source


def test_the_spelling_is_carried_unchanged() -> None:
    # Not normalised: `content` is the string the caller passed, not a re-encoding
    # of what it decodes to. The two agree here by construction — that is what
    # canonicality buys — but the assertion is about which of them is stored.
    spelling = base64.b64encode(_SHORT_SOURCE).decode("ascii")

    assert _audio(spelling).content == spelling


# --- one defect class per case ----------------------------------------------


def test_an_alphabet_outside_rfc_4648_section_4_is_refused() -> None:
    # RFC 4648 §5's URL-safe alphabet is the case that matters: it is real base64
    # of the same octets, so admitting it would give one recording two values.
    urlsafe = base64.urlsafe_b64encode(b"\xff\xfe\xfd").decode("ascii")
    assert "-" in urlsafe or "_" in urlsafe

    with pytest.raises(ValidationError, match="alphabet"):
        _audio(urlsafe)


def test_missing_padding_is_refused() -> None:
    padded = base64.b64encode(_SHORT_SOURCE).decode("ascii")
    assert padded.endswith("==")

    with pytest.raises(ValidationError, match="padded"):
        _audio(padded.rstrip("="))


def test_a_non_canonical_final_group_is_refused() -> None:
    # "QQ==" and "QR==" both decode to b"A": the second sets bits the final group
    # does not use. Without the canonicality clause they would be two values for
    # one recording, and `wire/codec.py` would faithfully preserve the difference.
    assert base64.b64decode("QR==") == base64.b64decode("QQ==") == b"A"

    with pytest.raises(ValidationError, match="canonical"):
        _audio("QR==")


def test_embedded_whitespace_is_refused() -> None:
    # A decoder that skips whitespace would admit a payload a stricter peer
    # refuses, which is the interoperability half of the same clause.
    with pytest.raises(ValidationError, match="alphabet"):
        _audio("QU JD")


def test_a_length_that_is_not_a_whole_group_is_refused() -> None:
    with pytest.raises(ValidationError, match="multiple of 4"):
        _audio("QUJ")


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_blank_recording_is_refused(blank: str) -> None:
    # `""` has a length that is a multiple of four and decodes to `b""`, so the
    # non-blank refinement is doing work the group check does not: a recording
    # carrying no octets is not a recording.
    with pytest.raises(ValidationError, match="blank"):
        _audio(blank)


def test_a_refusal_does_not_echo_the_recording() -> None:
    # ADR-0200 §9's own clause about the message, which matters most here: the
    # value is a recording of the owner's voice, and a refusal is the one place
    # §8's retention rule cannot see. The *message* names the defect and the
    # position and nothing else; pydantic still attaches the input, which is why
    # §9 obliges every untrusted entry point to re-raise `from None` — the
    # obligation this test pins the necessary half of.
    clip = "QUJD" * 8 + "!"

    with pytest.raises(ValidationError) as caught:
        _audio(clip)

    [detail] = caught.value.errors()
    rendered = str(detail.get("ctx", {}).get("error", ""))
    assert clip not in rendered
    assert "position" in rendered


# --- the format vocabulary ---------------------------------------------------


def test_the_vocabulary_is_exactly_the_two_media_types() -> None:
    # ADR-0200 §9 fixes them, and adding a member takes a recorded measurement
    # while removing one takes a superseding ADR. Pinned so neither happens by
    # accident.
    assert {member.value for member in SpokenAudioFormat} == {
        "audio/webm;codecs=opus",
        "audio/mp4",
    }


def test_a_format_is_its_own_media_type_string() -> None:
    # The member *is* the header value, so nothing maps between the two.
    assert SpokenAudioFormat.WEBM_OPUS.value == "audio/webm;codecs=opus"


def test_an_unknown_media_type_is_refused() -> None:
    with pytest.raises(ValidationError):
        SpokenAudio(content="QUJD", media_type="audio/ogg")  # type: ignore[arg-type]
