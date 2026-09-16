"""The terminal surface for ADR-0254 §11: the projection, the listing, the withdrawal.

**Every case is asserted over what the user reads**, because §11's obligations are
discharged in the rendering and nowhere else: *"A confirmation that establishes a bound
without naming it is not a confirmation of that bound"*, and the rendering bar is a
statement about characters on a screen.

The browser's twin is ``tests/interfaces/gateway/test_browser_authorizations.py`` and the
two are written against the same clauses deliberately — ADR-0250's M4 review found three
rounds spent fixing one surface and leaving the other, so the parity is asserted rather
than left to two readings.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO
from typing import Final

import pytest
import typer.main
from rich.console import Console
from test_cli_decisions import _flat
from typer.testing import CliRunner

from ai_assistant.core.types import (
    AuthorizationProjection,
    AuthorizationSettlement,
    AuthorizationView,
    BoundKind,
    CoverageView,
    QuoteView,
    ToolDefinition,
)
from ai_assistant.interfaces import cli
from ai_assistant.testing import (
    AUTHORIZATION_EXPIRES_AT,
    AUTHORIZATION_NOW,
    AUTHORIZATION_TOOL,
    FakeAssistantEngine,
    authorization,
    authorization_basis,
    coverage_member,
    money_bound,
    opening_act,
    period_bound,
    terms_bound,
)

#: The goal every listing here is about, and the statement §11 renders it by.
GOAL: Final = "goal-0001"
STATEMENT: Final = "book the campsite"

#: A terminal control character, so a handle that cannot be pasted is built from a value
#: rather than from an escape this file would then carry literally.
BELL: Final = chr(7)


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it."""
    buffer = StringIO()
    # **Wide**, so a rendering assertion is about what the surface writes rather than
    # about where Rich happened to fold it: `_print_hint` emits its command unfolded and
    # every other line here is prose the console wraps.
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=400))
    return buffer


def _view(**overrides: object) -> AuthorizationView:
    """One standing record, as ``standing_authorizations`` answers with it."""
    fields: dict[str, object] = {
        "id": "auth-1",
        "goal_statement": STATEMENT,
        "tool": AUTHORIZATION_TOOL,
        "coverage": (
            CoverageView(kind=BoundKind.MONEY, bound=money_bound("60"), span="under sixty pounds"),
        ),
        "expires_at": AUTHORIZATION_EXPIRES_AT,
        "live": True,
    }
    return AuthorizationView.model_validate(fields | overrides)


# --- §11 at the question ------------------------------------------------------


def test_the_confirmation_says_what_answering_would_leave_standing(output: StringIO) -> None:
    """§11: every fixed value, every bound the answer would establish, and the expiry.

    And the **span beside each**, because ADR-0254 §8 makes both halves survive: someone
    reading *"under sixty pounds"* beside a bound of GBP 60 can check the working before
    they answer rather than only after.

    **Each member is named by its kind** (ADR-0266 §9's §11 scope): *this kind of
    value is fixed at that value*, or *bounded by that limit*, where the argument key
    used to stand. A member names no argument, so a surface naming one would be
    inventing it.
    """
    projection = AuthorizationProjection(
        coverage=(
            CoverageView(kind=BoundKind.MONEY, bound=money_bound("60"), span="under sixty pounds"),
            CoverageView(kind=BoundKind.TERMS, fixed="A", span="the one by the lake"),
        ),
        expires_at=AUTHORIZATION_EXPIRES_AT,
        quote=None,
    )

    cli._render_confirmation_authorization(projection)

    rendered = _flat(output.getvalue())
    assert "standing authority" in rendered
    assert "the amount: up to 60 GBP" in rendered
    assert "under sixty pounds" in rendered
    assert "the terms: fixed at A" in rendered
    assert "the one by the lake" in rendered
    assert "2026-09-13 21:00 UTC" in rendered


