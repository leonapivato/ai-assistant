"""The activation viewer's walk mode: one activation, a step at a time (ADR-0316 §3:3).

The walked activation is written by ADR-0314's own store, shaped as the hub's sources
write it today (``_activation_record``). These cases hold what the server serves: the
steps in the activation's own order, each phase's summary read from its entries, the
text of what recall kept joined only where the record allows it, a missing or odd-shaped
entry costing its own summary alone (§5:2), and the observer's attempts as the last steps.
"""

from __future__ import annotations

import http.client
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _activation_record import (
    HOSTILE,
    KEPT_FACTS,
    KEPT_IDS,
    READING,
    ROUND_2_MESSAGE,
    ROUND_NOTES,
    SEARCH_RESULT,
    WALKED,
    WALKED_INPUT,
    WALKED_TITLES,
    iso,
    serving,
    viewer,
    write_record,
    write_walked,
)
from _learning_record import ALONE_CLAIM, EVIDENCE_CLAIM, write_learning

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration


@pytest.fixture
def record(tmp_path: Path) -> Path:
    """The viewer's record, the walked activation and the observer's files beside it."""
    return write_learning(write_walked(write_record(tmp_path)))


def _walk(record: Path, activation_id: str) -> dict[str, Any]:
    read = viewer.Record(record.parent)
    own = read.lines(activation_id)
    learned = read.learned_lines(activation_id)
    walked: dict[str, Any] = viewer.walk(
        [] if own is None else own[0],
        None if learned is None else learned[0],
        own=own is not None,
    )
    return walked


def _step(walked: dict[str, Any], title: str, nth: int = 0) -> dict[str, Any]:
    found: dict[str, Any] = [one for one in walked["steps"] if one["title"] == title][nth]
    return found


def _lines(directory: Path, activation_id: str, lines: list[dict[str, Any]]) -> None:
    rows = [{"activation_id": activation_id, **one} for one in lines]
    (directory / f"{activation_id}.jsonl").write_text(
        "".join(json.dumps(one) + "\n" for one in rows)
    )


def test_the_steps_are_the_activations_own_order(record: Path) -> None:
    walked = _walk(record, WALKED)
    assert [one["title"] for one in walked["steps"]] == WALKED_TITLES
    starts = [one["start"] for one in walked["steps"][:-1]]
    assert starts == sorted(starts)


def test_the_input_step_shows_what_arrived(record: Path) -> None:
    arrival = _step(_walk(record, WALKED), "Input")["arrival"]
    assert arrival["text"] == WALKED_INPUT
    assert arrival["from"] == "understanding"


def test_recalls_first_run_shows_its_kept_items_with_their_text_where_joined(
    record: Path,
) -> None:
    first = _step(_walk(record, WALKED), "Recall · first run")
    assert first["found"] == 3
    assert first["admitted"] == 2
    assert [(one["id"], one["score"], one["bands"]) for one in first["kept"]] == [
        (KEPT_IDS[0], 0.91, ["asserted"]),
        (KEPT_IDS[1], 0.84, ["derived"]),
    ]
    # Understanding's request showed both, in recall's order: the join is by order.
    assert [(one["label"], one["text"]) for one in first["kept"]] == [
        ("M1", KEPT_FACTS[0]),
        ("M2", KEPT_FACTS[1]),
    ]
    assert first["shown"]["joined"] is True
    assert first["cues"] == [{"text": WALKED_INPUT, "kinds": ["activation_input"]}]


def test_recalls_second_run_lists_planning_s_recalled_apart_and_never_joins_it(
    record: Path,
) -> None:
    second = _step(_walk(record, WALKED), "Recall · second run")
    assert [one["id"] for one in second["kept"]] == ["mem-seat"]
    assert second["kept"][0]["text"] is None
    shown = second["shown"]
    assert shown["from"] == "planning"
    assert shown["joined"] is False
    assert [one["label"] for one in shown["items"]] == ["M1", "M2", "M3"]


