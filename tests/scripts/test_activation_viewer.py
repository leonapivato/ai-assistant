"""Tests for ``scripts/activation_viewer.py`` (ADR-0316).

The viewer is loaded by its path, as every script here is: it is no package, and
nothing in ``ai_assistant`` may import it (§2:4). Its records are written with ADR-0314's
own store, so a change to the line the viewer reads fails here (§7:2), and the server
is bound for real on loopback, so §6's refusals and headers are pinned as a browser
meets them (§7:3).
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import http.client
import inspect
import json
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _operator_recipes import SCRIPTS

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

from _activation_record import (
    ACTIVATION,
    FOREIGN_LINES,
    HOSTILE,
    PRIVATE,
    at,
    iso,
    serving,
    step,
    viewer,
    write_record,
)
from _model_call_record import (
    ADDED,
    CALLS,
    CALLS_RULE,
    DIGEST_GIVEN_LINE,
    DIGEST_RETURNED_LINE,
    LABELS,
    ODD,
    ODD_ENTRIES,
    ROLE,
    ROUND_1_GIVEN,
    ROUND_1_INPUT,
    ROUND_1_RETURNED_LINE,
    ROUND_2_GIVEN,
    SEND_EMAIL,
    UNDERSTANDING_GIVEN,
    UNDERSTANDING_RETURNED,
    WEB_SEARCH,
    write_calls,
)


@pytest.fixture
def record(tmp_path: Path) -> Path:
    """A record written by ADR-0314's store, plus the lines it cannot write."""
    return write_record(tmp_path)


@pytest.fixture
def server(record: Path) -> Iterator[Any]:
    """The viewer bound on loopback at a free port, over ``record``'s data directory."""
    with serving(record) as bound:
        yield bound


_SOURCE = SCRIPTS / "activation_viewer.py"
_PACKAGE = Path(__file__).parents[2] / "src" / "ai_assistant"


def _request(
    port: int, path: str, *, method: str = "GET", host: str | None = "default"
) -> tuple[int, Mapping[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        if host is not None:
            connection.putheader("Host", f"127.0.0.1:{port}" if host == "default" else host)
        connection.endheaders()
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def _get_json(port: int, path: str) -> Any:
    status, headers, body = _request(port, path)
    assert status == 200, body
    assert headers["Content-Type"].startswith("application/json")
    return json.loads(body)


def _summary(port: int, activation_id: str) -> Any:
    listed = _get_json(port, "/api/activations")["activations"]
    return next(one for one in listed if one["id"] == activation_id)


def _snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    return {
        str(path.relative_to(root)): (
            path.stat().st_mode,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "",
        )
        for path in sorted(root.rglob("*"))
    }


# --- §2, §7:1: what it is and where it lives ----------------------------------------------


def test_it_imports_the_standard_library_alone() -> None:
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import"
            assert node.module is not None
            imported.add(node.module.split(".")[0])
    assert imported, "the scan found no imports at all"
    foreign = {name for name in imported if name not in sys.stdlib_module_names}
    assert foreign <= {"__future__"}, foreign


def test_nothing_in_the_package_names_it() -> None:
    naming = [
        path
        for path in _PACKAGE.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and b"activation_viewer" in path.read_bytes()
    ]
    assert naming == []


# --- §6: what it may not do -----------------------------------------------------------------


def test_it_binds_loopback_alone_and_takes_no_address(record: Path) -> None:
    assert viewer.HOST == "127.0.0.1"
    assert "host" not in inspect.signature(viewer.ViewerServer).parameters
    bound = viewer.ViewerServer(viewer.Record(record), 0, report=lambda _line: None)
    try:
        assert bound.server_address[0] == "127.0.0.1"
    finally:
        bound.server_close()
    for option in ("--host", "--bind", "--address"):
        with pytest.raises(SystemExit):
            viewer.parse_args([str(record), option, "0.0.0.0"])  # noqa: S104 — the refused bind


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "evil.example:{port}",
        "127.0.0.1:1",
        "localhost",
        "0.0.0.0:{port}",
        "[::1]:{port}",
        "",
    ],
)
def test_it_refuses_a_host_that_is_not_its_own_loopback_name(server: Any, host: str) -> None:
    status, headers, body = _request(
        server.port, "/api/activations", host=host.format(port=server.port)
    )
    assert status == 403
    assert b"act-1" not in body
    assert headers["Cache-Control"] == "no-store"


def test_it_refuses_a_request_with_no_host(server: Any) -> None:
    status, _headers, _body = _request(server.port, "/", host=None)
    assert status == 403


def test_it_answers_both_loopback_names(server: Any) -> None:
    for host in (
        f"127.0.0.1:{server.port}",
        f"localhost:{server.port}",
        f"LOCALHOST:{server.port}",
    ):
        status, _headers, _body = _request(server.port, "/", host=host)
        assert status == 200


@pytest.mark.parametrize(
    "method", ["POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "BREW"]
)
def test_it_answers_get_alone(server: Any, method: str) -> None:
    status, headers, _body = _request(server.port, "/api/activations", method=method)
    assert status == 405
    assert headers["Allow"] == "GET"
    assert headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/app.js",
        "/app.css",
        "/favicon.ico",
        "/api/activations",
        "/api/activation?id=act-1",
        "/api/call?id=act-1&line=0",
        "/api/call?id=act-1&line=1000",
        "/nowhere",
    ],
)
def test_every_response_carries_no_store_and_a_self_only_policy(server: Any, path: str) -> None:
    _status, headers, _body = _request(server.port, path)
    assert headers["Cache-Control"] == "no-store"
    policy = headers["Content-Security-Policy"]
    assert "default-src 'none'" in policy
    assert "script-src 'self'" in policy
    assert "connect-src 'self'" in policy
    assert "http" not in policy
    assert "*" not in policy
    assert "unsafe" not in policy
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_the_page_loads_nothing_it_does_not_serve(server: Any) -> None:
    for path in ("/", "/app.js", "/app.css"):
        _status, _headers, body = _request(server.port, path)
        assert b"http://" not in body
        assert b"https://" not in body
        assert b"//cdn" not in body


def test_an_activation_is_named_by_a_listed_id_never_a_path(server: Any, record: Path) -> None:
    (record.parent / "elsewhere.jsonl").write_text(
        json.dumps(
            {
                "activation_id": "x",
                "source": "planning",
                "kind": "given",
                "recorded_at": iso(0),
                "body": {},
            }
        )
        + "\n"
    )
    for name in ("../elsewhere", "..%2Felsewhere", "/etc/passwd", "act-1.jsonl", "act-1/..", ""):
        status, _headers, _body = _request(server.port, f"/api/activation?id={name}")
        assert status == 404, name
        status, _headers, _body = _request(server.port, f"/api/entry?id={name}&line=0")
        assert status == 404, name
        status, _headers, _body = _request(server.port, f"/api/call?id={name}&line=0")
        assert status == 404, name