def test_the_confirmation_says_nothing_where_answering_establishes_nothing(
    output: StringIO,
) -> None:
    """ADR-0178 §4's discriminator: absence is absence.

    A sentence on every ordinary confirmation saying *"this establishes nothing
    standing"* would be noise on the overwhelming majority of them, and the one-call
    reading is the default a user already holds.
    """
    cli._render_confirmation_authorization(None)

    assert output.getvalue() == ""


def test_an_empty_coverage_says_what_it_covers_rather_than_nothing(output: StringIO) -> None:
    """§20 arm 54: an empty projection is an authority over an **argument-free** call.

    A blank here would read as *"no limits"*, which is the opposite of what the record
    says: *"An empty `coverage` is an authority over an argument-free call and is a
    wildcard over nothing"*.
    """
    cli._render_confirmation_authorization(
        AuthorizationProjection(coverage=(), expires_at=AUTHORIZATION_EXPIRES_AT, quote=None)
    )

    rendered = _flat(output.getvalue())
    assert "no argument of yours" in rendered
    assert "not permission for anything wider" in rendered


def test_the_question_names_no_identifier(output: StringIO) -> None:
    """§11: *"The confirmation's projection names no identifier"*.

    Asserted over the whole rendering rather than over the member, because the surface
    is what the clause is about — and the row this projection was taken from carries a
    goal id, a row id and a connection reference.
    """
    row = authorization(id="auth-secret", goal="goal-secret")
    cli._render_confirmation_authorization(
        AuthorizationProjection(
            coverage=(
                CoverageView(kind=BoundKind.MONEY, bound=money_bound(), span="up to fifty pounds"),
            ),
            expires_at=row.expires_at,
            quote=None,
        )
    )

    rendered = _flat(output.getvalue())
    assert "auth-secret" not in rendered
    assert "goal-secret" not in rendered
    assert row.account.reference not in rendered
    assert row.subject_digest not in rendered


def test_the_projection_is_rendered_before_the_answer_is_collected(output: StringIO) -> None:
    """ADR-0233 §8's ordering clause, read onto §11's projection.

    The whole of what the answer establishes is above the prompt, so a user who answers
    has been shown it — which is what makes it *"a confirmation of that bound"*.
    """
    confirmation = FakeAssistantEngine().park(
        "h-1",
        authorization=AuthorizationProjection(
            coverage=(
                CoverageView(kind=BoundKind.MONEY, bound=money_bound(), span="up to fifty pounds"),
            ),
            expires_at=AUTHORIZATION_EXPIRES_AT,
            quote=None,
        ),
    )

    assert cli._render_confirmation(confirmation) is True
    rendered = _flat(output.getvalue())
    assert rendered.index("Why:") < rendered.index("standing authority")


#: The figure a proposed row was built over, and the instant it was read (ADR-0267 §7).
#:
#: **An amount with a fractional part and a currency that is not the bound's**, so an arm
#: asserting the figure cannot pass on the ceiling beside it: a quote of ``50 GBP`` under a
#: ceiling of ``up to 50 GBP`` would be satisfied by a surface that rendered the bound twice.
QUOTE: Final = QuoteView(
    amount=Decimal("45.50"), currency="EUR", read_at=AUTHORIZATION_NOW - timedelta(hours=2)
)


def test_the_confirmation_names_the_figure_the_act_was_quoted_at(output: StringIO) -> None:
    """ADR-0267 §7, beside the ceiling: *"A confirmation that renders a ceiling without
    the figure the act was quoted at is not a confirmation of that charge"*.

    **All three values of the** :class:`~ai_assistant.core.types.QuoteView`, because §6
    rests the disclosure on the number *and* on how old it is: a figure with no instance
    of when it was read is half of what the clause requires on the screen.

    **Beside and not in place of**: the bound the answer would establish is still
    rendered, which is why the quote here is a different amount in a different currency
    from the ceiling above it.
    """
    cli._render_confirmation_authorization(
        AuthorizationProjection(
            coverage=(
                CoverageView(kind=BoundKind.MONEY, bound=money_bound("60"), span="under sixty"),
            ),
            expires_at=AUTHORIZATION_EXPIRES_AT,
            quote=QUOTE,
        )
    )

    rendered = _flat(output.getvalue())
    assert "45.50" in rendered
    assert "EUR" in rendered
    assert "2026-09-13 08:00 UTC" in rendered
    # The ceiling is still there, in the currency the *bound* carries.
    assert "the amount: up to 60 GBP" in rendered