def test_a_request_showing_fewer_items_than_were_kept_is_not_joined(
    record: Path,
) -> None:
    understanding = {
        "messages": [
            {
                "role": "user",
                "content": json.dumps(
                    {"input": {"text": "hi"}, "recalled": [{"label": "M1", "fact": "f"}]}
                ),
            }
        ]
    }
    _lines(
        record,
        "fewer",
        [
            {"source": "recall", "kind": "given", "recorded_at": iso(0), "body": {"run": "first"}},
            {
                "source": "recall",
                "kind": "returned",
                "recorded_at": iso(10),
                "body": {"finds": [], "kept": [{"id": "a"}, {"id": "b"}]},
            },
            {
                "source": "understanding",
                "kind": "given",
                "recorded_at": iso(20),
                "body": understanding,
            },
        ],
    )
    first = _step(_walk(record, "fewer"), "Recall · first run")
    assert first["shown"]["joined"] is False
    assert [one["text"] for one in first["kept"]] == [None, None]
    assert first["shown"]["items"] == [{"label": "M1", "text": "f"}]


def test_understanding_reads_as_its_fields_with_its_labels_text(record: Path) -> None:
    """ADR-0353 §14:10: a reply recorded before ADR-0353 is read in the shape it was
    written in, since the diagnostic record is never upgraded."""
    step = _step(_walk(record, WALKED), "Understanding")
    reading = step["reading"]
    assert reading["shape"] == "earlier"
    assert reading["meaning"] == READING["meaning"]
    assert reading["ground"] == "stated"
    assert reading["references"] == [{"phrase": "the Lisbon flight", "labels": ["M1"]}]
    assert reading["relationships"][0]["ground"] == "supplied"
    assert reading["unresolved"] == [
        {"matter": "Which date in May", "why": "the fare depends on it"}
    ]
    assert reading["story_labels"] == ["S1"]
    assert step["labels"] == {"M1": KEPT_FACTS[0], "M2": KEPT_FACTS[1], "S1": "Trip to Lisbon"}
    links = step["links"]
    assert links[0]["label"] == "The call, readable"
    assert links[0]["call"] == links[0]["lines"][0]


#: A reply in ADR-0353 §9:1's shape: its six keys, and one it does not name.
_REPLY: dict[str, Any] = {
    "understanding": "Book the Lisbon flight and tell Ana it is booked.",
    "cites": ["M1", "R1"],
    "unclear": [
        {"gap": "which date in May", "readings": ["the 3rd", "the 10th"]},
        {"gap": "which Ana", "readings": ["the user's sister"]},
    ],
    "belongs_to": ["S1"],
    "meant_for": ["R1"],
    "relayed": False,
    "extra": 1,
}


def test_a_reply_in_its_six_keys_reads_in_that_shape() -> None:
    """ADR-0353 §14:10, §9:1: a reply written in the reply's shape is shown in it."""
    assert viewer.reading_of("```json\n" + json.dumps(_REPLY) + "\n```") == {
        "shape": "reply",
        "understanding": _REPLY["understanding"],
        "cites": ["M1", "R1"],
        "unclear": [
            {"gap": "which date in May", "readings": ["the 3rd", "the 10th"]},
            {"gap": "which Ana", "readings": ["the user's sister"]},
        ],
        "belongs_to": ["S1"],
        "meant_for": ["R1"],
        "relayed": False,
        "other": ["extra"],
    }
    odd = viewer.reading_of(
        '{"understanding": 3, "unclear": [{"gap": 1, "readings": ["a", 2]}], "relayed": "no"}'
    )
    assert odd is not None
    assert (odd["understanding"], odd["unclear"], odd["relayed"]) == (
        None,
        [{"gap": None, "readings": ["a"]}],
        None,
    )
    # An object with neither shape's own keys is read in the reply's shape.
    assert viewer.reading_of('{"continues": ["R1"]}') == {
        "shape": "reply",
        "understanding": None,
        "cites": [],
        "unclear": [],
        "belongs_to": [],
        "meant_for": [],
        "relayed": None,
        "other": ["continues"],
    }