def test_serving_leaves_the_record_unchanged(server: Any, record: Path) -> None:
    root = record.parent.parent
    before = _snapshot(root)
    for path in (
        "/",
        "/app.js",
        "/app.css",
        "/api/activations",
        "/api/activations?v=stale",
        "/api/activation?id=act-1",
        "/api/activation?id=act-2",
        "/api/entry?id=act-1&line=0",
        "/api/entry?id=act-2&line=1",
        "/api/call?id=act-1&line=3",
        "/api/call?id=act-1&line=4",
    ):
        _request(server.port, path)
    assert _snapshot(root) == before


# --- §3, §5: reading the store's record -----------------------------------------------------


def test_it_reads_the_stores_lines_the_marker_and_what_it_does_not_know(record: Path) -> None:
    read = viewer.Record(record).lines("act-1")
    assert read is not None
    lines, _version = read
    entries = [one for one in lines if isinstance(one, viewer.Entry)]
    assert len(entries) == len(ACTIVATION) + len(FOREIGN_LINES)
    assert entries[0].source == "understanding"
    assert entries[0].kind == "given"
    assert entries[0].at == at(10).timestamp()
    assert [(one.source, one.kind) for one in entries[-2:]] == [
        ("planning", "pondered"),
        ("oracle", "given"),
    ]
    # The line that is not JSON is counted; the line with no newline yet is not read.
    assert lines.count(None) == 1
    assert len(lines) == len(ACTIVATION) + len(FOREIGN_LINES) + 1

    marked = viewer.Record(record).lines("act-2")
    assert marked is not None
    last = marked[0][-1]
    assert isinstance(last, viewer.Truncation)
    assert last.at == at(100_500).timestamp()


def test_the_list_shows_each_activations_flow_newest_first(server: Any) -> None:
    listed = _get_json(server.port, "/api/activations")
    assert [one["id"] for one in listed["activations"]] == ["act-2", "act-1"]
    first = listed["activations"][1]
    assert first["input"] == HOSTILE
    assert first["ended"] == "nothing_due"
    assert first["rounds"] == 2
    assert first["duration"] == pytest.approx(1901 - 5)
    assert first["unreadable"] == 1
    assert first["open"] is False
    assert set(first["badges"]) == {"needs_you", "outside_content", "digest_failed"}
    second = listed["activations"][0]
    assert second["badges"] == ["truncated"]
    assert second["input"] == "hello"
    # Polling with the version it was given costs nothing and says so.
    again = _get_json(server.port, f"/api/activations?v={listed['version']}")
    assert again["unchanged"] is True


def test_the_badges_cover_a_refusal_and_a_stage_that_failed() -> None:
    tally = viewer.Tally("a")
    body = {"calls": [{"verdict": "not_done"}], "message": {"allowed": False}}
    tally.feed(viewer.Entry(0, "authorizing", "returned", 1.0, "", body))
    tally.feed(viewer.Entry(1, "controller", "step", 2.0, "", step("end", "stage_failed", 2, 2)))
    assert set(tally.badges()) == {"refused", "could_not_finish"}


def _fed(lines: list[Any]) -> Any:
    tally = viewer.Tally("a")
    for line in lines:
        tally.feed(line)
    return tally


def _controller(line: int, stage: str, due: str, start: int, outcome: str = "done") -> Any:
    body = step(stage, due, start, start + 1, outcome)
    return viewer.Entry(line, "controller", "step", at(start + 1).timestamp(), "", body)


@pytest.mark.parametrize("outcome", ["failed", "timed_out"])
def test_a_tolerated_stage_failure_badges_nothing_and_its_step_still_shows(outcome: str) -> None:
    # Recall tolerates its failure and its budget, and the pass goes on (ADR-0281 §5):
    # the activation finished, so nothing says it could not (ADR-0317 §3:3, §4:4).
    lines = [
        _controller(0, "recall", "not_recalled", 10, outcome),
        _controller(1, "understanding", "not_understood", 20),
        _controller(2, "planning", "first_round_due", 30),
        _controller(3, "end", "nothing_due", 40),
    ]
    tally = _fed(lines)
    assert tally.badges() == []
    assert tally.summary()["ended"] == "nothing_due"
    shown = viewer.timeline("a", lines)
    recall = [one for one in shown["items"] if one["lane"] == "recall"]
    assert [(one["kind"], one["tone"]) for one in recall] == [("step", outcome)]


@pytest.mark.parametrize(
    "rule",
    [
        "round_limit_reached",
        "stage_failed",
        "stage_timed_out",
        "stage_repeated",
        "interrupted",
        "hub_stopped",
    ],
)
def test_an_activation_its_end_cut_short_is_badged_could_not_finish(rule: str) -> None:
    tally = _fed([_controller(0, "planning", "round_due", 10), _controller(1, "end", rule, 20)])
    assert tally.badges() == ["could_not_finish"]


@pytest.mark.parametrize("rule", ["nothing_due", "route_taken", "no_text_input", "stopped"])
def test_an_activation_that_ended_without_being_cut_short_has_no_such_badge(rule: str) -> None:
    tally = _fed([_controller(0, "planning", "round_due", 10), _controller(1, "end", rule, 20)])
    assert tally.badges() == []


def test_a_failure_authorizing_returned_badges_only_through_the_end_it_caused() -> None:
    failure = {"failure": {"class": "AuditError", "message": "refused"}}
    returned = viewer.Entry(0, "authorizing", "returned", 1.0, "", failure)
    failed = _controller(1, "authorizing", "round_unauthorized", 10, "failed")
    assert _fed([returned, failed]).badges() == []
    ended = _fed([returned, failed, _controller(2, "end", "stage_failed", 20)])
    assert ended.badges() == ["could_not_finish"]
    assert _fed([returned, failed, _controller(2, "end", "stopped", 20)]).badges() == []


def test_a_refused_message_keeps_its_own_badge() -> None:
    refused = {"calls": [], "message": {"allowed": False}}
    lines = [
        viewer.Entry(0, "authorizing", "returned", 1.0, "", refused),
        _controller(1, "end", "nothing_due", 20),
    ]
    assert _fed(lines).badges() == ["refused"]