def test_the_figure_is_disclosed_and_is_never_offered_as_a_check(output: StringIO) -> None:
    """ADR-0267 §6: *"That is a disclosure and not a check"*.

    **No sentence makes the owner's answer a warrant that the price is still current**,
    and the surface says so rather than leaving a bare figure to be read as one: nothing
    expires a quote, no comparison reads its age, and the window between the reading and
    the charge is open (§6). What is asserted here is the fact stated, not its wording —
    the rendering must not claim the figure is held, guaranteed or current.
    """
    cli._render_confirmation_authorization(
        AuthorizationProjection(coverage=(), expires_at=AUTHORIZATION_EXPIRES_AT, quote=QUOTE)
    )

    rendered = _flat(output.getvalue())
    assert "not a warrant that it is still current" in rendered
    for claim in ("guaranteed", "held for you", "price is current", "locked"):
        assert claim not in rendered, claim


def test_no_quote_prints_no_line_about_one(output: StringIO) -> None:
    """ADR-0178 §4, one member in: absence prints nothing at all.

    ADR-0267 §7 gives the field three absent cases on the one write path that sets it —
    no ``MONEY`` member, no intended action, or no quote of the goal naming that action —
    and none of them is a figure this surface could invent. The projection around it
    still renders whole.
    """
    cli._render_confirmation_authorization(
        AuthorizationProjection(
            coverage=(
                CoverageView(kind=BoundKind.MONEY, bound=money_bound("60"), span="under sixty"),
            ),
            expires_at=AUTHORIZATION_EXPIRES_AT,
            quote=None,
        )
    )

    rendered = _flat(output.getvalue())
    assert "quoted at" not in rendered
    assert "still current" not in rendered
    assert "the amount: up to 60 GBP" in rendered


# --- §11's listing ------------------------------------------------------------


async def test_the_listing_renders_the_goal_by_statement_and_offers_the_withdrawal(
    output: StringIO,
) -> None:
    """§11's listing, field by field, and §20 arm 62's bar.

    The goal by its **statement**, the declaration by its own identifier and
    description, each member as a statement with the words behind it, the horizon, and
    the row's ``id`` — which is here because it is the **revocation handle**.
    """
    engine = FakeAssistantEngine()
    engine.hold_authorization(
        opening_act(
            id="auth-1",
            goal=GOAL,
            coverage=(
                coverage_member(
                    BoundKind.MONEY,
                    bound=money_bound("50"),
                    basis=authorization_basis(span="up to fifty pounds"),
                ),
            ),
            expires_at=AUTHORIZATION_NOW + timedelta(hours=1),
        ),
        goal_statement=STATEMENT,
    )

    code = await cli._drive_authorizations(engine, GOAL)

    assert code == cli._EXIT_OK
    rendered = _flat(output.getvalue())
    assert rendered.count(STATEMENT) == 1, "the goal is named once and not once per row"
    assert GOAL not in rendered, "ADR-0254 §11 renders a goal by statement and never by id"
    assert AUTHORIZATION_TOOL.id in rendered
    assert "up to 50 GBP" in rendered
    assert "up to fifty pounds" in rendered
    assert "still stands" in rendered
    assert "assistant revoke-authorization auth-1" in rendered


