"""The domains the upkeep runs tend, and the budget one firing shares (ADR-0384 §1:3, §3:4, §10).

What each job does with its domain is in its own module's tests: the scheduled tidy-up's
in ``test_scheduled_tidy_up.py`` and ``test_story_tidy_up.py``, the matters pass's in
``test_matters_pass.py``, and the reconsideration's in ``test_engine_notifications.py``.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from ai_assistant.core.types import RecordHome
from ai_assistant.orchestration.upkeep import RECONSIDERED, UPKEEP_DOMAINS, FiringBudget


def test_a_hub_with_one_person_has_two_domains_the_owners_first() -> None:
    """§1:3: the owner's domain and the hub's shared things, tended in that order."""
    assert (RecordHome.owners(), RecordHome.shared()) == UPKEEP_DOMAINS


def test_the_reconsideration_tends_the_owners_domain_alone() -> None:
    """§3:4: a held notification of another domain is left to the decision on whom it goes to."""
    assert RecordHome.owners() == RECONSIDERED


async def test_a_budget_no_run_started_is_never_spent() -> None:
    """A firing whose runs find nothing to do spends none of its budget."""
    budget = FiringBudget(timedelta(microseconds=1))

    await asyncio.sleep(0.01)

    assert budget.spent() is False


async def test_a_started_budget_is_spent_once_its_time_has_passed() -> None:
    budget = FiringBudget(timedelta(milliseconds=5))
    budget.start()
    assert budget.spent() is False

    await asyncio.sleep(0.02)

    assert budget.spent() is True


async def test_a_later_run_starting_the_budget_does_not_move_it() -> None:
    """The firing's runs share one budget: the second run's start leaves the first's."""
    budget = FiringBudget(timedelta(milliseconds=5))
    budget.start()
    await asyncio.sleep(0.02)

    budget.start()

    assert budget.spent() is True
