"""Tests for the review verdict line both scripts must agree on (issue #555).

`scripts/codex-review.sh` decides whether codex's output is a review at all and
records the `.review/` artifact; `scripts/ship.sh` decides whether an artifact
is complete enough to post. Both make that call with the same regex against the
last non-blank line, and the two copies are deliberately duplicated — they are
standalone scripts, with no shared library to hold the rule.

The duplication is the hazard these tests exist for. A copy that drifts fails
*silently and expensively*: codex-review discards the run as a refusal, the
findings body is unrecoverable because the script cleans up its temp files, no
artifact is written, and the lane cannot ship. The quota it spends is finite and
invisible. That is exactly what #555 was — a `Verdict — BLOCK` read as "the
reviewer refused" — and it survived because the failure wears the reviewer's
face rather than the script's.

So the pattern here is **derived from production, never mirrored**. Every
behavioural case below runs the regex extracted from *both* scripts, following
the precedent `test_ship.py` sets for the `_diff_opts` fixtures: a hand-copied
constant would let production drift while the tests kept asserting against a
pattern no script uses.

Locale is pinned deliberately. Neither script sets one (`ship.sh` scopes
`LC_ALL=C` to a single `awk` and nothing more), so the pattern has to hold under
whatever the environment supplies. That rules out a bracket class of multibyte
dashes: under `LC_ALL=C`, a class of em dash, en dash and hyphen degrades to
the individual UTF-8 bytes of those code points and stops matching an em dash
at all.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).parents[2] / "scripts"
_SCRIPT_NAMES = ("codex-review.sh", "ship.sh")
_BASH = shutil.which("bash")
_LOCALE = shutil.which("locale")

# The pattern as it stood before #555: the label's separator could only be a
# colon. Kept as a literal on purpose — it is a historical constant, not
# production — so the regression cases can assert the shipped pattern actually
# moved, rather than merely passing for reasons unrelated to the fix.
_PRE_555_PATTERN = r"^(verdict:?[[:space:]]*)?(block|approve with nits|approve)\.?$"


def _verdict_pattern(script: str) -> str:
    """The verdict regex as `script` actually spells it.

    Anchored on the `^(verdict` prefix rather than on `grep -qiE` alone, because
    `ship.sh` runs a second unrelated `grep -qiE '...' <<<` for its code-fence
    check. Exactly one match is required, so a future third copy of the rule
    cannot be added quietly and then drift.
    """
    text = (_SCRIPTS / script).read_text(encoding="utf-8")
    found = re.findall(r"grep -qiE '(\^\(verdict[^']*)' <<<", text)
    assert len(found) == 1, f"{script} must carry exactly one verdict pattern, got {found}"
    pattern: str = found[0]
    return pattern


_PATTERNS = {name: _verdict_pattern(name) for name in _SCRIPT_NAMES}


def _utf8_locale() -> str | None:
    """A UTF-8 locale this machine actually has, or None to skip.

    Spelling varies (`C.UTF-8` vs `C.utf8`), and a locale that is not installed
    silently falls back to `C` — which would turn the multibyte cases into
    duplicates of the `C` cases and quietly stop testing anything.
    """
    if _LOCALE is None:
        return None
    result = subprocess.run(  # noqa: S603  # resolved locale path, no user input
        [_LOCALE, "-a"], capture_output=True, text=True, check=False
    )
    for name in result.stdout.split():
        if name.lower().replace("-", "") in {"c.utf8", "en_us.utf8"}:
            return name
    return None


_UTF8 = _utf8_locale()
_LOCALES = ["C"] + ([_UTF8] if _UTF8 else [])

# Verdict lines a genuine review ends with, as they look *after* the scripts'
# own normalisation (`tr -d '*#\`'` then a whitespace trim), which is why no
# markdown emphasis appears here. The dash rows are #555 itself: the reviewer
# writes the separator interchangeably, and three of these four spellings were
# being discarded as refusals.
_ACCEPTED = [
    "BLOCK",
    "APPROVE",
    "APPROVE WITH NITS",
    "Verdict: BLOCK",
    "VERDICT: APPROVE",
    "Verdict \u2014 BLOCK",  # em dash, spaced: the shape observed on lane A of #546
    "Verdict \u2013 APPROVE",  # en dash, spaced
    "Verdict - APPROVE",  # hyphen, spaced
    "Verdict\u2014BLOCK",  # em dash, unspaced
    "Verdict: APPROVE WITH NITS",
    "Verdict \u2014 approve with nits",
    "verdict: block",  # the check is case-insensitive
    "Approve with nits.",  # the rubric's trailing period
]

# What the guard exists to catch, and must keep catching however wide the
# separator gets. A refusal or a timeout does not end in a line that *is* a
# verdict word — the whole-line anchor and the exact wording do the work, not
# the label. Mid-line and trailing-prose cases are the ones a substring search
# would wrongly accept.
_REJECTED = [
    "I'm unable to review this repository",
    "I cannot provide a verdict or APPROVE this change",
    "Sorry, I can't help with that.",
    "The verdict is BLOCK because of the following",  # verdict word mid-line
    "BLOCK the merge until this is fixed",  # trailing prose
    "Verdict pending",
    "unable to APPROVE",
    "approve with nits and also block",
    "",  # empty output
    "Verdict:",  # a label with no verdict
]


def _matches(pattern: str, line: str, locale: str) -> bool:
    """Whether `grep -qiE` accepts `line`, run exactly as the scripts run it."""
    assert _BASH is not None
    result = subprocess.run(  # noqa: S603  # resolved bash path, test-controlled input
        [_BASH, "-c", 'grep -qiE "$1" <<<"$2"', "_", pattern, line],
        env={"PATH": "/usr/bin:/bin", "LC_ALL": locale},
        check=False,
    )
    return result.returncode == 0


@pytest.mark.parametrize("script", _SCRIPT_NAMES)
@pytest.mark.parametrize("locale", _LOCALES)
@pytest.mark.parametrize("line", _ACCEPTED)
def test_a_conforming_verdict_line_is_accepted(script: str, locale: str, line: str) -> None:
    """Every spelling of the closing line a real review carries.

    Run per script rather than once, so the two copies are checked for
    *behaviour* and not only for byte-equality — a divergence introduced along
    with a matching edit to the equality test would still be caught here.
    """
    assert _matches(_PATTERNS[script], line, locale), (
        f"{script} rejects a conforming verdict under LC_ALL={locale}: {line!r}"
    )


@pytest.mark.parametrize("script", _SCRIPT_NAMES)
@pytest.mark.parametrize("locale", _LOCALES)
@pytest.mark.parametrize("line", _REJECTED)
def test_a_refusal_or_a_non_verdict_is_still_rejected(script: str, locale: str, line: str) -> None:
    """The guard must not have been widened into uselessness.

    Widening the separator is only safe because the anchor is what rejects a
    refusal. If a future edit relaxes the anchor or the verdict wording, these
    cases are what fails — including the two refusal sentences the scripts' own
    comments cite as the thing being guarded against.
    """
    assert not _matches(_PATTERNS[script], line, locale), (
        f"{script} accepts a non-verdict under LC_ALL={locale}: {line!r}"
    )


def test_the_two_copies_of_the_verdict_pattern_are_identical() -> None:
    """The divergence that would not fail loudly.

    `codex-review.sh` decides what becomes an artifact and `ship.sh` decides
    what may be posted. If the two spellings drift, a review the recorder
    accepts can be one the shipper rejects, stranding a valid review with no way
    to ship it — and nothing reports it, because each script is individually
    self-consistent. Mirrors
    `test_the_patch_identity_block_is_byte_identical_in_both_scripts`, which
    pins the other rule these two scripts must agree on.
    """
    codex, ship = (_PATTERNS[name] for name in _SCRIPT_NAMES)
    assert codex == ship, f"the verdict pattern has drifted:\n  codex: {codex}\n  ship:  {ship}"


@pytest.mark.parametrize(
    "line", ["Verdict \u2014 BLOCK", "Verdict \u2013 APPROVE", "Verdict - APPROVE"]
)
@pytest.mark.parametrize("locale", _LOCALES)
def test_the_dash_separated_verdicts_of_issue_555_were_previously_discarded(
    line: str, locale: str
) -> None:
    """The regression itself: these rows failed before the fix and pass after.

    Without this, every case above could pass against a pattern that never
    moved. Asserting the *old* pattern rejects exactly what the new one accepts
    is what makes the accepted-cases list evidence of the fix rather than
    evidence of the status quo.
    """
    assert not _matches(_PRE_555_PATTERN, line, locale), (
        f"the pre-#555 pattern was expected to discard {line!r}"
    )
    assert _matches(_PATTERNS["ship.sh"], line, locale), (
        f"the shipped pattern must accept {line!r} under LC_ALL={locale}"
    )


@pytest.mark.parametrize("locale", _LOCALES)
def test_an_enumerated_dash_class_would_not_have_survived_the_c_locale(locale: str) -> None:
    """Why the separator is a class of non-alphanumerics, not a list of dashes.

    The fix originally proposed for #555 enumerated the dashes as a bracket
    class of colon, em dash, en dash and hyphen. Two of those are multibyte code
    points, and a bracket expression matches *bytes* under `LC_ALL=C` — so the
    enumeration matches one byte of an em dash and breaks on the other two,
    discarding the very rows it was written to fix. Since no script pins a
    locale, that
    spelling would have reintroduced the bug on any machine running a non-UTF-8
    environment while passing on the one it was written on.

    Pinned as a property of the shipped pattern rather than of the rejected one:
    what must stay true is that the pattern carries no multibyte literal, so it
    cannot acquire a locale dependency in a later edit.
    """
    pattern = _PATTERNS["ship.sh"]
    assert pattern.isascii(), f"the verdict pattern must stay locale-independent: {pattern!r}"
    assert _matches(pattern, "Verdict \u2014 BLOCK", locale)


def _artifact_has_verdict(artifact: Path, locale: str) -> bool:
    """Run `ship.sh`'s real `artifact_has_verdict` against a file.

    The function is evaluated on its own rather than by running `ship.sh`, which
    would need a repo, a remote and a fake `gh`. Extracting it exercises the
    whole rule at its call site — the blank-line strip, the markdown strip, the
    trim, the pattern, and the two-body-line minimum — against the bytes
    production actually carries.
    """
    assert _BASH is not None
    text = (_SCRIPTS / "ship.sh").read_text(encoding="utf-8")
    match = re.search(r"^artifact_has_verdict\(\) \{\n.*?^\}\n", text, re.MULTILINE | re.DOTALL)
    assert match is not None, "no `artifact_has_verdict` function found in ship.sh"
    result = subprocess.run(  # noqa: S603  # resolved bash path, test-controlled input
        [_BASH, "-c", f'{match.group(0)}\nartifact_has_verdict "$1"', "_", str(artifact)],
        env={"PATH": "/usr/bin:/bin", "LC_ALL": locale},
        check=False,
    )
    return result.returncode == 0


@pytest.mark.parametrize("locale", _LOCALES)
def test_ship_accepts_a_dash_separated_artifact_end_to_end(tmp_path: Path, locale: str) -> None:
    """The fix holds at the call site, not only against the extracted string.

    An artifact looks like the real thing: a provenance header on line 1 (which
    `ship` strips before posting and does not count as body), findings, then the
    closing verdict. This is the shape that could not be shipped at all before
    the fix, because it was never recorded in the first place.
    """
    artifact = tmp_path / "review.md"
    artifact.write_text(
        "<!-- persona=adversarial base_sha=abc123 patch_id=deadbeef -->\n"
        "**major** `scripts/thing.sh:12` — the guard fails open here.\n"
        "**nit** `scripts/thing.sh:40` — stale comment.\n"
        "\n"
        "**Verdict \u2014 BLOCK**\n",
        encoding="utf-8",
    )

    assert _artifact_has_verdict(artifact, locale)


@pytest.mark.parametrize("locale", _LOCALES)
def test_ship_still_refuses_an_artifact_that_is_a_refusal(tmp_path: Path, locale: str) -> None:
    """A refusal must not become postable as a side effect of the widening."""
    artifact = tmp_path / "review.md"
    artifact.write_text(
        "<!-- persona=adversarial base_sha=abc123 patch_id=deadbeef -->\n"
        "I'm unable to review this repository.\n"
        "No changes were analysed.\n",
        encoding="utf-8",
    )

    assert not _artifact_has_verdict(artifact, locale)


@pytest.mark.parametrize("locale", _LOCALES)
def test_ship_still_refuses_a_verdict_with_no_findings(tmp_path: Path, locale: str) -> None:
    """The anti-rubber-stamping rule is independent of the separator.

    A dash-separated verdict with no body must fail for the *body* reason, so
    widening the separator cannot be a back door into posting an empty review.
    """
    artifact = tmp_path / "review.md"
    artifact.write_text(
        "<!-- persona=adversarial base_sha=abc123 patch_id=deadbeef -->\nVerdict \u2014 APPROVE\n",
        encoding="utf-8",
    )

    assert not _artifact_has_verdict(artifact, locale)