def test_a_reply_in_its_six_keys_names_its_labels_text(record: Path) -> None:
    understanding = {
        "messages": [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "recalled": [{"label": "M1", "fact": "Ana is the user's sister."}],
                        "stories": [{"label": "S1", "summary": "Trip to Lisbon"}],
                        "in_progress": [{"label": "R1", "input": "book the flight"}],
                    }
                ),
            }
        ]
    }
    _lines(
        record,
        "replied",
        [
            {
                "source": "understanding",
                "kind": "given",
                "recorded_at": iso(20),
                "body": understanding,
            },
            {
                "source": "understanding",
                "kind": "returned",
                "recorded_at": iso(30),
                "body": {"reply": json.dumps(_REPLY)},
            },
        ],
    )
    step = _step(_walk(record, "replied"), "Understanding")
    assert step["reading"]["shape"] == "reply"
    assert step["labels"] == {
        "M1": "Ana is the user's sister.",
        "S1": "Trip to Lisbon",
        "R1": "book the flight",
    }


def test_a_reply_that_is_no_json_object_is_shown_as_written() -> None:
    assert viewer.reading_of("I think they mean a flight.") is None
    assert viewer.reading_of('```\n{"meaning": "m", "extra": 1}\n```') is not None
    odd = viewer.reading_of(
        '{"meaning": 3, "references": "none", "answers": [{"parts": [1, "x"]}]}'
    )
    assert odd is not None
    assert odd["meaning"] is None
    assert odd["references"] == []
    assert odd["answers"] == [{"question": None, "parts": [1]}]


def test_each_planning_round_shows_what_came_back_and_what_it_proposed(record: Path) -> None:
    walked = _walk(record, WALKED)
    first = _step(walked, "Planning · round 1")
    assert first["first"] is True
    assert first["before"] is None
    assert [(one["name"], json.loads(one["arguments"])) for one in first["calls"]] == [
        ("web_search", {"query": "Lisbon flights May"})
    ]
    assert first["notes"] == ROUND_NOTES
    assert first["asks"] == ["book_flight"]
    second = _step(walked, "Planning · round 2")
    assert second["before"]["round"] == 1
    assert second["before"]["calls"][0]["result"] == {"label": "R1", "text": SEARCH_RESULT}
    assert second["evidence"][0]["of"] == "R1"
    assert second["message"] == ROUND_2_MESSAGE
    assert second["calls"] == []


def test_authorizing_shows_each_verdict_and_the_message(record: Path) -> None:
    walked = _walk(record, WALKED)
    first = _step(walked, "Authorizing · round 1")
    assert first["verdicts"][0]["verdict"] == "allowed"
    assert first["message"] == {"allowed": True, "reason": None, "place": "chat"}
    assert _step(walked, "Authorizing · round 2")["outside"] is True


def test_digesting_and_the_end(record: Path) -> None:
    walked = _walk(record, WALKED)
    digest = _step(walked, "Digesting")["parts"]
    assert digest == [
        {
            "question": "Which flight fits?",
            "result": "r1",
            "part": "1 of 1",
            "returned": True,
            "failed": False,
            "why": None,
            "evidence": '{\n "evidence": [\n  "TP 1351 at 09:40"\n ]\n}',
        }
    ]
    end = _step(walked, "The end")
    assert end["rule"] == "nothing_due"
    assert end["recorded"] is True