def test_the_timeline_draws_one_lane_per_source_and_planning_by_round(server: Any) -> None:
    shown = _get_json(server.port, "/api/activation?id=act-1")
    lanes = [lane["key"] for lane in shown["lanes"]]
    assert lanes[:7] == [
        "controller",
        "recall",
        "understanding",
        "planning",
        "authorizing",
        "acting",
        "digesting",
    ]
    assert lanes[7:] == ["planning · pondered", "oracle"]
    items = shown["items"]
    rounds = [one for one in items if one["lane"] == "planning" and one["kind"] == "step"]
    assert [one["label"] for one in rounds] == ["round 1", "round 2"]
    assert rounds[0]["start"] == pytest.approx(at(410).timestamp() * 1000)
    assert rounds[0]["end"] == pytest.approx(at(901).timestamp() * 1000)
    calls = [one for one in items if one["lane"] == "planning" and one["kind"] == "call"]
    assert [one["round"] for one in calls] == [1, 2]
    assert len(calls[0]["lines"]) == 2
    acting = [one for one in items if one["lane"] == "acting"]
    assert len(acting) == 1
    failed = [one for one in items if one["lane"] == "digesting" and one["kind"] == "call"]
    assert failed[0]["tone"] == "failed"
    assert shown["rounds"][0]["text"] == "Looking that up. " + PRIVATE
    assert shown["rounds"][0]["calls"] == [
        {"id": "c1", "name": "web_search"},
        {"id": "c2", "name": "web_search"},
    ]
    assert shown["rounds"][0]["marked"] is True
    assert shown["rounds"][0]["thinking"] is True
    assert [(one["call_id"], one["verdict"]) for one in shown["rounds"][0]["verdicts"]] == [
        ("c1", "allowed"),
        ("c2", "needs_you"),
    ]
    assert shown["rounds"][1]["marked"] is False
    assert shown["rounds"][1]["text"] == "Here is the answer."
    assert shown["unreadable"] == 1


def test_a_message_is_marked_allowed_and_never_claimed_written(server: Any) -> None:
    shown = _get_json(server.port, "/api/activation?id=act-1")
    marks = [one for one in shown["items"] if one["kind"] == "message"]
    assert len(marks) == 1
    assert marks[0]["lane"] == "authorizing"
    assert marks[0]["label"] == "message allowed"
    assert shown["rounds"][1]["message"] == {"allowed": True, "reason": None}
    assert "written" not in json.dumps(shown).replace("not recorded", "")
    assert "whether it was written is not recorded" in viewer.SCRIPT


def test_the_truncation_marker_is_the_files_end(server: Any) -> None:
    shown = _get_json(server.port, "/api/activation?id=act-2")
    assert shown["truncated"]["at"] == pytest.approx(at(100_500).timestamp() * 1000)
    assert shown["summary"]["badges"] == ["truncated"]
    marker = _get_json(server.port, f"/api/entry?id=act-2&line={shown['truncated']['line']}")
    assert marker["truncated_at"].startswith("2026-10-13T09:01:40.500000")


def test_a_click_shows_a_body_whole(server: Any) -> None:
    entry = _get_json(server.port, "/api/entry?id=act-1&line=4")
    assert entry["source"] == "planning"
    assert entry["kind"] == "returned"
    assert entry["body"] == ACTIVATION[4][3]
    missing, _headers, _body = _request(server.port, "/api/entry?id=act-1&line=999")
    assert missing == 404


# --- §4: near-live --------------------------------------------------------------------------


def test_it_follows_the_directory_as_it_changes(server: Any, record: Path) -> None:
    def ids() -> list[str]:
        return [one["id"] for one in _get_json(server.port, "/api/activations")["activations"]]

    line = json.dumps(
        {
            "activation_id": "act-3",
            "source": "controller",
            "kind": "step",
            "recorded_at": iso(200_000),
            "body": {},
        }
    )
    fresh = record / "act-3.jsonl"
    fresh.write_text(line[:20])
    assert "act-3" in ids()
    assert _summary(server.port, "act-3")["entries"] == 0
    with fresh.open("a") as handle:
        handle.write(line[20:] + "\n")
    assert _summary(server.port, "act-3")["entries"] == 1
    fresh.unlink()
    (record / "act-2.jsonl").unlink()
    assert ids() == ["act-1"]
    gone, _headers, _body = _request(server.port, "/api/activation?id=act-2")
    assert gone == 404


def test_a_record_not_yet_created_lists_nothing(tmp_path: Path) -> None:
    listed = viewer.Record(tmp_path / "missing").activations()
    assert listed["activations"] == []
    assert listed["present"] is False
    assert not (tmp_path / "missing").exists()


# --- §6:7-§6:8: text, never markup; nothing printed from an entry ---------------------------


