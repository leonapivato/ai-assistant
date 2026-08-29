"""Session-wide pytest configuration.

Its main job is to record which tests actually **ran and passed**, so that
``tests/core/test_protocol_triad.py`` can assert the Protocol-triad rule
against real executed assertions rather than against files that merely exist.
A conformance suite bound to a fake by a class pytest never collects runs zero
assertions; so does one whose tests are all collected and then skipped. Neither
is visible to a file-existence check, so the evidence has to come from pytest
itself.

Collection alone is not enough for the same reason, which is why the record is
built from call-phase reports and the triad check is reordered to run last --
it is the only test in the suite whose subject is the rest of the suite.

It also holds ``hermetic_assistant_env``, which closes both channels a
``Settings`` reads ambient configuration through -- ``ASSISTANT_*`` in the
environment and a ``.env`` beside the working directory -- for the modules that
build one. That belongs in a conftest
rather than in each module because it is a property of the run rather than of any
one test, and in *this* one because it is the only conftest the corpus has: mypy
checks ``tests/`` with no ``__init__.py`` anywhere under it, so a second file named
``conftest.py`` is a duplicate module and fails the gate.

It also registers ``--aged-store-scale``, the one option the leg-7 retrieval
instrument needs (issue #789). It lives here because ``pytest_addoption`` is
honoured only in the rootdir conftest, and it is a *volume* switch rather than a
selection one: both scales run the same tests, so it is deliberately absent from
``_FILTERING_OPTIONS`` below.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, TypedDict

import pytest
import pytest_asyncio
import structlog
from playwright.async_api import Error as BrowserError
from playwright.async_api import async_playwright

from ai_assistant.core.config import Settings

# A shared conformance suite with no owning subsystem package sits under
# `tests/core/` — `reader_contract.py` and `secret_contract.py` both do, because
# their Protocols' implementations live in leaf packages (ADR-0093 §2, ADR-0125 §8).
# Under pytest's `prepend` import mode a test module's *own* directory goes on
# `sys.path` and another test directory's does not, so `from secret_contract import
# ...` in `tests/secret_store/` resolves in a whole-suite run only because
# `tests/core` sorts first, and not at all when that directory is run on its own.
# Pinning it here, in the one conftest the corpus has (mypy refuses a second module
# named `conftest`), makes a narrowed run import the same suite the gate does.
sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))

# Registered by being imported: pluggy reads hook implementations off a plugin
# module's namespace, and this conftest is the only plugin the corpus has. What
# the guard refuses, and why it has to be a collection hook rather than a test,
# is in `collection_guard`'s own docstring -- in short, a `Test...` class left
# abstract is dropped from collection in silence, taking every test it inherits
# with it and leaving the run green (issue #1757). Its directory is already on
# `sys.path`: pytest's prepend import mode put it there to import this file.
from collection_guard import pytest_pycollect_makeitem  # noqa: F401  # a hook, by name

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Sequence

    from playwright.async_api import Browser
    from test_protocol_triad import CheckOutcome, TriadEvidence

# Options that narrow what is collected or run. If any is in play the record is
# a subset of the suite, and the absence of a class proves nothing. `maxfail`
# covers `-x`, which stops the run before later tests report; `ignore` and
# `ignore_glob` drop whole paths while leaving `config.args` looking complete.
_FILTERING_OPTIONS = (
    "keyword",
    "markexpr",
    "deselect",
    "lf",
    "failedfirst",
    "maxfail",
    "ignore",
    "ignore_glob",
)

#: The check whose subject is every other test, so it has to run after them.
_TRIAD_CHECK = "tests/core/test_protocol_triad.py"

#: The key a worker files its half of the triad record under, in xdist's own
#: worker-to-controller channel.
_TRIAD_OUTPUT_KEY = "triad_record"

#: Volume profiles the leg-7 retrieval instrument can run at. ``gate`` is sized
#: to keep the Definition-of-Done gate quick; ``full`` is the on-demand run that
#: produces the numbers ADR-0112 §7 gates retrieval tuning on.
_AGED_STORE_SCALES = ("gate", "full")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the aged-store instrument's volume switch (issue #789)."""
    parser.addoption(
        "--aged-store-scale",
        choices=_AGED_STORE_SCALES,
        default=_AGED_STORE_SCALES[0],
        help=(
            "Volume profile for the leg-7 retrieval instrument "
            "(tests/memory/test_aged_store_retrieval.py). Selects how large a "
            "store the latency and k-shortfall measurements are taken against; "
            "it deselects nothing."
        ),
    )


@pytest.fixture(scope="session")
def aged_store_scale(request: pytest.FixtureRequest) -> str:
    """Which volume profile the leg-7 retrieval instrument runs at."""
    return str(request.config.getoption("--aged-store-scale"))


#: The prefix ``Settings.model_config`` reads the environment under, matched
#: case-insensitively because pydantic-settings' loader is (see
#: ``tests/core/test_env_example.py``): a stray lower-case ``assistant_embedder``
#: is read exactly as the upper-case name is.
_SETTINGS_ENV_PREFIX = "ASSISTANT_"