def test_an_activation_still_running_walks_what_it_has(record: Path) -> None:
    """ADR-0316 §5:2: a missing entry loses its summary and nothing else."""
    _lines(
        record,
        "running",
        [
            {
                "source": "understanding",
                "kind": "given",
                "recorded_at": iso(0),
                "body": {
                    "messages": [
                        {"role": "user", "content": json.dumps({"input": {"text": HOSTILE}})}
                    ]
                },
            },
            {
                "source": "planning",
                "kind": "returned",
                "recorded_at": iso(50),
                "body": "not an object",
            },
        ],
    )
    walked = _walk(record, "running")
    assert [one["title"] for one in walked["steps"]] == [
        "Input",
        "Understanding",
        # A response no request or step opened begins no round: it is unnumbered.
        "Planning",
        "The end",
    ]
    understanding = walked["steps"][1]
    assert understanding["returned"] is False
    assert understanding["reading"] is None
    assert understanding["step"] is None
    planning = walked["steps"][2]
    assert planning["calls"] == []
    assert planning["request"] is False
    assert walked["steps"][-1]["recorded"] is False


def test_the_observer_s_attempts_are_the_last_steps(record: Path) -> None:
    walked = _walk(record, "a-retried")
    learning = [one for one in walked["steps"] if one["phase"] == "learning"]
    assert [one["title"] for one in learning] == ["Learning · attempt 1", "Learning · attempt 2"]
    assert walked["steps"][-2:] == learning
    claims = [finding["claim"] for finding in learning[1]["findings"]]
    assert EVIDENCE_CLAIM in claims
    assert all(link["file"] == "observer" for link in learning[1]["links"])


def test_an_activation_whose_own_record_is_gone_walks_its_learning_alone(record: Path) -> None:
    walked = _walk(record, "a-alone")
    assert walked["own"] is False
    assert [one["phase"] for one in walked["steps"]] == ["learning"]
    assert walked["steps"][0]["findings"][0]["claim"] == ALONE_CLAIM


# --- the server -----------------------------------------------------------------------------


@pytest.fixture
def server(record: Path) -> Iterator[Any]:
    """The viewer on loopback over ``record``."""
    with serving(record) as bound:
        yield bound


def _get(port: int, path: str) -> tuple[int, dict[str, str], Any]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), json.loads(response.read())
    finally:
        connection.close()


def test_the_walk_is_served_by_id_and_polled_by_version(server: Any) -> None:
    status, headers, walked = _get(server.port, f"/api/walk?id={WALKED}")
    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert [one["title"] for one in walked["steps"]] == WALKED_TITLES
    _status, _headers, activation = _get(server.port, f"/api/activation?id={WALKED}")
    assert activation["version"] == walked["version"]
    status, _headers, again = _get(server.port, f"/api/walk?id={WALKED}&v={walked['version']}")
    assert status == 200
    assert again["unchanged"] is True


def test_the_walk_names_an_activation_by_id_and_never_by_path(server: Any) -> None:
    for asked in ("nope", "../walked", "walked.jsonl"):
        status, _headers, body = _get(server.port, f"/api/walk?id={asked}")
        assert status == 404
        assert body == {"error": "no such activation"}


def test_a_score_too_large_for_a_number_loses_its_hint_alone(server: Any, record: Path) -> None:
    """ADR-0316 §5:2: a 401-digit score is a hint not recognised, never the walk's failure."""
    huge = "9" * 401
    returned = (
        '{"activation_id": "huge", "source": "recall", "kind": "returned", "recorded_at": "'
        + iso(10)
        + '", "body": {"finds": [{"id": "x", "score": '
        + huge
        + ', "band": "asserted"}], "kept": [{"id": "x", "score": '
        + huge
        + "}]}}\n"
    )
    (record / "huge.jsonl").write_text(returned)
    status, _headers, walked = _get(server.port, "/api/walk?id=huge")
    assert status == 200
    recall = walked["steps"][1]
    assert recall["kept"] == [
        {
            "id": "x",
            "score": None,
            "bands": ["asserted"],
            "found_by": [],
            "label": None,
            "text": None,
        }
    ]