def test_entry_text_is_served_as_data_and_rendered_as_text(server: Any) -> None:
    status, headers, body = _request(server.port, "/api/entry?id=act-1&line=0")
    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert headers["X-Content-Type-Options"] == "nosniff"
    # The page holds no entry: everything reaches it through fetch as JSON.
    _status, _headers, page = _request(server.port, "/")
    assert HOSTILE.encode() not in page
    # And the script puts every string into the page as text, never as markup.
    for sink in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "Function(",
    ):
        assert sink not in viewer.SCRIPT, sink
    assert "textContent" in viewer.SCRIPT
    assert json.loads(body)["body"]["messages"][1]["content"].find("<script>") >= 0


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.mark.timeout(60)
def test_run_from_the_command_line_it_prints_its_address_and_no_entry(record: Path) -> None:
    port = _free_port()
    process = subprocess.Popen(  # noqa: S603 — this interpreter and the script, by path
        [sys.executable, "-B", str(_SOURCE), str(record), "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                status, _headers, _body = _request(port, "/api/activations")
                break
            except OSError:
                assert time.monotonic() < deadline, "the viewer did not start"
                time.sleep(0.1)
        assert status == 200
        for path in (
            "/api/activation?id=act-1",
            "/api/entry?id=act-1&line=4",
            "/api/entry?id=act-1&line=x",
        ):
            _request(port, path)
        _request(port, "/", method="POST")
        _request(port, "/", host="evil.example")
    finally:
        process.terminate()
        stdout, stderr = process.communicate(timeout=10)
    printed = stdout + stderr
    assert f"http://127.0.0.1:{port}".encode() in printed
    for content in (PRIVATE, "act-1", "Looking that up", "hello"):
        assert content.encode() not in printed


def test_help_says_how_to_run_it() -> None:
    result = subprocess.run(  # noqa: S603 — this interpreter and the script, by path
        [sys.executable, "-B", str(_SOURCE), "--help"], capture_output=True, text=True, check=True
    )
    for needed in ("ssh -L 8765:127.0.0.1:8765", "--port", "hub's user", "diagnostics"):
        assert needed in result.stdout, needed


# --- §5:2: a hint lost, never an activation ------------------------------------------------

#: Values no source writes today, in every place a hint is read.
_ODD: tuple[object, ...] = ([], {}, 1, None, "text", [{}], {"x": []})

_HINT_KEYS = (
    "stage",
    "due",
    "outcome",
    "started_at",
    "ended_at",
    "failure",
    "messages",
    "calls",
    "message",
    "read_outside_content",
    "digest",
    "response",
    "result",
    "question",
    "part",
    "run",
    "grounds",
)

_SOURCES = ("controller", "understanding", "recall", "planning", "authorizing", "digesting")


def _odd_lines() -> list[bytes]:
    shapes: list[object] = [*_ODD]
    shapes += [dict.fromkeys(_HINT_KEYS, odd) for odd in _ODD]
    shapes += [
        {"response": {"parts": [odd, {"part_kind": "tool-call", "args": odd}]}} for odd in _ODD
    ]
    shapes += [{"calls": [odd], "message": odd} for odd in _ODD]
    lines: list[bytes] = []
    for number, body in enumerate(shapes):
        for source in _SOURCES:
            for kind in ("given", "returned", "step"):
                line = {
                    "activation_id": "odd",
                    "source": source,
                    "kind": kind,
                    "recorded_at": iso(number),
                    "body": body,
                }
                lines.append(json.dumps(line).encode())
    return lines


def test_a_body_of_an_unexpected_shape_loses_its_hint_and_nothing_else() -> None:
    lines = [viewer.parse_line(number, raw) for number, raw in enumerate(_odd_lines())]
    assert None not in lines
    tally = viewer.Tally("odd")
    for line in lines:
        tally.feed(line)
    json.dumps(tally.summary(), allow_nan=False)
    shown = viewer.timeline("odd", lines)
    json.dumps(shown, allow_nan=False)
    assert len(shown["entries"]) == len(lines)


def test_one_odd_activation_leaves_the_list_and_the_others_whole(server: Any, record: Path) -> None:
    (record / "odd.jsonl").write_bytes(b"\n".join(_odd_lines()) + b"\n")
    listed = {one["id"] for one in _get_json(server.port, "/api/activations")["activations"]}
    assert listed == {"act-1", "act-2", "odd"}
    assert _get_json(server.port, "/api/activation?id=odd")["id"] == "odd"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_line_holding_a_constant_json_does_not_have_is_unreadable(constant: str) -> None:
    raw = '{"activation_id": "a", "source": "planning", "kind": "given", '
    raw += f'"recorded_at": "{iso(0)}", "body": {{"x": {constant}}}}}'
    assert viewer.parse_line(0, raw.encode()) is None


def test_a_string_that_names_no_instant_is_no_instant() -> None:
    values: tuple[object, ...] = ("", "not a time", "2026-13-40T00:00:00", [], None, 7)
    for value in values:
        assert viewer.instant(value) is None


def test_a_number_too_large_to_be_finite_makes_its_line_unreadable() -> None:
    raw = '{"activation_id": "a", "source": "planning", "kind": "given", '
    raw += f'"recorded_at": "{iso(0)}", "body": {{"x": 1e400}}}}'
    assert viewer.parse_line(0, raw.encode()) is None


def test_a_lone_surrogate_in_an_entry_is_served_not_fatal(server: Any, record: Path) -> None:
    # The input as understanding's request carries it: JSON inside a message's content,
    # here with a lone surrogate escaped in it.
    content = '{"input": {"text": "before \\ud800 after"}}'
    line = {
        "activation_id": "lone",
        "source": "understanding",
        "kind": "given",
        "recorded_at": iso(300_000),
        "body": {"messages": [{"role": "user", "content": content}]},
    }
    (record / "lone.jsonl").write_text(json.dumps(line) + "\n")
    shown = _summary(server.port, "lone")
    assert shown["input"] == "before \ud800 after"
    assert _summary(server.port, "act-1")["rounds"] == 2
    entry = _get_json(server.port, "/api/entry?id=lone&line=0")
    assert entry["body"]["messages"][0]["content"] == content


def test_a_request_whose_response_was_never_written_keeps_no_later_response() -> None:
    lines = [
        viewer.Entry(0, "planning", "given", 1.0, "", {"messages": []}),
        # Round 1's returned entry was never written (ADR-0314 §2:4).
        viewer.Entry(1, "planning", "given", 5.0, "", {"messages": []}),
        viewer.Entry(2, "planning", "returned", 6.0, "", {"response": {"parts": []}}),
    ]
    shown = viewer.timeline("a", lines)
    calls = [one for one in shown["items"] if one["kind"] == "call"]
    assert [(one["round"], one["lines"], one["tone"]) for one in calls] == [
        (2, [1, 2], "ok"),
        (1, [0], "pending"),
    ]
    assert "returned" not in shown["rounds"][0]
    assert shown["rounds"][1]["returned"] == 2


def _planning_step(line: int, start: float, end: float) -> Any:
    def stamp(seconds: float) -> str:
        return datetime.fromtimestamp(seconds, UTC).isoformat()

    body = {"stage": "planning", "due": "round_due", "outcome": "done"}
    body |= {"started_at": stamp(start), "ended_at": stamp(end)}
    return viewer.Entry(line, "controller", "step", end, "", body)


def _rounds_of(shown: Any) -> list[tuple[str, object, object]]:
    return [
        (one["kind"], one["round"], one["lines"])
        for one in shown["items"]
        if one["lane"] == "planning"
    ]


def test_a_round_whose_step_was_never_written_takes_no_other_rounds_number() -> None:
    lines = [
        viewer.Entry(0, "planning", "given", 1.0, "", {}),
        viewer.Entry(1, "planning", "returned", 2.0, "", {}),
        # Round 1's step entry was never written; round 2's was.
        viewer.Entry(2, "planning", "given", 5.0, "", {}),
        viewer.Entry(3, "planning", "returned", 6.0, "", {}),
        _planning_step(4, 4.0, 7.0),
    ]
    shown = viewer.timeline("a", lines)
    assert sorted(_rounds_of(shown), key=str) == sorted(
        [("call", 1, [0, 1]), ("call", 2, [2, 3]), ("step", 2, [4])], key=str
    )
    assert shown["rounds"][1]["step"]["line"] == 4
    assert "step" not in shown["rounds"][0]


def test_a_response_never_crosses_into_another_rounds_step() -> None:
    lines = [
        viewer.Entry(0, "planning", "given", 1.0, "", {}),
        # Round 1's response and round 2's request were never written.
        _planning_step(1, 0.5, 3.0),
        viewer.Entry(2, "planning", "returned", 6.0, "", {}),
        _planning_step(3, 4.0, 7.0),
    ]
    shown = viewer.timeline("a", lines)
    assert sorted(_rounds_of(shown), key=str) == sorted(
        [("call", 1, [0]), ("step", 1, [1]), ("returned", 2, [2]), ("step", 2, [3])], key=str
    )
    pending = next(one for one in shown["items"] if one["kind"] == "call")
    assert pending["tone"] == "pending"


# --- §3:3: a model call, readable beside its bodies ---------------------------------------


@pytest.fixture
def calls(record: Path) -> Path:
    """The record, with the activation of model calls and the odd one written beside it."""
    return write_calls(record)


def _call(port: int, activation_id: str, line: int) -> Any:
    return _get_json(port, f"/api/call?id={activation_id}&line={line}")


def _paragraphs(view: Any) -> list[str]:
    return [part["text"] for section in view["told"]["sections"] for part in section["parts"]]


def test_a_planning_call_reads_as_told_given_offered_and_done(server: Any, calls: Path) -> None:
    view = _call(server.port, CALLS, ROUND_1_GIVEN)
    assert (view["source"], view["round"]) == ("planning", 1)
    assert (view["given"], view["returned"]) == (ROUND_1_GIVEN, ROUND_1_RETURNED_LINE)
    # What it was told: the instructions, a paragraph to a part, each sized and estimated.
    assert _paragraphs(view) == [ROLE, LABELS, CALLS_RULE]
    first = view["told"]["sections"][0]["parts"][0]
    assert (first["n"], first["chars"], first["tokens"]) == (
        1,
        len(ROLE),
        viewer.estimate(len(ROLE)),
    )
    # What it was given: the user message's JSON, a key to a part, its lists counted.
    (message,) = view["input"]
    assert (message["role"], message["form"]) == ("user", "json")
    keys = {one["key"]: one for one in message["keys"]}
    assert list(keys) == list(ROUND_1_INPUT)
    assert keys["stories"]["kind"] == "list · 2 items"
    assert keys["stories"]["chars"] == len(json.dumps(ROUND_1_INPUT["stories"]))
    assert {"path": "stories[].notes", "lists": 2, "items": 2} in keys["stories"]["lists"]
    assert json.loads(keys["stories"]["text"]) == ROUND_1_INPUT["stories"]
    # What it could do: the tools offered to the provider, the reserved one last.
    tools = view["tools"]
    assert tools["from"] == "returned"
    assert [(one["name"], one["reserved"]) for one in tools["tools"]] == [
        ("web_search", False),
        ("send_email", False),
        ("planning_round", True),
    ]
    assert json.loads(tools["tools"][0]["schema"]) == WEB_SEARCH["parameters"]
    # What it did: the response's parts in order, the round tool's as its notes and asks.
    did = view["did"]
    assert [(one["kind"], one["title"]) for one in did["parts"]] == [
        ("thinking", "Thinking (the provider's summary)"),
        ("text", "Text"),
        ("call", "Call · web_search"),
        ("notes", "Episode notes"),
        ("asks", "Asks named"),
    ]
    assert json.loads(did["parts"][2]["text"]) == {"query": "flights to Lisbon"}
    assert did["parts"][2]["id"] == "c1"
    assert did["parts"][3]["text"] == "Looking for flights."
    assert did["parts"][4]["items"] == ["c0"]
    assert did["usage"] == {"input": 12_345, "output": 456, "cache read": 10_000, "cache write": 0}
    assert view["notes"] == []
    # The same call, asked for by its returned entry.
    assert _call(server.port, CALLS, ROUND_1_RETURNED_LINE) == view


def test_understandings_call_says_it_records_no_usage(server: Any, calls: Path) -> None:
    view = _call(server.port, CALLS, UNDERSTANDING_RETURNED)
    assert view["given"] == UNDERSTANDING_GIVEN
    sections = view["told"]["sections"]
    assert [one["heading"] for one in sections] == [None, "What to return", "RULES"]
    assert [[part["n"] for part in one["parts"]] for one in sections] == [[1], [2], [3]]
    assert view["tools"] is None
    assert view["changes"] is None
    did = view["did"]
    assert did["usage"] is None
    assert "#3090" in did["usage_note"]
    assert [one["kind"] for one in did["parts"]] == ["reply"]
    assert json.loads(did["parts"][0]["text"]) == {"meaning": "find a flight"}


def test_a_digest_parts_call_shows_its_question_reply_and_dropped_items(
    server: Any, calls: Path
) -> None:
    view = _call(server.port, CALLS, DIGEST_GIVEN_LINE)
    assert view["returned"] == DIGEST_RETURNED_LINE
    assert view["about"] == {
        "question": "Which flight is cheapest?",
        "result": "r1",
        "part": "1 of 1",
    }
    assert [one["key"] for one in view["input"][0]["keys"]] == ["question", "records"]
    assert [one["title"] for one in view["did"]["parts"]] == ["Reply", "Dropped evidence"]
    assert view["did"]["usage"] is None
    assert view["round"] is None


def test_a_round_shows_what_changed_in_its_request_since_the_round_before(
    server: Any, calls: Path
) -> None:
    assert _call(server.port, CALLS, ROUND_1_GIVEN)["changes"] is None
    changes = _call(server.port, CALLS, ROUND_2_GIVEN)["changes"]
    assert (changes["against"], changes["against_round"]) == (ROUND_1_GIVEN, 1)
    shown = {one["part"]: one for one in changes["parts"]}
    assert {name: one["change"] for name, one in shown.items()} == {
        "instructions": "changed",
        "input · understood": "unchanged",
        "input · place": "unchanged",
        "input · stories": "unchanged",
        "input · rounds": "changed",
        "input · results": "added",
        "tool · web_search": "unchanged",
        "tool · send_email": "removed",
    }
    # A changed paragraph is its own line of the diff; the others are its context.
    diff = shown["instructions"]["diff"]["lines"]
    assert [one for one in diff if one.startswith(("+", "-"))] == ["+" + ADDED]
    assert " " + CALLS_RULE in diff
    assert any(one.startswith('+  "round": 1') for one in shown["input · rounds"]["diff"]["lines"])
    assert shown["input · rounds"]["before"] == len("[]")
    assert shown["tool · send_email"]["before"] == len(json.dumps(SEND_EMAIL))


def test_a_call_the_record_holds_half_of_says_what_is_missing() -> None:
    given = viewer.Entry(0, "planning", "given", 1.0, "", {"messages": [], "tools": [WEB_SEARCH]})
    returned = viewer.Entry(1, "understanding", "returned", 2.0, "", {"reply": "ok"})
    pending = viewer.model_call([given], 0)
    assert pending is not None
    assert pending["returned"] is None
    assert pending["did"] is None
    # With no returned entry, the tools are the request's own.
    assert pending["tools"]["from"] == "given"
    assert any("No returned entry" in one for one in pending["notes"])
    lone = viewer.model_call([returned], 0)
    assert lone is not None
    assert (lone["given"], lone["told"], lone["input"]) == (None, None, None)
    assert any("No given entry" in one for one in lone["notes"])
    assert lone["did"]["parts"][0]["text"] == "ok"


def test_a_line_that_is_no_model_call_has_no_call_view(server: Any, calls: Path) -> None:
    read = viewer.Record(calls).lines(CALLS)
    assert read is not None
    lines = read[0]
    for number, line in enumerate(lines):
        is_call = (
            isinstance(line, viewer.Entry)
            and line.source in {"understanding", "planning", "digesting"}
            and line.kind in {"given", "returned"}
        )
        assert (viewer.model_call(lines, number) is not None) == is_call, number
    for path in (
        f"/api/call?id={CALLS}&line=2",
        f"/api/call?id={CALLS}&line=6",
        f"/api/call?id={CALLS}&line={len(lines)}",
        f"/api/call?id={CALLS}&line=-1",
        f"/api/call?id={CALLS}&line=x",
        f"/api/call?id={CALLS}",
        f"/api/call?id=act-1&line={len(ACTIVATION) + len(FOREIGN_LINES)}",
    ):
        status, _headers, _body = _request(server.port, path)
        assert status == 404, path


def test_bodies_of_other_shapes_lose_their_parts_and_say_so(server: Any, calls: Path) -> None:
    read = viewer.Record(calls).lines(ODD)
    assert read is not None
    lines = read[0]
    views = [viewer.model_call(lines, number) for number in range(len(lines))]
    json.dumps(views, allow_nan=False)
    # Messages that are no list: nothing to split, and said so.
    first = views[0]
    assert first is not None
    assert (first["told"], first["input"]) == (None, None)
    assert any("no list of messages" in one for one in first["notes"])
    # Unnamed tools are counted and left out; a response with no parts says so.
    assert first["tools"] == {"from": "returned", "tools": [], "unnamed": 2}
    assert "no response parts" in first["did"]["odd"]
    # Content that is not text is still shown, as JSON, and marked.
    odd = views[2]
    assert odd is not None
    assert [(one["form"], one.get("odd")) for one in odd["input"]] == [("text", True)] * 2
    assert "no reply" in odd["did"]["odd"]
    # Text that is not JSON stays text; a failed response shows its failure.
    text = views[5]
    assert text is not None
    assert text["input"] == [
        {"index": 1, "role": "user", "form": "text", "text": "{not json", "chars": 9, "tokens": 3}
    ]
    assert text["did"]["failure"] == "ModelError boom"
    # A body that is no object: the call stands, its request unread.
    last = views[len(ODD_ENTRIES)]
    assert last is not None
    assert last["input"] is None
    # The line that is not JSON is no call.
    assert views[-1] is None
    status, _headers, _body = _request(server.port, f"/api/call?id={ODD}&line={len(lines) - 1}")
    assert status == 404


def test_every_odd_body_reads_as_a_call_or_none_and_never_fails() -> None:
    lines = [viewer.parse_line(number, raw) for number, raw in enumerate(_odd_lines())]
    for number in range(len(lines)):
        json.dumps(viewer.model_call(lines, number), allow_nan=False)


def test_instructions_split_at_paragraphs_under_the_headings_they_have() -> None:
    text = (
        "Opening paragraph,\nwith a line break inside it.\n\n"
        "# A Markdown heading\n"
        "and its first paragraph.\n\n"
        "Note: a lead-in is no heading\nwhere its paragraph goes on.\n\n"
        "Standing alone:\n\n"
        "Under it.\n\n\n"
        "  \n\n"
        "IN CAPITALS\n\n"
        "Last."
    )
    sections = viewer.instruction_sections(text)
    assert [(one["heading"], [part["text"] for part in one["parts"]]) for one in sections] == [
        (None, ["Opening paragraph,\nwith a line break inside it."]),
        (
            "A Markdown heading",
            [
                "and its first paragraph.",
                "Note: a lead-in is no heading\nwhere its paragraph goes on.",
            ],
        ),
        ("Standing alone", ["Under it."]),
        ("IN CAPITALS", ["Last."]),
    ]
    assert viewer.instruction_sections("") == []


def test_a_large_request_is_split_and_compared_within_bounds() -> None:
    paragraphs = [f"Paragraph {number}: " + "word " * 40 for number in range(viewer.MAX_PARTS + 50)]
    sections = viewer.instruction_sections("\n\n".join(paragraphs))
    parts = sections[0]["parts"]
    assert len(parts) == viewer.MAX_PARTS + 1
    assert parts[-1]["rest"] is True
    assert parts[-1]["text"].startswith(f"Paragraph {viewer.MAX_PARTS}:")
    # A diff longer than the view shows is cut, and one too large to draw is not drawn.
    before = "\n".join(f"line {number}" for number in range(viewer.DIFF_LINES * 2))
    after = "\n".join(f"line {number}!" for number in range(viewer.DIFF_LINES * 2))
    cut = viewer.text_diff(before, after)
    assert (len(cut["lines"]), cut["cut"]) == (viewer.DIFF_LINES, True)
    huge = viewer.text_diff("x" * (viewer.DIFF_CHARS + 1), "y")
    assert (huge["lines"], huge["too_large"]) == ([], True)


def _round_tool(args: object) -> list[tuple[str, str]]:
    part = {"part_kind": "tool-call", "tool_name": "planning_round", "args": args}
    body = {"response": {"parts": [part]}}
    view = viewer.model_call([viewer.Entry(0, "planning", "returned", 1.0, "", body)], 0)
    assert view is not None
    return [(one["title"], one["text"]) for one in view["did"]["parts"]]


def test_the_round_tools_arguments_of_another_shape_are_shown_as_written() -> None:
    odd = "Call · planning_round · arguments not of its shape"
    assert _round_tool({"notes": "kept", "asks": ["c1"]}) == [
        ("Episode notes", "kept"),
        ("Asks named", "c1"),
    ]
    assert _round_tool('{"notes": "kept"}') == [("Episode notes", "kept")]
    # The rejected round's own arguments are what diagnoses it: none is dropped.
    assert _round_tool({"notes": 42, "asks": "c1"}) == [
        (odd, json.dumps({"notes": 42, "asks": "c1"}, indent=1))
    ]
    assert _round_tool('{"notes": "kept", "another_round": true') == [
        (odd, '{"notes": "kept", "another_round": true')
    ]
    assert _round_tool({"asks": ["c1", 2]}) == [(odd, json.dumps({"asks": ["c1", 2]}, indent=1))]
    assert _round_tool({"notes": "kept", "another_round": True})[0] == ("Episode notes", "kept")
    part = {"part_kind": "tool-call", "tool_name": "web_search", "args": "{not json"}
    body = {"response": {"parts": [part]}}
    view = viewer.model_call([viewer.Entry(0, "planning", "returned", 1.0, "", body)], 0)
    assert view is not None
    assert view["did"]["parts"][0]["text"] == "{not json"


def test_a_diff_keeps_content_that_looks_like_its_headers() -> None:
    assert viewer.text_diff("-- old", "++ new")["lines"] == ["@@ -1 +1 @@", "--- old", "+++ new"]


def test_a_diff_of_one_change_in_a_long_part_matches_difflibs_own() -> None:
    before = [f"line {number}" for number in range(5_000)]
    for after in (
        [*before[:4_000], "inserted", *before[4_000:]],
        [*before[:10], *before[11:]],
        [*before[:-1], "changed"],
        ["first", *before],
    ):
        expected = list(difflib.unified_diff(before, after, lineterm="", n=2))[2:]
        assert viewer.text_diff("\n".join(before), "\n".join(after))["lines"] == expected


def test_a_diff_whose_changed_middle_is_too_long_is_not_drawn() -> None:
    # Matching many short, interleaved lines costs the square of their number.
    count = viewer.DIFF_SPAN
    before = "\n".join(f"{number}\na" for number in range(count))
    after = "\n".join(f"{number}\nb" for number in range(count))
    assert viewer.text_diff(before, after)["too_large"] is True
    # The lines both sides share are set aside first, so a long part changed once is drawn.
    shared = "\n".join(f"{number}" for number in range(viewer.DIFF_SPAN * 3))
    assert viewer.text_diff(shared + "\na", shared + "\nb")["lines"][-2:] == ["-a", "+b"]


def test_a_token_estimate_is_characters_over_four_rounded_up() -> None:
    assert [viewer.estimate(chars) for chars in (0, 1, 4, 5, 10_700)] == [0, 1, 1, 2, 2_675]


def _rendered(document: object, **body: object) -> dict[str, object]:
    return {
        "messages": [
            {"role": "system", "content": "instruction", "name": None},
            {"role": "user", "content": json.dumps(document), "name": None},
        ],
        **body,
    }


def test_the_input_is_read_back_from_understandings_request() -> None:
    received = {
        "received_as": "the message the user just sent on conversation:c1",
        "text": "What's on today? And the weather",
        "messages": [
            {"position": 1, "written_at": iso(1_000), "text": "What's on today?"},
            {"position": 2, "written_at": iso(2_000), "text": "And the weather"},
        ],
    }
    lines: list[Any] = [
        viewer.Entry(0, "controller", "step", 1.0, "", step("windows", "due", 0, 1)),
        viewer.Entry(1, "understanding", "given", 2.0, "", _rendered({"input": received})),
    ]
    assert viewer.timeline("a", lines)["arrival"] == {
        "from": "understanding",
        "line": 1,
        "text": "What's on today? And the weather",
        "received_as": "the message the user just sent on conversation:c1",
        "messages": [
            {"position": 1, "at": at(1_000).timestamp() * 1000, "text": "What's on today?"},
            {"position": 2, "at": at(2_000).timestamp() * 1000, "text": "And the weather"},
        ],
    }


def test_without_understanding_the_input_is_planning_place_windows_marked_item() -> None:
    document = {
        "place": {"description": "The hub's chat."},
        "place_window": [
            {"from": "the assistant", "at": iso(500), "text": "Earlier."},
            {"from": "the user", "at": iso(1_000), "is_the_input": True, "text": "Remind me at 6"},
        ],
    }
    lines: list[Any] = [viewer.Entry(0, "planning", "given", 2.0, "", _rendered(document))]
    arrival = viewer.timeline("a", lines)["arrival"]
    assert (arrival["from"], arrival["line"], arrival["text"]) == ("planning", 0, "Remind me at 6")
    assert arrival["received_as"] == "The hub's chat."
    assert [one["text"] for one in arrival["messages"]] == ["Remind me at 6"]


def test_planning_shows_each_marked_item_of_a_joined_input_in_the_windows_order() -> None:
    document = {
        "place": {"description": "The hub's chat."},
        "place_window": [
            {"from": "the user", "at": iso(1_000), "is_the_input": True, "text": "Remind me"},
            {"from": "the assistant", "at": iso(1_500), "text": "Between them."},
            {"from": "the user", "at": iso(2_000), "is_the_input": True, "text": "at 6"},
            {"from": "the user", "at": iso(2_500), "is_the_input": True, "text": 3},
        ],
    }
    lines: list[Any] = [viewer.Entry(0, "planning", "given", 2.0, "", _rendered(document))]
    arrival = viewer.timeline("a", lines)["arrival"]
    assert arrival["text"] == "Remind me\nat 6"
    assert arrival["messages"] == [
        {"position": None, "at": at(1_000).timestamp() * 1000, "text": "Remind me"},
        {"position": None, "at": at(2_000).timestamp() * 1000, "text": "at 6"},
    ]


def test_an_input_understanding_shows_no_messages_of_keeps_its_text() -> None:
    received = {"received_as": "scheduled work", "text": "Scheduled instruction"}
    lines: list[Any] = [
        viewer.Entry(0, "understanding", "given", 1.0, "", _rendered({"input": received}))
    ]
    arrival = viewer.timeline("a", lines)["arrival"]
    assert (arrival["text"], arrival["messages"]) == ("Scheduled instruction", [])


@pytest.mark.parametrize(
    "position", ["1e400", "-1e400", "NaN", "1.5", "true", '"1"', "[1]", str(2**53), "null"]
)
def test_a_position_not_a_safe_whole_number_is_dropped_and_its_message_stays(
    position: str,
) -> None:
    # Written as the request's own JSON text, since that is where an odd number is decoded.
    content = (
        f'{{"input":{{"text":"hello","messages":[{{"position":{position},"text":"hello"}}]}}}}'
    )
    body = {"messages": [{"role": "user", "content": content}]}
    lines: list[Any] = [viewer.Entry(0, "understanding", "given", 1.0, "", body)]
    shown = viewer.timeline("a", lines)
    json.dumps(shown, allow_nan=False)
    assert shown["arrival"]["messages"] == [{"position": None, "at": None, "text": "hello"}]


def test_a_message_row_with_no_text_is_dropped() -> None:
    received = {"text": "hello", "messages": [3, {"position": 1}, {"position": 2, "text": "hi"}]}
    lines: list[Any] = [
        viewer.Entry(0, "understanding", "given", 1.0, "", _rendered({"input": received}))
    ]
    arrival = viewer.timeline("a", lines)["arrival"]
    assert arrival["messages"] == [{"position": 2, "at": None, "text": "hi"}]


def _strict(raw: bytes) -> Any:
    def refuse(name: str) -> object:
        raise AssertionError(name)

    return json.loads(raw, parse_constant=refuse)


def test_an_infinite_position_leaves_the_activation_response_valid_json(
    server: Any, record: Path
) -> None:
    # The input as understanding's request carries it: JSON inside a message's content.
    content = '{"input":{"text":"hello","messages":[{"position":1e400,"text":"hello"}]}}'
    line = {
        "activation_id": "infinite",
        "source": "understanding",
        "kind": "given",
        "recorded_at": iso(300_000),
        "body": {"messages": [{"role": "user", "content": content}]},
    }
    (record / "infinite.jsonl").write_text(json.dumps(line) + "\n")
    status, _, body = _request(server.port, "/api/activation?id=infinite")
    assert status == 200, body
    arrival = _strict(body)["arrival"]
    assert arrival["text"] == "hello"
    assert arrival["messages"] == [{"position": None, "at": None, "text": "hello"}]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"messages": "odd"},
        _rendered(["not", "an", "object"]),
        _rendered({"input": {"text": 3}}),
    ],
)
def test_a_record_whose_requests_show_no_input_shows_none(body: Any) -> None:
    lines: list[Any] = [viewer.Entry(0, "understanding", "given", 1.0, "", body)]
    assert viewer.timeline("a", lines)["arrival"] is None


