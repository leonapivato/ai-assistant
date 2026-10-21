"""The activation viewer's display of the hub's follow-up file (ADR-0337 §8:17).

The record is written as the hub writes it, through the package's own follow-up asker
around ADR-0314's own store (``_follow_up_record``), so a change to the line either side
reads fails here. The viewer is bound for real on loopback over it.
"""

from __future__ import annotations

import http.client
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _activation_record import serving, viewer
from _follow_up_record import (
    ACT_A,
    ACT_B,
    ACT_F,
    ANSWER,
    DIGEST_GIVEN,
    MODEL_NAME,
    PLANNING_GIVEN,
    PLANNING_RETURNED,
    SCOUT_GIVEN,
    UNDERSTANDING_GIVEN,
    UNDERSTANDING_RETURNED,
    write_followed,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration


@pytest.fixture
def record(tmp_path: Path) -> Path:
    return write_followed(tmp_path)


@pytest.fixture
def server(record: Path) -> Iterator[Any]:
    with serving(record) as bound:
        yield bound


def _json(port: int, path: str) -> Any:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
        response = connection.getresponse()
        assert response.status == 200
        return json.loads(response.read())
    finally:
        connection.close()


def test_a_follow_up_file_is_never_listed_as_an_activation(server: Any, record: Path) -> None:
    assert (record / f"{ACT_A}.followup.jsonl").is_file()
    assert (record / f"{ACT_B}.followup.jsonl").is_file()

    listed = {one["id"] for one in _json(server.port, "/api/activations")["activations"]}

    assert listed == {ACT_A, ACT_F}
    assert viewer.Record(record).listing().keys() == {ACT_A, ACT_F}
    assert viewer.Record(record).follow_up_listing().keys() == {ACT_A, ACT_B, ACT_F}


def test_a_follow_up_is_never_on_the_timeline(server: Any) -> None:
    shown = json.dumps(_json(server.port, f"/api/activation?id={ACT_A}"))

    assert ANSWER not in shown
    assert "follow_up" not in shown


@pytest.mark.parametrize("line", [UNDERSTANDING_GIVEN, UNDERSTANDING_RETURNED])
def test_a_completions_view_shows_its_follow_up_beside_it(server: Any, line: int) -> None:
    view = _json(server.port, f"/api/call?id={ACT_A}&line={line}")

    (asked,) = view["follow_ups"]
    assert asked["answer"]["text"] == ANSWER
    assert asked["failure"] is None
    assert asked["origin"] == "default"
    assert isinstance(asked["version"], str)
    assert asked["model"] == MODEL_NAME
    assert asked["followed_version"] == "0123456789ab"


@pytest.mark.parametrize("line", [PLANNING_GIVEN, PLANNING_RETURNED])
def test_a_rounds_view_shows_its_own_follow_up_and_no_other(server: Any, line: int) -> None:
    view = _json(server.port, f"/api/call?id={ACT_A}&line={line}")

    (asked,) = view["follow_ups"]
    assert asked["answer"]["text"] == ANSWER
    assert view["replays"] == []


def test_a_call_that_was_not_asked_shows_none(server: Any) -> None:
    """ADR-0337 §8:4: a digest part written before ADR-0334's key is no recorded call."""
    view = _json(server.port, f"/api/call?id={ACT_A}&line={DIGEST_GIVEN}")

    assert view["follow_ups"] == []


def test_the_observers_call_shows_the_follow_up_written_under_each_activation(
    server: Any,
) -> None:
    """§8:11: asked once, and written under each activation the call was written under."""
    for activation_id in (ACT_A, ACT_B):
        view = _json(server.port, f"/api/call?id={activation_id}&file=observer&line={SCOUT_GIVEN}")

        (asked,) = view["follow_ups"]
        assert asked["answer"]["text"] == ANSWER


def test_a_follow_up_that_failed_is_shown_as_its_failure(server: Any) -> None:
    view = _json(server.port, f"/api/call?id={ACT_F}&line=0")

    (asked,) = view["follow_ups"]
    assert asked["answer"] is None
    assert asked["failure"].startswith("ModelRateLimitError")


def test_a_follow_up_naming_another_instant_or_part_is_not_shown(record: Path) -> None:
    lines, _ = viewer.Record(record).lines(ACT_A)
    followed, _ = viewer.Record(record).follow_up_lines(ACT_A)
    given = lines[PLANNING_GIVEN]

    assert len(viewer.follow_ups_of(followed, given)) == 1
    moved = viewer.Entry(
        line=given.line,
        source=given.source,
        kind=given.kind,
        at=given.at + 0.001,
        recorded_at=given.recorded_at,
        body=given.body,
    )
    assert viewer.follow_ups_of(followed, moved) == []
    digest = lines[DIGEST_GIVEN]
    assert viewer.follow_ups_of(followed, digest) == []
