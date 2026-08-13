"""ADR-0140 §12's table: disabled by default, and refused where §12 says it is.

Two seams state the same rules and both are tested here, because they are reached
independently. :class:`~ai_assistant.core.config.Settings` is what a deployment
configures; ``EmailReader.__init__`` is what a test or a second composition root
reaches directly, and ADR-0093 §10 names the constructor half explicitly —
"``Reader`` specifies no constructor and no configuration surface … so a generic
suite has nothing to over-supply. It is a concrete reader's test and a
``Settings`` test."

The defaults are duplicated across the two modules rather than imported, because
``core`` depends on nothing else in ``ai_assistant`` (golden rule 2) and the
dependency can only point one way. That duplication is exactly what
:func:`test_the_settings_defaults_are_the_readers_defaults` exists to keep from
drifting: a "bounded default" that two conforming layers disagree about is
ADR-0074 §9.3's failure with the ADR's own figures in it.

**The range worth the most here is ``email_window_past``'s open lower bound.**
``calendar_window_past`` may be zero and ``test_calendar_settings.py`` asserts
that it is accepted, while this one may not be — so a lane that reaches for the
neighbouring field declaration inherits a ``ge=0`` and ships a reader that reads
nothing while reporting health. The two assertions are deliberately made in the
same suite so the asymmetry is visible rather than surprising.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import _MAX_EMAIL_WINDOW, Settings, load_settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.readers import (
    DEFAULT_EMAIL_MAX_BYTES,
    DEFAULT_EMAIL_MAX_CONTENT_BYTES,
    DEFAULT_EMAIL_MAX_MESSAGES,
    DEFAULT_EMAIL_READ_TIMEOUT,
    DEFAULT_EMAIL_WINDOW_PAST,
    MAX_EMAIL_WINDOW,
    EmailReader,
)

_ABSOLUTE = Path("/srv/mail/inbox.mbox")


@pytest.fixture(autouse=True)
def _no_email_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's own ``.env`` out of the defaults being asserted."""
    for name in (
        "ASSISTANT_EMAIL_SOURCE_PATH",
        "ASSISTANT_EMAIL_READER_INTERVAL",
        "ASSISTANT_EMAIL_WINDOW_PAST",
        "ASSISTANT_EMAIL_MAX_MESSAGES",
    ):
        monkeypatch.delenv(name, raising=False)


# --- disabled by default (ADR-0093 §7, ADR-0140 §12) ------------------------


def test_the_email_reader_ships_disabled() -> None:
    """Both nullable fields ``None``, so a fresh install reads no mail.

    ADR-0093 §7's reason unchanged — "nothing may read a user's personal files
    because a default said so" — and it places the default correctly relative to
    the grant question, which for this source has a second edge: the store's
    *contents* arrive on the box through a process the operator started, so a
    default that read it would be reading mail nobody in this system was ever asked
    about (ADR-0140 §9).
    """
    settings = Settings()

    assert settings.email_source_path is None
    assert settings.email_reader_interval is None


def test_the_settings_defaults_are_the_readers_defaults() -> None:
    """The figures ADR-0140 §12 names, agreeing across the two layers that hold them."""
    settings = Settings()

    assert settings.email_window_past == DEFAULT_EMAIL_WINDOW_PAST == timedelta(days=7)
    assert settings.email_max_messages == DEFAULT_EMAIL_MAX_MESSAGES == 2_000
    assert settings.email_max_bytes == DEFAULT_EMAIL_MAX_BYTES == 8 * 1024 * 1024
    assert settings.email_read_timeout == DEFAULT_EMAIL_READ_TIMEOUT == timedelta(seconds=10)
    assert settings.email_max_content_bytes == DEFAULT_EMAIL_MAX_CONTENT_BYTES == 4 * 1024 * 1024
    assert _MAX_EMAIL_WINDOW == MAX_EMAIL_WINDOW == timedelta(days=3650)


def test_the_table_is_seven_fields_and_a_field_added_is_a_decision() -> None:
    """§12 says "exactly these seven", and the absences are as decided as the entries.

    No ``email_window_future``, because a mailbox has no future and the field would
    bound nothing. No expansion budget, because a mailbox has no generator — the
    messages in the store are the messages. And **no field carrying the account or
    its credential**: the reader's identity is the declared constant ``"email"``,
    and ADR-0140 §11 keeps the credential the operator's and the fetcher's, because
    a hub that held one would have to *use* it, which means speaking IMAP.
    """
    email_fields = {name for name in Settings.model_fields if name.startswith("email_")}

    assert email_fields == {
        "email_source_path",
        "email_reader_interval",
        "email_window_past",
        "email_max_messages",
        "email_max_bytes",
        "email_read_timeout",
        "email_max_content_bytes",
    }


# --- shape at load, existence at run time (ADR-0093 §7) ---------------------