# --- understanding's tagged request (ADR-0353 §2, §3, §7), written by hand -------------
# ``test_activation_viewer_walk`` reads one the stage itself rendered; these hold the
# shapes it does not render there.


def _tagged(*sections: str) -> dict[str, object]:
    content = "\n\n".join(sections)
    return {"messages": [{"role": "user", "content": content, "name": None}]}


def test_each_input_of_a_tagged_stimulus_follows_its_own_framing_sentence() -> None:
    """ADR-0353 §7:1: a joined input is framed by a sentence of its own, after the first."""
    body = _tagged(
        "# The stimulus\n"
        "A stimulus reached the system at 9:00 am on Tuesday 27 October 2026: a message "
        "Maren typed in the hub chat. It contains this text:\n"
        '<said from="Maren">Remind me</said>\n'
        "\n"
        "A stimulus reached the system at 8:59 am on Tuesday 27 October 2026: a report from "
        "orders@bakery.example, taken in from other work, which was stopped. It contains this "
        "report:\n"
        '<received from="orders@bakery.example, as claimed">Cake &amp; candles</received>'
    )
    lines: list[Any] = [viewer.Entry(3, "understanding", "given", 1.0, "", body)]
    arrival = viewer.timeline("a", lines)["arrival"]
    assert (arrival["from"], arrival["line"]) == ("understanding", 3)
    assert arrival["text"] == "Remind me\nCake & candles"
    assert len(arrival["framing"]) == 2
    assert arrival["received_as"] == "\n".join(arrival["framing"])
    assert [(one["tag"], one["writer"], one["input"]) for one in arrival["messages"]] == [
        ("said", "Maren", 0),
        ("received", "orders@bakery.example, as claimed", 1),
    ]