async def test_the_listing_says_a_lapsed_record_has_lapsed_and_still_offers_it(
    output: StringIO,
) -> None:
    """§16 returns a lapsed row deliberately: *"a user can see and revoke what they once
    authorised"* — ADR-0193 §9's own reason one store over, and why the withdrawal path
    needs no history query.
    """
    engine = FakeAssistantEngine()
    engine.hold_authorization(
        opening_act(id="auth-old", goal=GOAL, expires_at=AUTHORIZATION_NOW - timedelta(minutes=1)),
        goal_statement=STATEMENT,
    )

    await cli._drive_authorizations(engine, GOAL)

    rendered = _flat(output.getvalue())
    assert "has lapsed" in rendered
    assert "assistant revoke-authorization auth-old" in rendered


async def test_the_listing_claims_nothing_about_the_next_call(output: StringIO) -> None:
    """§11: *"The listing is a record of what the user authorised and is not a promise
    that the next call will be allowed"* — ``decide`` is the only thing that answers
    that, and the surface says so rather than leaving the reader to infer it.
    """
    engine = FakeAssistantEngine()
    engine.hold_authorization(opening_act(id="auth-1", goal=GOAL), goal_statement=STATEMENT)

    await cli._drive_authorizations(engine, GOAL)

    assert "not a promise that the next call will go through" in _flat(output.getvalue())


async def test_an_empty_listing_is_a_sentence_and_not_a_blank(output: StringIO) -> None:
    """A goal holding no authority answers empty, and the surface says what that means:
    every call for that piece of work is put to the user as it comes up.
    """
    code = await cli._drive_authorizations(FakeAssistantEngine(), GOAL)

    assert code == cli._EXIT_OK
    assert "Nothing standing" in _flat(output.getvalue())


def test_every_bound_kind_renders_as_its_own_statement(output: StringIO) -> None:
    """ADR-0254 §2's three kinds, one statement each and no fourth.

    A bound rendered as a bare figure would lose which comparison it is — the
    asymmetric failure §2 states the enumeration against.
    """
    cli._render_coverage(
        (
            CoverageView(kind=BoundKind.MONEY, bound=money_bound("60"), span="under sixty"),
            CoverageView(kind=BoundKind.PERIOD, bound=period_bound(), span="this weekend"),
            CoverageView(
                kind=BoundKind.TERMS,
                bound=terms_bound("refundable", "flexible"),
                span="cancellable",
            ),
        ),
        indent="  ",
    )

    rendered = _flat(output.getvalue())
    assert "up to 60 GBP" in rendered
    assert "up to but not including" in rendered
    assert "Europe/London" in rendered
    assert "one of: refundable, flexible" in rendered


def test_a_strict_ceiling_is_said_strictly_and_never_as_an_inclusive_one(
    output: StringIO,
) -> None:
    """ADR-0266 §3: *"under 100"* and *"at most 100"* stopped being one value.

    **The two render differently or the screen misstates the authority.** A rendering
    saying *"up to"* for both shows the owner a limit a cent wider than the one they
    are about to establish — and this is the one surface §11 exists to make the
    working checkable on, so the permissive direction here is exactly the one ADR-0254
    §2's asymmetry names.
    """
    cli._render_coverage(
        (
            CoverageView(
                kind=BoundKind.MONEY,
                bound=money_bound("100", maximum_exclusive=True),
                span="under 100 euros",
            ),
        ),
        indent="  ",
    )

    rendered = _flat(output.getvalue())
    assert "the amount: under 100 GBP" in rendered
    assert "up to" not in rendered


def test_a_money_bound_with_a_floor_states_both_ends(output: StringIO) -> None:
    """§2's ``MONEY`` kind carries an optional ``minimum``, and a rendering that dropped
    it would understate what the act permitted.
    """
    cli._render_coverage(
        (
            CoverageView(
                kind=BoundKind.MONEY,
                bound=money_bound("60", minimum="10"),
                span="between ten and sixty",
            ),
        ),
        indent="  ",
    )

    assert "from 10 GBP up to 60 GBP" in _flat(output.getvalue())