def test_a_relative_source_path_is_refused_at_load() -> None:
    with pytest.raises(ValidationError, match="absolute path"):
        Settings(email_source_path=Path("mail/inbox.mbox"))


def test_a_source_path_is_expanded_but_not_required_to_exist() -> None:
    """A file's existence is a property of the world at an instant, not of the config.

    Here the split matters more than it does for a calendar: the store is written
    by a process outside this system entirely, so "the fetcher has not run yet" is
    an ordinary first-boot state — and a hub that refused to start over it would
    make an advisory source a boot dependency on a component it does not supervise.
    """
    assert Settings(email_source_path=_ABSOLUTE).email_source_path == _ABSOLUTE

    expanded = Settings(email_source_path=Path("~/mail/inbox.mbox")).email_source_path
    assert expanded is not None
    assert expanded.is_absolute()
    assert not str(expanded).startswith("~")


def test_an_interval_with_no_source_is_refused_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one incoherent state of the pair (ADR-0140 §12).

    The alternatives are all worse and all silently different: a scheduler that
    omits the requested job reports health while running nothing, one that arms it
    re-runs a failing job forever, and one that treats it as a source fault turns a
    configuration mistake into an infinite retry.
    """
    with pytest.raises(ValidationError, match="needs a source to read"):
        Settings(email_reader_interval=timedelta(hours=1))

    monkeypatch.setenv("ASSISTANT_EMAIL_READER_INTERVAL", "PT1H")
    with pytest.raises(ConfigurationError, match="invalid configuration"):
        load_settings()


def test_the_three_coherent_states_load() -> None:
    """Fully disabled, a source with no scheduled read, and both live."""
    assert Settings().email_reader_interval is None
    assert Settings(email_source_path=_ABSOLUTE).email_reader_interval is None
    both = Settings(email_source_path=_ABSOLUTE, email_reader_interval=timedelta(hours=6))
    assert both.email_reader_interval == timedelta(hours=6)


def test_disabled_is_none_and_never_zero() -> None:
    """ADR-0083 §7's convention, and its reason applies unmodified.

    The scheduler re-arms a job from its *completion*, so an interval of zero makes
    it due again the instant it finishes — and "off" and "as fast as possible" look
    identical in a config file.
    """
    with pytest.raises(ValidationError):
        Settings(email_source_path=_ABSOLUTE, email_reader_interval=timedelta(0))


# --- the ranges §12 names ----------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        # The open lower bound, which is the one this table does not share with
        # the calendar's.
        ("email_window_past", timedelta(0)),
        ("email_window_past", timedelta(seconds=-1)),
        ("email_window_past", timedelta(days=3651)),
        ("email_max_messages", 0),
        ("email_max_messages", 2**63),
        ("email_max_bytes", 0),
        ("email_max_content_bytes", 0),
        ("email_read_timeout", timedelta(0)),
    ],
)
def test_a_figure_outside_its_range_is_refused_at_load(field: str, value: object) -> None:
    """Refused at load rather than at the first run (ADR-0093 §5, ADR-0140 §12)."""
    kwargs: dict[str, Any] = {field: value}
    with pytest.raises(ValidationError):
        Settings(**kwargs)


def test_a_zero_window_is_refused_here_while_the_calendars_is_accepted() -> None:
    """The asymmetry stated as one assertion, because it is the trap §12 names.

    A calendar deployment that wants only what is ahead is coherent, so
    ``calendar_window_past`` may be zero. A mailbox has no future at all, so a zero
    ``email_window_past`` is not a narrower configuration — it is a reader that
    reads nothing while reporting health.
    """
    assert Settings(calendar_window_past=timedelta(0)).calendar_window_past == timedelta(0)

    with pytest.raises(ValidationError):
        Settings(email_window_past=timedelta(0))


# --- the constructor states the same rules (ADR-0093 §10) -------------------


def test_the_constructor_refuses_a_relative_path() -> None:
    with pytest.raises(ValueError, match="absolute path"):
        EmailReader(Path("inbox.mbox"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("window_past", timedelta(0)),
        ("window_past", timedelta(seconds=-1)),
        ("window_past", timedelta(days=3651)),
        ("max_messages", 0),
        ("max_messages", 2**63),
        ("max_bytes", 0),
        ("max_content_bytes", 0),
        ("read_timeout", timedelta(0)),
        # A flag is not a count, which is the rule the layers under `Settings`
        # already state at the seam a direct caller reaches (#471).
        ("max_messages", True),
        ("max_bytes", True),
        ("max_content_bytes", True),
    ],
)
def test_the_constructor_refuses_a_figure_outside_its_range(field: str, value: object) -> None:
    kwargs: dict[str, Any] = {field: value}
    with pytest.raises(ValueError, match=f"email_{field}"):
        EmailReader(_ABSOLUTE, **kwargs)