def test_a_tagged_input_with_no_ones_words_is_its_framing_sentence_alone() -> None:
    """ADR-0353 §7:5: no content clause, and no content follows it."""
    sentence = (
        "A stimulus reached the system at 9:00 am on Tuesday 27 October 2026: an input with no "
        "one's words in it arrived from the hallway sensor."
    )
    body = _tagged(f"# The stimulus\n{sentence}", "# Knowledge")
    lines: list[Any] = [viewer.Entry(0, "understanding", "given", 1.0, "", body)]
    arrival = viewer.timeline("a", lines)["arrival"]
    assert (arrival["text"], arrival["received_as"], arrival["messages"]) == (None, sentence, [])
    assert viewer.input_of(body) is None


@pytest.mark.parametrize(
    "content",
    [
        # Tags that do not balance: the read is a hint, so nothing is read.
        '# The stimulus\nA stimulus reached the system.\n<said from="Maren">hi</received>',
        '# The stimulus\nA stimulus reached the system.\n<said from="Maren">hi',
        # Not the tagged message: it opens with no stimulus heading.
        'Something else\n# The stimulus\n<said from="Maren">hi</said>',
        "# The stimulus",
    ],
)
def test_a_tagged_request_that_does_not_read_shows_no_input(content: str) -> None:
    body = {"messages": [{"role": "user", "content": content}]}
    lines: list[Any] = [viewer.Entry(0, "understanding", "given", 1.0, "", body)]
    assert viewer.timeline("a", lines)["arrival"] is None
    assert viewer.labels_in(body, {"M1"}) == {}