def test_a_handle_that_cannot_be_pasted_is_not_offered_as_a_command(output: StringIO) -> None:
    """The ``_is_pasteable``/``_uncopyable`` pair, on this surface's own handle.

    ADR-0254 §11 puts the id on screen because it is the revocation handle; a handle a
    terminal cannot render is one a printed command would name **wrongly**, so the
    command is withheld and the reason is stated.
    """
    cli._render_authorization(_view(id=f"auth{BELL}bell"), with_goal=False)

    rendered = _flat(output.getvalue())
    assert "assistant revoke-authorization" not in rendered
    assert "cannot show" in rendered


# --- §11's withdrawal, and §16's four members --------------------------------


@pytest.mark.parametrize("settlement", list(AuthorizationSettlement))
def test_every_settlement_member_renders_as_its_own_statement(
    settlement: AuthorizationSettlement, output: StringIO
) -> None:
    """The enumeration arm: **all four**, and none as silence.

    ``WOULD_DUPLICATE`` is unreachable on this surface — it is reachable only on a
    settlement to ``ESTABLISHED`` and a withdrawal settles to ``REVOKED`` — and it is
    given a sentence anyway, because the closed vocabulary crosses a version boundary
    and a member with no sentence renders as nothing at all.

    **And none of them is rendered as a fault**: each says what the store found, and the
    two that moved nothing are the store working rather than failing.
    """
    cli._render_authorization_settlement(settlement, "auth-1")

    rendered = _flat(output.getvalue())
    assert rendered.strip(), f"{settlement} renders as silence"
    assert settlement.value not in rendered, "the member's own spelling is not the sentence"


async def test_the_withdrawal_says_what_it_does_not_do(output: StringIO) -> None:
    """§11: revocation is **whole** and **prospective**.

    *"A recorded `ALLOW` stays recorded, stays true about the moment it was made"*, so
    the surface says what is not undone rather than letting a user read the act as wider
    than it is.
    """
    engine = FakeAssistantEngine()
    engine.hold_authorization(opening_act(id="auth-1", goal=GOAL), goal_statement=STATEMENT)

    code = await cli._drive_revoke_authorization(engine, "auth-1")

    assert code == cli._EXIT_OK
    rendered = _flat(output.getvalue())
    assert "Withdrawn." in rendered
    assert "Nothing already decided is rewritten" in rendered


async def test_withdrawing_a_question_the_user_never_answered_says_so(output: StringIO) -> None:
    """§1's graph: a ``PROPOSED`` row is not revocable, and that is not an omission.

    *"A question the user has not answered is withdrawn by declining it or by letting it
    lapse"*, and the surface says which act to take rather than reporting a failure.
    """
    engine = FakeAssistantEngine()
    engine.hold_authorization(
        authorization(id="auth-open", goal=GOAL, confirmation="d-1"), goal_statement=STATEMENT
    )

    await cli._drive_revoke_authorization(engine, "auth-open")

    rendered = _flat(output.getvalue())
    assert "Nothing to withdraw" in rendered
    assert "declining it" in rendered


async def test_an_unknown_handle_is_a_result_and_never_a_stack_trace(output: StringIO) -> None:
    """``AssistantEngineContract::test_a_refusal_is_a_result_and_not_an_exception``."""
    code = await cli._drive_revoke_authorization(FakeAssistantEngine(), "auth-nobody")

    assert code == cli._EXIT_OK
    assert "no record" in _flat(output.getvalue())


async def test_the_withdrawal_takes_no_read_back_to_decide_what_it_says() -> None:
    """One call and no second one, on ``_render_recipient_grant_outcome``'s reason one
    store over: the settlement already says exactly what happened, and a listing taken
    after it could not tell *withdrawn* from *was already gone* apart.
    """
    engine = FakeAssistantEngine()
    engine.hold_authorization(opening_act(id="auth-1", goal=GOAL), goal_statement=STATEMENT)

    await cli._drive_revoke_authorization(engine, "auth-1")

    assert [name for name, _ in engine.calls] == ["revoke_authorization"]


