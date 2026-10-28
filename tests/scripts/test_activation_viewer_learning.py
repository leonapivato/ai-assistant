"""The activation viewer's learning lane and learning overview (ADR-0333 §5).

The observer files are written by the observer itself over the canonical fakes, through
ADR-0314's own store (``_learning_record``, §5:8), beside the activation files the
viewer's other tests read. These cases hold what the server serves: an observer file
joined to its activation by name and never listed as one, the lane drawn over the
observer's own instants, the overview newest first with each finding's claim and
outcome in short, an activation shown with its learning alone, and the observer's
calls readable as any other.
"""

from __future__ import annotations

import http.client
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _activation_record import serving, viewer, write_record
from _learning_record import (
    ALONE_CLAIM,
    EVIDENCE_CLAIM,
    KEPT_CLAIM,
    NOT_KEPT_CLAIM,
    NOT_KEPT_NOTE,
    SAID,
    write_learning,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration


@pytest.fixture
def record(tmp_path: Path) -> Path:
    """The viewer's activation record, and the observer's files beside it."""
    return write_learning(write_record(tmp_path))


@pytest.fixture
def server(record: Path) -> Iterator[Any]:
    """The viewer on loopback over ``record``."""
    with serving(record) as bound:
        yield bound


def _get(port: int, path: str) -> tuple[int, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def _json(port: int, path: str) -> Any:
    status, body = _get(port, path)
    assert status == 200, body
    return body


def _overview(port: int) -> dict[str, Any]:
    return {one["id"]: one for one in _json(port, "/api/learning")["activations"]}


def test_an_observer_file_is_never_listed_as_an_activation(server: Any, record: Path) -> None:
    """§5:6: ``X.observer.jsonl`` names no activation ``X.observer``; the list is unchanged."""
    assert (record / "a-alone.observer.jsonl").is_file()

    listed = {one["id"] for one in _json(server.port, "/api/activations")["activations"]}

    assert listed == {"act-1", "act-2", "a-kept", "a-skipped", "a-retried"}
    assert not any(one.endswith(".observer") for one in listed)


def test_the_overview_lists_each_activation_with_an_observer_file_newest_first(
    server: Any,
) -> None:
    """§5:4: every activation the record holds an observer file for, by its latest entry."""
    listed = _json(server.port, "/api/learning")["activations"]

    assert [one["id"] for one in listed] == ["a-retried", "a-alone", "a-kept", "a-skipped"]
    latest = [one["latest"] for one in listed]
    assert latest == sorted(latest, reverse=True)


def test_the_overview_shows_input_state_failure_and_each_findings_outcome(server: Any) -> None:
    """§5:5: the input in short, the episode's state, any failure, each claim and outcome."""
    shown = _overview(server.port)

    kept = shown["a-kept"]
    assert kept["input"] == SAID["a-kept"]
    assert (kept["state"], kept["own"], kept["dropped"]) == ("processed", True, 1)
    first, second = kept["findings"]
    assert (first["claim"], first["outcome"]["short"]) == (KEPT_CLAIM, "memory created")
    assert first["outcome"]["kept"] is True
    assert first["outcome"]["wording"] == KEPT_CLAIM
    assert second["claim"] == NOT_KEPT_CLAIM
    assert second["outcome"]["short"] == "nothing kept"
    assert second["outcome"]["why"] == "nothing in it was kept"
    assert second["outcome"]["note"] == NOT_KEPT_NOTE

    retried = shown["a-retried"]
    assert (retried["attempts"], retried["failed"], retried["state"]) == (2, 1, "processed")
    (evidence,) = retried["findings"]
    assert evidence["claim"] == EVIDENCE_CLAIM
    assert (evidence["outcome"]["short"], evidence["outcome"]["wording"]) == (
        "memory created",
        EVIDENCE_CLAIM,
    )
    assert evidence["outcome"]["unclear"] == 0

    skipped = shown["a-skipped"]
    assert (skipped["state"], skipped["findings"]) == ("skipped", [])


def test_each_finding_names_the_lines_of_the_prompts_and_replies_behind_it(
    server: Any, record: Path
) -> None:
    """The owner jumps from a finding to its scout's, framing's and placements' calls."""
    (second,) = [one for one in _overview(server.port)["a-kept"]["findings"] if one["id"] == "f2"]
    lines = (record / "a-kept.observer.jsonl").read_text(encoding="utf-8").splitlines()

    def body(line: int) -> Any:
        return json.loads(lines[line])["body"]

    assert body(second["scout"]["given"])["stage"] == "scout"
    assert "reply" in body(second["scout"]["returned"])
    assert second["commit"] is None
    assert body(second["framing"]["given"])["finding"]["claim"] == NOT_KEPT_CLAIM
    assert body(second["framing"]["returned"])["finding"] == "f2"
    assert second["placements"] == []
    (evidence,) = _overview(server.port)["a-retried"]["findings"]
    (placed,) = evidence["placements"]
    retried = (record / "a-retried.observer.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(retried[placed["given"]])["body"]["stage"] == "placement"
    assert json.loads(retried[placed["returned"]])["body"]["finding"] == evidence["id"]
    assert body(second["outcome"]["line"])["stage"] == "outcome"
    assert body(second["findings_line"])["stage"] == "findings"


def test_the_learning_lane_groups_by_attempt_and_leaves_the_timeline_alone(
    server: Any, record: Path
) -> None:
    """§5:2-§5:3: grouped by attempt, over its own instants; the activation's span unchanged."""
    lines, _version = viewer.Record(record.parent).lines("a-retried") or ([], "")
    alone = viewer.timeline("a-retried", lines)

    shown = _json(server.port, "/api/activation?id=a-retried")

    assert shown["own"] is True
    assert (shown["start"], shown["end"]) == (alone["start"], alone["end"])
    assert shown["summary"] == alone["summary"]
    first, second = shown["learning"]["attempts"]
    assert first["ended"]["end"] == "failed"
    assert "timed out" in first["ended"]["failure"]
    assert second["ended"]["state"] == "processed"
    assert first["start"] > alone["end"]
    kinds = [item["kind"] for item in second["items"]]
    assert kinds == ["call", "findings", "call", "call", "outcome", "end"]
    assert [item["stage"] for item in second["items"] if item["kind"] == "call"] == [
        "scout",
        "framing",
        "placement",
    ]


def test_an_activation_with_only_its_observer_file_shows_its_learning_alone(
    server: Any,
) -> None:
    """§5:6: its own record absent, said so, and its lane shown."""
    shown = _json(server.port, "/api/activation?id=a-alone")

    assert shown["own"] is False
    assert shown["items"] == []
    (finding,) = shown["learning"]["findings"]
    assert (finding["claim"], finding["outcome"]["short"]) == (ALONE_CLAIM, "memory created")
    assert _overview(server.port)["a-alone"]["own"] is False
    assert _get(server.port, "/api/activation?id=nobody")[0] == 404


def test_an_activation_with_no_observer_file_has_no_lane(server: Any) -> None:
    shown = _json(server.port, "/api/activation?id=act-1")

    assert shown["own"] is True
    assert shown["learning"] is None


def test_an_observer_call_reads_as_told_given_and_done(server: Any, record: Path) -> None:
    """§5:2: a call's body readable as well as raw, as every model call is."""
    (second,) = [one for one in _overview(server.port)["a-kept"]["findings"] if one["id"] == "f2"]
    line = second["framing"]["given"]

    view = _json(server.port, f"/api/call?id=a-kept&file=observer&line={line}")

    assert view["source"] == "observer"
    assert view["about"]["stage"] == "framing"
    assert (view["about"]["finding"], view["about"]["claim"]) == ("f2", NOT_KEPT_CLAIM)
    assert view["returned"] == second["framing"]["returned"]
    assert view["told"]["sections"]
    assert view["input"][0]["keys"][0]["key"] == "claim"
    (reply,) = view["did"]["parts"]
    assert NOT_KEPT_NOTE in reply["text"]
    # Since ADR-0354 §7:2 the observer's returned entry keeps its usage and model; the
    # test double names a model no rates are kept for, so no cost is estimated.
    assert view["did"]["usage"] == {"input": 0, "output": 0, "cache read": 0, "cache write": 0}
    assert (view["did"]["model"], view["did"]["cost"]) == ("fake:structured", None)
    assert "usage_note" not in view["did"]
    entry = _json(server.port, f"/api/entry?id=a-kept&file=observer&line={line}")
    assert (entry["source"], entry["kind"]) == ("observer", "given")
    # Without ``file=observer`` a line is the activation's own file's.
    assert _json(server.port, "/api/entry?id=a-kept&line=0")["source"] == "understanding"


def test_a_step_entry_or_a_line_of_another_file_is_no_observer_call(server: Any) -> None:
    (first,) = [one for one in _overview(server.port)["a-kept"]["findings"] if one["id"] == "f1"]

    for line in (first["findings_line"], first["outcome"]["line"], 999):
        assert _get(server.port, f"/api/call?id=a-kept&file=observer&line={line}")[0] == 404
    assert _get(server.port, "/api/call?id=act-1&file=observer&line=0")[0] == 404


def test_the_overview_follows_a_file_as_it_grows_and_goes(server: Any, record: Path) -> None:
    """§5:7, ADR-0316 §4: followed as an activation's file is, and dropped when swept."""
    before = _json(server.port, "/api/learning")
    path = record / "a-skipped.observer.jsonl"
    line = json.loads(path.read_text(encoding="utf-8"))
    line["recorded_at"] = "2030-01-01T00:00:00+00:00"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")

    grown = _json(server.port, f"/api/learning?v={before['version']}")
    assert grown["activations"][0]["id"] == "a-skipped"
    assert grown["activations"][0]["entries"] == 2

    path.unlink()
    assert "a-skipped" not in _overview(server.port)


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (
            {"writes": [{"memory": "m", "operations": ["create"], "track_record": None}]},
            (True, "memory created"),
        ),
        (
            {
                "writes": [
                    {"memory": "n", "operations": ["create"]},
                    {"memory": "o", "operations": ["replace"]},
                ]
            },
            (True, "memory created, memory replaced"),
        ),
        ({"writes": [{"memory": "m", "operations": ["add_support"]}]}, (True, "memory added to")),
        (
            {"writes": [{"memory": "m", "operations": ["raise_question"]}]},
            (True, "question raised"),
        ),
        (
            {"writes": [{"memory": "m", "operations": [], "track_record": False}]},
            (True, "track record: let down"),
        ),
        ({"unwritten": "below_floor"}, (False, "nothing kept")),
        ("not an object", (False, "nothing kept")),
    ],
)
def test_an_outcome_reads_in_short(outcome: object, expected: tuple[bool, str]) -> None:
    """§5:5's list: created, added to, ended or replaced, a question, a track record, or not."""
    shown = viewer.outcome_in_short(outcome)

    assert (shown["kept"], shown["short"]) == expected


def test_odd_observer_lines_lose_their_summary_and_nothing_else() -> None:
    """ADR-0316 §5:2 over the lane: a body of another shape is still an entry to click."""
    learned = viewer.Learned("odd")
    odd: list[dict[str, Any]] = [
        {"stage": "findings", "findings": "not a list", "dropped": True},
        {"stage": "outcome", "finding": 7, "outcome": [], "decided": "x"},
        {"stage": "end", "failure": {"class": 3}},
        {"stage": "commit", "finding": {"id": None}},
        {"stage": ["scout"]},
        {},
    ]
    for number, body in enumerate(odd):
        raw = {
            "activation_id": "odd",
            "source": "observer",
            "kind": "returned" if number == 3 else "step",
            "recorded_at": "2026-10-18T12:00:00+00:00",
            "body": body,
        }
        learned.feed(viewer.parse_line(number, json.dumps(raw).encode()))
    learned.feed(None)

    lane = learned.lane()
    summary = learned.summary()

    assert summary["entries"] == len(odd)
    assert summary["unreadable"] == 1
    clickable = [
        line for one in lane["attempts"] for item in one["items"] for line in item["lines"]
    ]
    assert sorted(clickable) == list(range(len(odd)))


@pytest.mark.parametrize(
    ("returned", "tone"),
    [({}, "ok"), ({"failure": None}, "ok"), ({"failure": "timed out"}, "failed")],
)
def test_an_observer_call_failed_only_where_its_failure_holds_one(
    returned: dict[str, Any], tone: str
) -> None:
    """#3510: no ``failure`` key and ``failure: null`` alike say nothing failed."""
    learned = viewer.Learned("calls")
    kinds = ("given", "returned")
    for number, (kind, body) in enumerate(zip(kinds, ({}, returned), strict=True)):
        raw = {
            "activation_id": "calls",
            "source": "observer",
            "kind": kind,
            "recorded_at": f"2026-10-18T12:00:0{number}+00:00",
            "body": {"stage": "scout"} | body,
        }
        learned.feed(viewer.parse_line(number, json.dumps(raw).encode()))
    learned.feed(None)
    (attempt,) = learned.lane()["attempts"]
    assert [(one["kind"], one["tone"]) for one in attempt["items"]] == [("call", tone)]


def test_a_framing_whose_findings_entry_is_absent_keeps_its_link(server: Any, record: Path) -> None:
    """A finding recorded only from its framing on (the record turned on between attempts)."""
    kept = (record / "a-kept.observer.jsonl").read_text(encoding="utf-8").splitlines()
    later = [one for one in kept if json.loads(one)["body"]["stage"] not in {"scout", "findings"}]
    (record / "later.observer.jsonl").write_text("\n".join(later) + "\n", encoding="utf-8")

    first, second = _overview(server.port)["later"]["findings"]

    assert (first["claim"], second["claim"]) == (KEPT_CLAIM, NOT_KEPT_CLAIM)
    assert second["findings_line"] is None
    framed = second["framing"]
    assert json.loads(later[framed["given"]])["body"]["finding"]["id"] == "f2"
    assert json.loads(later[framed["returned"]])["body"]["finding"] == "f2"
    assert second["outcome"]["short"] == "nothing kept"


@pytest.mark.parametrize("stage", [["scout"], {"step": "commit"}, 3, None])
def test_a_call_whose_stage_is_of_another_shape_reads_as_no_call(
    server: Any, record: Path, stage: object
) -> None:
    """ADR-0316 §5:2 via ADR-0333 §5:7: an odd hint loses its reading, never the request."""
    line = {
        "activation_id": "odd",
        "source": "observer",
        "kind": "given",
        "recorded_at": "2026-10-18T12:00:00+00:00",
        "body": {"stage": stage, "messages": []},
    }
    (record / "odd.observer.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")

    assert _get(server.port, "/api/call?id=odd&file=observer&line=0")[0] == 404
    assert _json(server.port, "/api/entry?id=odd&file=observer&line=0")["kind"] == "given"
    assert _json(server.port, "/api/activation?id=odd")["learning"]["entries"]