def test_a_tagged_label_names_its_tags_text_or_a_containers_tags() -> None:
    """ADR-0353 §3:3, §3:6: each item the reply may cite carries ``label``; a container's
    text is its tags', and an empty tag says what it marks."""
    body = _tagged(
        '# The stimulus\nA stimulus reached the system.\n<said from="Maren">hi</said>',
        "## Stimulus origin knowledge\n"
        '<message label="H1" from="Maren" at="Mon 26 Oct 2026, 9:00 am">see you &lt;3</message>\n'
        '<message label="H2" deleted="yes"/>',
        "## Concurrent stimuli\n"
        '<stimulus label="R1" origin="the hub chat" acted="no">\n'
        '  <said from="Maren">book a table</said>\n'
        '  <said from="Maren" withheld="yes"/>\n'
        "</stimulus>",
        "### Matters\n"
        '<matter label="S1">\n  <summary from="the system">Ivy\'s party</summary>\n</matter>',
    )
    assert viewer.labels_in(body, {"H1", "H2", "R1", "S1", "M9"}) == {
        "H1": "see you <3",
        "H2": 'deleted="yes"',
        "R1": 'said: book a table\nsaid: from="Maren" withheld="yes"',
        "S1": "summary: Ivy's party",
    }


def _recalled_after(section: str, kept: int) -> dict[str, Any]:
    recalled = {"finds": [], "kept": [{"id": f"mem-{n}"} for n in range(kept)]}
    lines: list[Any] = [
        viewer.Entry(0, "recall", "given", 1.0, "", {"run": "first"}),
        viewer.Entry(1, "recall", "returned", 2.0, "", recalled),
        viewer.Entry(2, "understanding", "given", 3.0, "", _tagged("# The stimulus", section)),
    ]
    walked: dict[str, Any] = viewer.walk(lines, None, own=True)
    (first,) = [one for one in walked["steps"] if one["title"] == "Recall · first run"]
    found: dict[str, Any] = first
    return found