# --- §11's announcement -------------------------------------------------------


def test_an_act_that_opened_two_authorities_is_announced_as_two(output: StringIO) -> None:
    """§20 arm 64: *"two rows, two views, two different bounds"*, each naming its own
    declaration. **A lane that merged them fails this arm**, and so does one that
    announced only the first.
    """
    rail = ToolDefinition.model_validate(AUTHORIZATION_TOOL.model_dump() | {"id": "rail"})
    hotels = ToolDefinition.model_validate(AUTHORIZATION_TOOL.model_dump() | {"id": "hotels"})

    cli._render_opened_authorizations(
        (
            _view(
                id="auth-train",
                tool=rail,
                coverage=(
                    CoverageView(
                        kind=BoundKind.MONEY, bound=money_bound("50"), span="fifty for the train"
                    ),
                ),
            ),
            _view(
                id="auth-hotel",
                tool=hotels,
                coverage=(
                    CoverageView(
                        kind=BoundKind.MONEY,
                        bound=money_bound("100"),
                        span="a hundred for the hotel",
                    ),
                ),
            ),
        )
    )

    rendered = _flat(output.getvalue())
    assert "rail" in rendered
    assert "hotels" in rendered
    assert "up to 50 GBP" in rendered
    assert "up to 100 GBP" in rendered
    assert "assistant revoke-authorization auth-train" in rendered
    assert "assistant revoke-authorization auth-hotel" in rendered


def test_a_turn_that_opened_none_announces_nothing(output: StringIO) -> None:
    """§11: *"It is **empty** on every turn that opened none"* — including a turn that
    only re-grounds an existing constraint, which ADR-0250 §5 requires to stay
    unannounced and which is why this member exists rather than riding that one.
    """
    cli._render_opened_authorizations(())

    assert output.getvalue() == ""


# --- the command surface ------------------------------------------------------


def test_the_two_command_names_are_the_ones_the_surface_owes() -> None:
    """Two operations and no third (ADR-0254 §16's closed roster), named on the terminal
    for the vocabulary they belong to: ``grant``, ``revoke`` and ``grants`` already have
    a referent on this surface and it is ``SourceGrant`` — so these qualify, exactly as
    ADR-0235 §7's recipient commands do.
    """
    group = typer.main.get_command(cli.app)
    names = set(group.commands)  # type: ignore[attr-defined]

    assert {"authorizations", "revoke-authorization"} <= names


def test_the_withdrawal_asks_no_question_and_takes_no_second_argument() -> None:
    """§11: withdrawal is **whole**, so there is no narrowing to express — and it is
    *"never refused for a ceiling"*, so nothing here offers a force flag either.
    """
    group = typer.main.get_command(cli.app)
    command = dict(group.commands)["revoke-authorization"]  # type: ignore[attr-defined]

    assert {str(one.name) for one in command.params} == {"authorization_id"}


def test_the_listing_command_takes_a_goal_and_no_limit() -> None:
    """§11: *"It takes no `limit`"* — a truncated answer to *"what do I authorise"* is a
    false answer rather than a partial one, so there is no page to ask for.
    """
    group = typer.main.get_command(cli.app)
    command = dict(group.commands)["authorizations"]  # type: ignore[attr-defined]

    assert {str(one.name) for one in command.params} == {"goal_id"}


def test_the_commands_refuse_a_blank_identifier_before_any_call() -> None:
    """The ``_present_id`` callback both commands carry, exercised through the shell."""
    result = CliRunner().invoke(cli.app, ["authorizations", "   "])
    withdrawal = CliRunner().invoke(cli.app, ["revoke-authorization", "   "])

    assert result.exit_code != 0
    assert withdrawal.exit_code != 0