@pytest.fixture
def hermetic_assistant_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every ``ASSISTANT_*`` variable, so the shell cannot change the verdict.

    ``Settings`` reads its fields from the environment, and a test that names some
    of them in the constructor does **not** thereby pin the rest: the unnamed ones
    still come from whatever the process was started with. So a test asserting on a
    default asserts on the developer's shell, and the assertion holds or fails by
    accident of who ran it (issue #1368). CI is the case that hides this — its
    environment is bare, so the suite is green there exactly where the exposure
    would be caught.

    Sweep rather than a list of names, for two reasons. A named list goes stale the
    moment a field is added, which is the failure mode being fixed rather than a
    variant of it; and a value that is invalid rather than merely unexpected fails
    at construction, before the field the test names is ever reached, so the fields
    a test *does* pin are no protection against it.

    It takes the test's own ``monkeypatch`` rather than opening a context of its
    own, so that a test which goes on to ``setenv`` one of these names undoes it on
    the single stack, in order. Two independent stacks can restore in the wrong
    order and leave the variable deleted for the rest of the session.

    The environment is one of two channels, and closing only it would move the
    exposure rather than end it: ``model_config`` also names ``env_file=".env"``,
    resolved against the working directory, and with the variables swept the
    dotenv source is what a value would then arrive through. A clone holding a
    ``.env`` is the ordinary way this project is configured
    (``tests/core/test_env_example.py`` is a test of that instruction), so the
    file is neutralised too -- by the setting that selects it rather than by
    moving the working directory, which is the narrower act and the one that says
    what it closes.

    Apply it to a whole module with
    ``pytestmark = pytest.mark.usefixtures("hermetic_assistant_env")``.
    """
    for variable in list(os.environ):
        if variable.upper().startswith(_SETTINGS_ENV_PREFIX):
            monkeypatch.delenv(variable, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture(autouse=True)
def structlog_configuration_is_this_test_s_own() -> Iterator[None]:
    """Give each test back the ``structlog`` configuration it started with.

    **The exposure.** ``structlog``'s configuration is process-global, and
    ``structlog.testing.capture_logs`` — which 27 modules of this suite assert
    through — replaces and restores only its *processors*. It leaves
    ``wrapper_class``, ``logger_factory`` and ``cache_logger_on_first_use``
    untouched, and each of those can silence a capture on its own: the level lives
    in ``wrapper_class`` (``core.logging._configure`` installs
    ``structlog.make_filtering_bound_logger(level)``, which drops an ``info`` call
    **before** any processor sees it), and caching binds a logger's chain on first
    use so that a later ``configure`` never reaches it. A test that leaves any of
    them moved therefore leaves every later ``capture_logs`` on that worker
    capturing nothing — and each of those tests fails saying the code under test
    logged nothing, which is a true statement about a global somebody else moved.

    **It is not one stray test.** A census over one distributed run — this fixture
    with a recorder in place of the restore — found about twenty tests in six
    modules handing the configuration on changed: ``tests/core/test_logging.py``
    (whose subject *is* the configuration, including a case that leaves
    ``cache_logger_on_first_use`` on), ``tests/models/test_routing.py``,
    ``tests/context/test_context_provider.py``,
    ``tests/permissions/test_action_policy.py``,
    ``tests/tools/test_egress_channel.py`` and ``tests/interfaces/test_cli.py``.
    None of them is wrong: each installs a configuration because that is what it is
    testing. What was missing is anything that scopes the effect to the test that
    wanted it.

    **Why it surfaced now.** Which tests share a worker with which is decided by
    xdist's distribution mode, and ADR-0216 §3 obliges this suite to run
    ``loadgroup`` (see :func:`pytest_configure`) where it used to run ``worksteal``.
    The coupling is older than either: it was reproduced on a clean ``origin/main``
    under ``--dist load``, and on this branch a run with the browser layer ignored
    failed the same way, so it is neither the layer's nor ``loadgroup``'s. Both
    ``just test-fast`` runs after this fixture landed were green where the three
    before it were not.

    **Autouse and unconditional**, in ``hermetic_assistant_env``'s spirit and for
    its reason — a verdict must not depend on state the run happened to be left in.
    It *restores* rather than resets: whatever a test inherited is what it hands on,
    so a module that configures deliberately still sees its own configuration for
    the length of the test that made it. Where structlog was **unconfigured** on the
    way in it is returned to unconfigured, because
    ``core.logging.install_redaction`` reads ``structlog.is_configured()`` and takes
    a different path on each answer — and ``tests/core/test_logging.py`` is a test
    of exactly that branch.

    Yields:
        Nothing; the configuration is restored on the way out.
    """
    was_configured = structlog.is_configured()
    held = structlog.get_config()
    snapshot = {**held, "processors": list(held["processors"])}
    try:
        yield
    finally:
        if structlog.is_configured() != was_configured or structlog.get_config() != snapshot:
            if was_configured:
                structlog.configure(**snapshot)
            else:
                structlog.reset_defaults()


#: The launch arguments ADR-0216's layer needs, and the reason each is here.
#:
#: The first two hand Chromium its own synthetic capture device, so ``getUserMedia``
#: resolves and ``MediaRecorder`` writes a real WebM/Opus blob with no microphone, no
#: prompt and no operator on a CI runner. The third is about the *playback* side: a
#: page whose audio context the browser suspends until a gesture decodes perfectly and
#: sounds nothing, which is the one failure this layer must not read as the page's own.
LAUNCH_ARGUMENTS = (
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
)

#: What ADR-0216 §6 tells a developer to run when the browser build is absent.
#: Named in the skip message, because a skip that says only "no browser" leaves the
#: reader to find the command themselves.
_BROWSER_INSTALL = "uv run playwright install chromium"


#: The only way to distribute this suite, and every other way is refused below.
#:
#: ADR-0216 §3: "One ``pytest`` run launches at most one browser process at a time,
#: whether it is serial or distributed: a distributed run launches no more browsers
#: than a serial one." The browser is a session-scoped fixture, so that holds exactly
#: when every case of the layer lands on one worker, which is what the layer's
#: ``xdist_group`` marker asks for -- and ``loadgroup`` is the only scheduling that
#: honours it. ``load`` and ``worksteal`` ignore the marker outright; ``loadfile`` and
#: ``loadscope`` keep a *module* together, which is not the same promise, and the
#: layer already spans two modules; ``each`` sends every test to every worker.
_ONLY_DISTRIBUTION = "loadgroup"


def pytest_configure(config: pytest.Config) -> None:
    """Refuse a distributed run that would scatter the browser layer (ADR-0216 §3).

    ``pyproject.toml``'s ``addopts`` selects ``loadgroup``, which is what makes the
    clause hold for every ordinary invocation -- but ``addopts`` is the *weakest*
    source of an option: a later ``--dist`` on the command line wins, and so does one
    in ``PYTEST_ADDOPTS``. Adversarial review, round 1, ``blocker``: under
    ``worksteal`` the four cases can land on four workers, each launching its own
    Chromium, and **the run is still green** -- so nothing would ever say that the
    ratified property had stopped holding.

    So it is refused rather than silently corrected. Correcting it here cannot work:
    a worker re-parses the controller's argv and ini (``workermanage.py`` sends
    ``invocation_params.args`` and, of ``config.option``, only ``basetemp``), and a
    worker suffixes a test's node id with its group only when *its own* ``--dist``
    reads ``loadgroup``. Rewriting the option on the controller would therefore buy a
    group-honouring scheduler over node ids no worker had grouped, which is the
    scattering it was meant to prevent, wearing a fix's clothes.

    A serial run is untouched: ``addopts``' mode is inert without workers, and this
    refuses nothing there.

    Args:
        config: The session's configuration.

    Raises:
        pytest.UsageError: If the run is distributed under any mode but ``loadgroup``.
    """
    mode = str(config.getoption("dist", "no"))
    if not getattr(config.option, "tx", []) or mode == "no":
        return
    if mode != _ONLY_DISTRIBUTION:
        raise pytest.UsageError(
            f"--dist {mode} would scatter the gateway's browser layer across workers, "
            f"one Chromium each, which ADR-0216 §3 forbids: a distributed run launches "
            f"no more browsers than a serial one. Use --dist {_ONLY_DISTRIBUTION} "
            f"(what pyproject.toml's addopts selects), or -n0 for a serial run."
        )


#: The substring Playwright puts in a launch refusal when the build was never
#: installed. It is matched rather than read off a code because Playwright gives the
#: condition none: every launch failure is the same `Error` class, and the message is
#: the only thing separating "you never installed it" from "it is here and will not
#: start".
_MISSING_BUILD = "Executable doesn't exist"


def classify_launch_refusal(refusal: BrowserError) -> NoReturn:
    """Answer a Playwright launch refusal the way ADR-0216 §6 requires.

    A *named* helper rather than an arm of :func:`gateway_browser`, so the one branch
    of the layer that no machine with the browser installed can reach has a caller
    that is not a browser launch (issue #1808). Every case of the layer needs the
    launch to have succeeded, so until this was lifted out it was the only line of
    the harness the suite could not execute -- and §6's skip is the clause that
    decides whether a fresh clone's anchor is discharged or its gate is simply red.

    It never returns: an absent build skips the layer, and anything else is re-raised.

    Args:
        refusal: What ``chromium.launch`` raised.

    Raises:
        BrowserError: The refusal itself, where the build is present and will not
            start -- a missing system library, a sandbox refusal. §6 skips for an
            absent build and for nothing else, so that is reported as the failure it
            is rather than quietly turned into a pass.
    """
    if _MISSING_BUILD not in str(refusal):
        raise refusal
    pytest.skip(
        "the browser ADR-0216 §5 pins is not installed in this clone; "
        f"`{_BROWSER_INSTALL}` installs it "
        "(`just setup` runs that, and CI installs it unconditionally)"
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def gateway_browser() -> AsyncIterator[Browser]:
    """The one browser the gateway's executable layer drives (ADR-0216 §3, §5, §6).

    **Session-scoped, and in this file because it has to be.** §3 says the browser
    "is started once and shared by every case in the layer", and a session-scoped
    fixture defined in a test module and imported into a second one is two fixture
    definitions and therefore two browsers. ``tests/conftest.py`` is the only
    conftest this corpus has -- mypy refuses a second module named ``conftest``
    where the test tree carries no packages -- so this is the only place a fixture
    can be shared across the layer's modules. Everything else about the layer lives
    beside its cases, in ``tests/interfaces/gateway/browser_drive.py``.

    **The full ``chromium``, named rather than defaulted.** §5 makes the full build
    what is installed and driven, and Playwright launches the lighter
    ``chromium-headless-shell`` for a headless launch unless the channel says
    otherwise. ``channel="chromium"`` is what asks for the build §5 names; the shell
    may be substituted only against the recorded comparison that section requires.

    **Absent build, skip** (§6): "Where the browser build the installed
    ``playwright`` pins is not present, the layer skips, with a message naming the
    command that installs it. That skip is a condition the suite declares, in
    ADR-0166 §1's sense, and an anchor discharged by a run carrying it is
    discharged." Only that condition skips: a browser that is present and will not
    start -- a missing system library, a sandbox refusal -- is a failure and is
    reported as one. Which of the two a refusal is, is
    :func:`classify_launch_refusal`'s to say, and it is a named function rather than
    an arm of this fixture so that the branch this machine cannot reach is still
    reachable by a test (``tests/interfaces/gateway/test_browser_harness.py``).

    Yields:
        The browser, closed when the session ends.
    """
    async with async_playwright() as driver:
        try:
            browser = await driver.chromium.launch(channel="chromium", args=list(LAUNCH_ARGUMENTS))
        except BrowserError as refusal:
            classify_launch_refusal(refusal)
        try:
            yield browser
        finally:
            await browser.close()


@dataclass
class _RunRecord:
    """What this pytest session actually ran, and whether that was the whole suite."""

    #: Test class -> names of the tests on it with at least one satisfactory
    #: call-phase report.
    reported: dict[type, set[str]] = field(default_factory=dict)
    #: Test class -> names of the tests on it with at least one *un*satisfactory
    #: report. Tracked separately from `reported` because a parametrized test
    #: reports once per case under a single name: if any case failed, was
    #: xfailed, or was skipped by a mark, the obligation is not honoured however
    #: many sibling cases passed.
    unsatisfactory: dict[type, set[str]] = field(default_factory=dict)
    #: Test class -> names of the tests on it that were honoured by opting out
    #: rather than by passing. Tracked so a suite whose obligations are *all*
    #: optional, and all skipped, cannot certify itself having asserted nothing.
    opted_out: dict[type, set[str]] = field(default_factory=dict)
    unfiltered: bool = False

    def honoured(self) -> dict[type, frozenset[str]]:
        """Return, per class, the tests whose every reported case was satisfactory."""
        return {
            cls: frozenset(names - self.unsatisfactory.get(cls, set()))
            for cls, names in self.reported.items()
        }


_RECORD = _RunRecord()

#: nodeid -> (owning class, test name, is-an-optional-obligation), so a report
#: can be attributed without the report itself carrying any of it.
_OWNERS: dict[str, tuple[type, str, bool]] = {}

#: Marker a conformance suite puts on a test its implementations may skip.
_OPTIONAL = "optional_obligation"


def _declares_optional(func: object) -> bool:
    """Report whether the *test function itself* is marked an optional obligation.

    Read off the function rather than through ``item.get_closest_marker``,
    which would also honour the mark applied to a subclass or a whole module.
    Only the conformance suite gets to say which of its obligations are
    optional; a binding class declaring its inherited tests optional and then
    skipping them all is precisely the bypass this guards.
    """
    return any(mark.name == _OPTIONAL for mark in getattr(func, "pytestmark", []))


def _is_unfiltered(config: pytest.Config) -> bool:
    """Report whether this session is running the entire configured suite."""
    if any(config.getoption(option, default=None) for option in _FILTERING_OPTIONS):
        return False
    testpaths: Sequence[str] = config.getini("testpaths")
    wanted = [str(config.rootpath / path) for path in testpaths]
    given = [str(config.rootpath / arg) for arg in config.args]
    return given == wanted


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Attribute each item to its class, and defer the triad check to the end."""
    _RECORD.unfiltered = _is_unfiltered(config)
    _OWNERS.clear()
    for item in items:
        cls = getattr(item, "cls", None)
        if cls is not None:
            _OWNERS[item.nodeid] = (
                cls,
                getattr(item, "originalname", None) or item.name,
                _declares_optional(getattr(item, "function", None)),
            )

    deferred = [item for item in items if item.nodeid.startswith(_TRIAD_CHECK)]
    if deferred:
        items[:] = [item for item in items if not item.nodeid.startswith(_TRIAD_CHECK)] + deferred

    # The seam's eligibility rule, applied once and remembered on every process.
    # A worker then hands these back; a serial session keeps the list only so the
    # checks in `test_protocol_triad` can pin the rule against what pytest really
    # collected, rather than against a name-shaped guess at it.
    eligible = [item for item in items if _EVIDENCE_FIXTURE in getattr(item, "fixturenames", ())]
    _EVIDENCE_ITEMS[:] = [item.nodeid for item in eligible]

    if _is_worker(config):
        _hand_evidence_checks_to_the_controller(config, items, eligible)


def _is_satisfactory(report: pytest.TestReport, *, optional: bool) -> bool:
    """Report whether one phase report is consistent with an obligation being met.

    Only a call-phase pass is evidence that a contract's assertions ran. A skip
    counts *only* where the suite itself marked the test ``optional_obligation``
    and the test's own body then chose to bow out -- see
    ``ContextProviderContract``'s ``serves_a_fixed_instant``, an obligation that
    genuinely does not apply to a provider serving a fixed instant.

    Any other skip is an obligation that did not happen, whatever its cause: a
    ``pytest.skip("not implemented")`` in an unmarked contract test, or a mark
    imposing a skip at setup before the body ever runs.

    ``wasxfail`` is never satisfactory: an expected failure is a contract
    assertion that did not hold, kept green by the mark.
    """
    if hasattr(report, "wasxfail"):
        return False
    if report.when == "call":
        return bool(report.passed or (report.skipped and optional))
    return not (report.skipped or report.failed)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Record how each reported phase of each test turned out."""
    owner = _OWNERS.get(report.nodeid)
    if owner is None:
        return
    cls, name, optional = owner
    if not _is_satisfactory(report, optional=optional):
        _RECORD.unsatisfactory.setdefault(cls, set()).add(name)
    elif report.when == "call":
        _RECORD.reported.setdefault(cls, set()).add(name)
        if report.skipped:
            _RECORD.opted_out.setdefault(cls, set()).add(name)


@pytest.fixture(scope="session")
def triad_evidence() -> TriadEvidence:
    """What this session ran, in the form the Protocol-triad check reads it.

    Serial sessions only: under xdist the items requesting this fixture are
    handed to the controller instead (see below), because no worker's record is
    the suite's.
    """
    return _evidence_of(_RECORD)


# ---------------------------------------------------------------------------
# A distributed session (ADR-0179)
# ---------------------------------------------------------------------------
#
# `_RECORD` is per process, and under `-n auto` there are several: each worker
# runs its own session over a share of the items, so a contract subclass that
# passed on `gw3` is simply absent from `gw0`'s record. Read from a worker, the
# triad check therefore reports every Protocol as missing its binding -- which is
# why `just test-fast` used to deselect it and why CI stayed serial (ADR-0166 §3).
#
# The record is made whole in the one process that outlives every worker. Three
# moves, and nothing here runs at all in a serial session:
#
# 1. At collection, each worker hands the evidence-dependent items *back* -- it
#    deselects them and remembers how to name them. Which items those are is read
#    off the fixture they request, not off a list of test names, so a check added
#    later inherits the arrangement by asking for the evidence.
# 2. At its session end, each worker exports its half through xdist's own
#    `workeroutput` channel: the honoured/opted-out names it recorded, plus the
#    static candidacy of each recorded class, computed here because this is the
#    process that holds the class objects. Names cross a process boundary; class
#    objects do not.
# 3. The controller takes each worker's half as the worker leaves, merges them,
#    asks `test_protocol_triad` for the verdict, and reports it under the very
#    nodeids the workers gave up. So the check is decided over the whole suite's
#    evidence and reads in the summary exactly as it does serially.
#
# The evidence travels through xdist's channel rather than a file on disk on
# purpose: this check exists because file-shaped evidence proves nothing, and a
# record a later invocation reads back is a record a stale or hand-written file
# can satisfy.

#: The fixture whose presence marks an item as one only the controller can decide.
_EVIDENCE_FIXTURE = "triad_evidence"

#: Set on every process at collection: the nodeid of each item the seam's own
#: eligibility rule selects. On a worker these are the items handed over; in a
#: serial session nothing is handed over and this is kept only so
#: ``test_protocol_triad`` can pin the seam against what pytest actually
#: collected. Reading it there rather than introspecting module globals is what
#: makes the guards see a check written as a class method, or parametrized by a
#: ``pytestmark`` on its module or class -- shapes a name-based guard misses and
#: this seam accepts.
_EVIDENCE_ITEMS: list[str] = []

#: Set on a worker: how to name each item it handed to the controller, in the
#: three fields a ``TestReport``'s location wants plus the nodeid.
_HANDED_OVER: list[_ItemPayload] = []

#: Set on the controller: one entry per worker that finished cleanly, and the
#: names of any that did not (whose share of the record is therefore missing).
_WORKER_HALVES: list[_TriadPayload] = []
_WORKERS_LOST: list[str] = []


class _ItemPayload(TypedDict):
    """Enough of one handed-over item to report an outcome under its nodeid."""

    nodeid: str
    path: str
    lineno: int
    domain: str


class _ClassPayload(TypedDict):
    """One recorded test class's half of the evidence, as names."""

    reported: list[str]
    unsatisfactory: list[str]
    opted_out: list[str]
    candidacy: dict[str, list[str]]


class _TriadPayload(TypedDict):
    """One worker's whole contribution, in types execnet can carry."""

    classes: dict[str, _ClassPayload]
    items: list[_ItemPayload]
    unfiltered: bool


def _is_worker(config: pytest.Config) -> bool:
    """Report whether this process is an xdist worker rather than the controller."""
    return hasattr(config, "workerinput")


def _evidence_of(record: _RunRecord) -> TriadEvidence:
    """Build the triad's evidence from one process's record.

    Imported here rather than at module scope because the dependency genuinely
    runs the other way: ``test_protocol_triad`` imports this conftest for the
    predicates that decide what a report means. What it owns is the
    *interpretation* of the record -- which classes could bind which Protocol --
    and that has to be computed where the class objects are.
    """
    from test_protocol_triad import (  # noqa: PLC0415 — see `_report_evidence_checks`
        TriadEvidence,
        class_key,
        static_candidacy,
    )

    return TriadEvidence(
        honoured={class_key(cls): names for cls, names in record.honoured().items()},
        opted_out={class_key(cls): frozenset(names) for cls, names in record.opted_out.items()},
        candidacy={class_key(cls): static_candidacy(cls) for cls in record.reported},
        unfiltered=record.unfiltered,
    )


def _hand_evidence_checks_to_the_controller(
    config: pytest.Config, items: list[pytest.Item], handed_over: list[pytest.Item]
) -> None:
    """Deselect the items no worker can decide, and remember how to name them."""
    if not handed_over:
        return
    items[:] = [item for item in items if item not in handed_over]
    config.hook.pytest_deselected(items=handed_over)
    _HANDED_OVER[:] = [
        _ItemPayload(
            nodeid=item.nodeid,
            path=str(item.location[0]),
            lineno=int(item.location[1] or 0),
            domain=str(item.location[2]),
        )
        for item in handed_over
    ]


def _worker_half() -> _TriadPayload:
    """Render this worker's record as something execnet can carry."""
    from test_protocol_triad import class_key, static_candidacy  # noqa: PLC0415 — as above

    classes: dict[str, _ClassPayload] = {}
    for cls in set(_RECORD.reported) | set(_RECORD.unsatisfactory) | set(_RECORD.opted_out):
        classes[class_key(cls)] = _ClassPayload(
            reported=sorted(_RECORD.reported.get(cls, set())),
            unsatisfactory=sorted(_RECORD.unsatisfactory.get(cls, set())),
            opted_out=sorted(_RECORD.opted_out.get(cls, set())),
            candidacy={
                protocol: sorted(names) for protocol, names in static_candidacy(cls).items()
            },
        )
    return _TriadPayload(classes=classes, items=list(_HANDED_OVER), unfiltered=_RECORD.unfiltered)


def _merged_evidence(halves: list[_TriadPayload]) -> TriadEvidence:
    """Union every worker's half into the evidence the whole suite produced.

    Unioned rather than intersected, and per test *name*: with the default
    distribution one class's tests are split across workers, so each worker holds
    part of one class's obligations. ``honoured`` is derived after the union for
    the same reason -- a case that failed on one worker must veto the same name
    reported satisfactory on another.
    """
    from test_protocol_triad import TriadEvidence  # noqa: PLC0415 — as above

    reported: dict[str, set[str]] = {}
    unsatisfactory: dict[str, set[str]] = {}
    opted_out: dict[str, set[str]] = {}
    candidacy: dict[str, dict[str, frozenset[str]]] = {}
    for half in halves:
        for key, entry in half["classes"].items():
            reported.setdefault(key, set()).update(entry["reported"])
            unsatisfactory.setdefault(key, set()).update(entry["unsatisfactory"])
            opted_out.setdefault(key, set()).update(entry["opted_out"])
            candidacy.setdefault(key, {}).update(
                {protocol: frozenset(names) for protocol, names in entry["candidacy"].items()}
            )
    return TriadEvidence(
        honoured={
            key: frozenset(names - unsatisfactory.get(key, set()))
            for key, names in reported.items()
        },
        opted_out={key: frozenset(names) for key, names in opted_out.items()},
        candidacy=candidacy,
        unfiltered=all(half["unfiltered"] for half in halves),
    )


def pytest_testnodedown(node: object, error: object) -> None:
    """Take a worker's half of the record as it leaves (xdist, controller side)."""
    half = getattr(node, "workeroutput", {}).get(_TRIAD_OUTPUT_KEY)
    if error is not None or half is None:
        _WORKERS_LOST.append(str(getattr(node, "gateway", node)))
        return
    _WORKER_HALVES.append(half)


def pytest_sessionfinish(session: pytest.Session, exitstatus: object) -> None:
    """Export this worker's half, or -- on the controller -- decide over them all."""
    output = getattr(session.config, "workeroutput", None)
    if output is not None:
        output[_TRIAD_OUTPUT_KEY] = _worker_half()
        return
    if _is_distributed_controller(session.config):
        _report_evidence_checks(session)


def _is_distributed_controller(config: pytest.Config) -> bool:
    """Report whether this is the controller of a session that had workers.

    ``numprocesses`` is xdist's own resolved worker count -- an int by the time
    the option is parsed, so ``-n auto`` reads as the number it chose and ``-n 0``,
    which is xdist standing down, reads as a serial run.
    """
    if _is_worker(config) or config.getoption("collectonly", default=False):
        return False
    return bool(getattr(config.option, "numprocesses", 0))


def _report_that_nothing_was_handed_over(session: pytest.Session) -> None:
    """Fail a distributed run that handed no evidence-dependent check over at all.

    The one failure this arrangement could otherwise suffer in silence, because
    it takes the nodeids to report under away with it. Every other way the record
    can be wrong leaves at least one handed-over item on the controller, so there
    is something to report against; with none, the checks were deselected on every
    worker and then simply vanish -- a green run that ran the Protocol-triad check
    nowhere. Both routes there are covered: no worker's half arrived, and halves
    that arrived carrying no items.

    It is a failure only where the checks were *collected*, which on an unfiltered
    run they always are -- ``--deselect`` and every other way of not collecting
    them makes the run filtered (see ``_FILTERING_OPTIONS``). The controller reads
    that from its own options rather than from the halves, since with no half
    there is nothing to read it from.

    Reaching this needs the channel itself to have stopped working -- xdist
    renaming ``workeroutput`` or ``pytest_testnodedown``, or a handover that keeps
    the record while dropping the item names -- which is what ADR-0179's
    **Revisit if** names as the thing this rests on. ADR-0179 §2 says a check no
    process decided is a failure, so it is reported as one, under a nodeid of its
    own rather than under a test's.
    """
    session.config.hook.pytest_runtest_logreport(
        report=_as_report(
            _ItemPayload(
                nodeid=f"{_TRIAD_CHECK}::the_workers_record_reached_the_controller",
                path=_TRIAD_CHECK,
                lineno=0,
                domain="",
            ),
            (
                "failed",
                "this session collected the whole suite and ran workers, but not one "
                "evidence-dependent check reached the controller to be decided -- so "
                "the Protocol-triad checks were deselected on every worker and "
                f"decided by nobody ({len(_WORKER_HALVES)} half/halves arrived, "
                f"{len(_WORKERS_LOST)} worker(s) were lost). The channel they travel "
                "on (xdist's `workeroutput` and `pytest_testnodedown`, and the item "
                "names inside each half) is what to look at (ADR-0179 §2).",
            ),
        )
    )
    session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _report_evidence_checks(session: pytest.Session) -> None:
    """Decide the handed-over checks over the merged record, and report them.

    Reported through ``pytest_runtest_logreport`` under the workers' own nodeids,
    which is the same door xdist puts every worker's result through, so the
    outcomes land in the counts, the failure list and the short summary exactly
    as a locally executed test's would. The exit status is set here too: by the
    time a session finishes, pytest has already decided it from the tests that
    ran, and these two did not run in any worker.
    """
    # Imported here, not at module scope: `test_protocol_triad` imports this
    # conftest, and pytest has to import (and assertion-rewrite) the test module
    # itself before anything else does.
    from test_protocol_triad import evaluate_for_controller  # noqa: PLC0415 — see above

    handed_over = {
        payload["nodeid"]: payload for half in _WORKER_HALVES for payload in half["items"]
    }
    if not handed_over:
        if _is_unfiltered(session.config):
            _report_that_nothing_was_handed_over(session)
        return
    outcomes = evaluate_for_controller(_merged_evidence(_WORKER_HALVES))
    reported = [(item, _outcome_for(item, outcomes)) for item in handed_over.values()]
    if _is_unfiltered(session.config):
        reported += _for_checks_no_item_claimed(handed_over, outcomes)
    for item, result in reported:
        session.config.hook.pytest_runtest_logreport(report=_as_report(item, result))
    if any(outcome == "failed" for _, (outcome, _message) in reported):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _for_checks_no_item_claimed(
    handed_over: dict[str, _ItemPayload], outcomes: dict[str, CheckOutcome]
) -> list[tuple[_ItemPayload, CheckOutcome]]:
    """Fail every check the controller decided that no handed-over item names.

    The mirror of ``_outcome_for``'s unclaimed-nodeid case, and the same rule read
    from the other end: there it is an item nothing decided, here it is a decision
    with no item to be reported under. Either way something in the handover has
    gone missing, and the outcome that would otherwise be silently dropped is a
    *failing* one about as often as not -- so the loss is reported as the failure
    rather than the decision it swallowed.

    Only on an unfiltered run, where both checks are collected by construction. A
    narrowed one may legitimately collect one of them and not the other (``-k`` on
    a name that matches only one), and then a decision with no item is the ordinary
    case rather than a fault.

    Only items the controller can actually decide claim anything, since only they
    name an evaluator key. An item of any other shape is already failing under
    ``_outcome_for`` with the reason; it neither covers a check nor earns a second
    report here blaming the handover for a name that in fact arrived intact.
    """
    claimed = {name for nodeid in handed_over if (name := _check_name(nodeid)) is not None}
    return [
        (
            _ItemPayload(nodeid=f"{_TRIAD_CHECK}::{name}", path=_TRIAD_CHECK, lineno=0, domain=""),
            (
                "failed",
                f"the controller decided {name!r} over the merged record, but no "
                f"worker handed over an item to report it under -- so its verdict "
                f"would have been dropped. The item names inside each half of the "
                f"record are what to look at (ADR-0179 §2).",
            ),
        )
        for name in sorted(set(outcomes) - claimed)
    ]


#: Said to whoever writes an evidence-dependent check the controller cannot
#: decide. Kept whole here because the guard in ``test_protocol_triad`` says the
#: same thing at authoring time, and the two must not drift.
_NOT_DECIDABLE = (
    "{nodeid} requests the merged record, but an evidence-dependent check must be a "
    "plain module-level function of " + _TRIAD_CHECK + ", not parametrized. "
    "`evaluate_for_controller` is keyed by bare function name, so any other shape "
    "either has no key or -- worse -- collides with another check's, and this item "
    "would be reported with a verdict computed for something else while its own body "
    "never ran. Write it as a module-level check; for several cases, write several "
    "checks or read the cases out of the record (ADR-0179 §2)."
)


def _check_name(nodeid: str) -> str | None:
    """The evaluator key an item stands for, or ``None`` if nothing can decide it.

    The seam's whole shape contract, in one place because two callers need the
    same answer: an evidence-dependent check is a module-level, unparametrized
    function of ``_TRIAD_CHECK``. Everything else is refused rather than reduced.

    Refused rather than supported, deliberately. ``evaluate_for_controller`` is
    keyed by bare function ``__name__``, and reducing a richer nodeid to its last
    component is ambiguous exactly where it is most dangerous:
    ``…::TestExtra::test_no_exemption_is_stale`` reduces onto the *existing*
    check's key, so the controller would report that check's verdict under this
    item and the new method's body would never run -- a green distributed gate on
    a check nobody evaluated, which is the one outcome ADR-0179 §2 exists to make
    impossible. A parametrized case is the same fault in a milder form.
    """
    path, sep, name = nodeid.partition("::")
    if not sep or path != _TRIAD_CHECK or "::" in name or "[" in name:
        return None
    return name


def _outcome_for(item: _ItemPayload, outcomes: dict[str, CheckOutcome]) -> CheckOutcome:
    """Return what the merged record decided for one handed-over item.

    Two ways to arrive at a failure without a Protocol being at fault, and both
    are stated as failures rather than swallowed: a worker that left without
    handing its half over (the record is then not the suite's, so an absent
    binding proves nothing), and an item nothing in
    ``evaluate_for_controller`` claims (a new evidence-dependent check whose
    author did not wire it up, which must not read as a pass).
    """
    if _WORKERS_LOST:
        return (
            "failed",
            f"the record is incomplete: {len(_WORKERS_LOST)} worker(s) left without "
            f"handing over their half ({', '.join(sorted(_WORKERS_LOST))}), so an "
            f"absent binding class proves nothing here either",
        )
    name = _check_name(item["nodeid"])
    if name is None:
        return ("failed", _NOT_DECIDABLE.format(nodeid=item["nodeid"]))
    unclaimed: CheckOutcome = (
        "failed",
        f"{item['nodeid']} was handed to the controller, but "
        f"test_protocol_triad.evaluate_for_controller has no entry for {name!r} "
        f"-- so nothing decided it",
    )
    return outcomes.get(name, unclaimed)


def _as_report(item: _ItemPayload, result: CheckOutcome) -> pytest.TestReport:
    """Render one controller-side decision as the report a worker would have sent."""
    outcome, message = result
    return pytest.TestReport(
        nodeid=item["nodeid"],
        location=(item["path"], item["lineno"], item["domain"]),
        keywords={},
        outcome=outcome,
        longrepr=(
            (item["path"], item["lineno"], f"Skipped: {message}")
            if outcome == "skipped"
            else (message or None)
        ),
        when="call",
        duration=0.0,
        start=0.0,
        stop=0.0,
    )