def test_tagged_recalled_memories_saying_why_none_shows_is_their_note() -> None:
    note = "Nothing is shown: everything recall found is already shown above."
    first = _recalled_after(f"### Recalled memories\n{note}", kept=1)
    assert first["shown"] == {
        "from": "understanding",
        "line": 2,
        "said": note,
        "items": [],
        "joined": False,
    }


def test_tagged_recalled_memories_fewer_than_were_kept_are_listed_apart() -> None:
    section = (
        "### Recalled memories\n"
        '<memory label="M1" from="the system">f</memory>\n'
        '<stimulus label="M2" at="Mon 26 Oct 2026, 9:00 am">\n'
        '  <said from="Maren">earlier</said>\n'
        "</stimulus>"
    )
    first = _recalled_after(section, kept=3)
    assert first["shown"]["joined"] is False
    assert first["shown"]["items"] == [
        {"label": "M1", "text": "f"},
        {"label": "M2", "text": "said: earlier"},
    ]
    assert [one["text"] for one in first["kept"]] == [None, None, None]
    joined = _recalled_after(section, kept=2)
    assert [one["label"] for one in joined["kept"]] == ["M1", "M2"]


def test_a_calls_view_names_the_prompt_version_origin_and_flags_on() -> None:
    prompt = {
        "name": "planning",
        "version": "f1bb64c0d5e2",
        "origin": "override",
        "flags": {"spawn": True, "waiting": False, "person": True},
    }
    given = viewer.Entry(0, "planning", "given", 1.0, "", _rendered({}, prompt=prompt))
    view = viewer.model_call([given], 0)
    assert view is not None
    assert view["prompt"] == {
        "name": "planning",
        "version": "f1bb64c0d5e2",
        "origin": "override",
        "flags_on": ["person", "spawn"],
    }
    unnamed = viewer.Entry(0, "planning", "given", 1.0, "", _rendered({}))
    named_nothing = viewer.model_call([unnamed], 0)
    assert named_nothing is not None
    assert named_nothing["prompt"] is None
