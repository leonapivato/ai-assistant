"""A realistic fake ``codex`` for driving ``scripts/codex-review.sh`` in tests.

The persistent-session driver (ADR-0025) does three things a trivial fake cannot
satisfy: it reads the ``thread_id`` back from a ``codex exec --json`` event
stream, it resumes a recorded thread with ``codex exec resume``, and it *proves*
each round ran read-only by reading Codex's own session rollout
(``$CODEX_HOME/sessions/.../rollout-*-<thread_id>.jsonl``). This fake mirrors all
three so a test exercises the real control flow without contacting OpenAI.

Behaviour is steered entirely by environment variables, so one script covers
every case:

- ``FAKE_CODEX_REVIEW``     — the review body written to ``-o`` (default: a
  one-finding APPROVE). Set empty to simulate a dropped/empty review.
- ``FAKE_CODEX_THREAD_ID``  — the thread id a fresh start reports (default: a
  random uuid), so a test can assert on a known id.
- ``FAKE_CODEX_FORCE_SANDBOX`` — override the sandbox policy written to the
  rollout, to exercise the read-only fail-closed path.
- ``FAKE_CODEX_RESUME_FAIL`` — when ``1``, a ``resume`` exits non-zero, standing
  in for a pruned/unavailable session (the degradation path).
- ``FAKE_CODEX_START_FAIL`` — when ``1``, a *fresh* session exits non-zero with
  its whole failure on stdout as ``--json`` events and **nothing on stderr**,
  which is what real ``codex exec --json`` does (issues #1674, #1675).
- ``FAKE_CODEX_TURN_FAILED`` — when ``1``, the turn fails while the process
  still exits **0**: a ``turn.failed`` event on stdout, no review written. The
  other half of the same illegibility.
- ``FAKE_CODEX_PROMPT_COPY`` — a path to copy the prompt (stdin) to, so a test
  can assert on what the reviewer was told.
- ``FAKE_CODEX_PRE_CMD``    — a shell snippet ``eval``'d before output is
  written, to reproduce a race (a commit or a base move mid-review).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "codex-review.sh"

# The fake mimics codex's effective-sandbox resolution: a bypass runs
# full-access; otherwise a driver-set ``-s``/``-c sandbox_mode`` wins; a test may
# force a value. The resolved policy is written into the rollout's turn_context
# exactly where real codex records it, so the driver's read-only proof reads it.
_FAKE_CODEX = r"""#!/usr/bin/env bash
set -euo pipefail

mode=start
tid=""
ofile=""
want_json=0
bypass=0
sb=""
prev=""
for a in "$@"; do
    case "$a" in
        --json) want_json=1 ;;
        --dangerously-bypass-approvals-and-sandbox) bypass=1 ;;
    esac
    case "$prev" in
        -o) ofile="$a" ;;
        -s) sb="$a" ;;
        -c) [[ "$a" == sandbox_mode=* ]] && sb="${a#sandbox_mode=}" ;;
    esac
    prev="$a"
done

if [[ "${1:-}" == "exec" && "${2:-}" == "resume" ]]; then
    mode=resume
    tid="${3:-}"
fi

# Record the argv, one per line, when asked — for tests that assert on flags.
if [[ -n "${FAKE_CODEX_ARGS_FILE:-}" ]]; then
    printf '%s\n' "$@" >"${FAKE_CODEX_ARGS_FILE}"
fi

# Capture the prompt (fed on stdin) before anything else, when asked.
if [[ -n "${FAKE_CODEX_PROMPT_COPY:-}" ]]; then
    cat >"${FAKE_CODEX_PROMPT_COPY}"
fi

# A pruned/unavailable session: resume exits non-zero, the driver degrades.
if [[ "$mode" == "resume" && "${FAKE_CODEX_RESUME_FAIL:-}" == "1" ]]; then
    echo "fake codex: session ${tid} not found" >&2
    exit 1
fi

# Reproduce a mid-review race (a commit landing, the base moving) when asked.
if [[ -n "${FAKE_CODEX_PRE_CMD:-}" ]]; then
    eval "${FAKE_CODEX_PRE_CMD}"
fi

eff="${sb:-read-only}"
[[ "$bypass" -eq 1 ]] && eff="danger-full-access"
[[ -n "${FAKE_CODEX_FORCE_SANDBOX:-}" ]] && eff="${FAKE_CODEX_FORCE_SANDBOX}"

if [[ "$mode" == "start" ]]; then
    tid="${FAKE_CODEX_THREAD_ID:-$(cat /proc/sys/kernel/random/uuid 2>/dev/null ||
        echo "fake-$$-${RANDOM}")}"
fi

# A fresh session the service refuses. The whole failure goes to STDOUT as --json
# events and stderr stays EMPTY — measured behaviour of codex-cli 0.146.0, and the
# shape that made issues #1674 and #1675 unreadable: the driver routes that stdout
# into a temp file it then deletes.
if [[ "$mode" == "start" && "${FAKE_CODEX_START_FAIL:-}" == "1" ]]; then
    if [[ "$want_json" -eq 1 ]]; then
        printf '{"type":"thread.started","thread_id":"%s"}\n' "$tid"
        printf '{"type":"error","message":"fake codex: the service refused this request"}\n'
        printf '{"type":"turn.failed","error":{"message":"fake codex: refused"}}\n'
    fi
    exit 1
fi

if [[ "$want_json" -eq 1 ]]; then
    printf '{"type":"thread.started","thread_id":"%s"}\n' "$tid"
    if [[ "${FAKE_CODEX_TURN_FAILED:-}" == "1" ]]; then
        printf '{"type":"turn.failed","error":{"message":"%s"}}\n' \
            "fake codex: the turn failed mid-stream"
    else
        printf '{"type":"turn.completed"}\n'
    fi
fi

# A turn that fails while the process still exits 0 writes no review, so `-o` is
# left untouched and the driver's empty-review guard is what catches it. The
# rollout is still written, because the read-only proof runs first and would
# otherwise be the refusal a test attributed to the wrong thing.
if [[ -n "$ofile" && "${FAKE_CODEX_TURN_FAILED:-}" != "1" ]]; then
    if [[ -n "${FAKE_CODEX_REVIEW+set}" ]]; then
        printf '%s' "${FAKE_CODEX_REVIEW}" >"$ofile"
    else
        printf 'a finding\nVerdict: APPROVE\n' >"$ofile"
    fi
fi

# Write the session rollout the read-only proof reads. Resume appends a fresh
# turn_context to the same thread's file, exactly as real codex does. A test can
# suppress it to exercise the "unprovable sandbox" fail-closed path.
if [[ "$want_json" -eq 1 && -n "${CODEX_HOME:-}" && -n "$tid" &&
    "${FAKE_CODEX_NO_ROLLOUT:-}" != "1" ]]; then
    d="${CODEX_HOME}/sessions/2026/07/21"
    mkdir -p "$d"
    f="${d}/rollout-fake-${tid}.jsonl"
    if [[ ! -f "$f" ]]; then
        printf '{"type":"session_meta","payload":{"session_id":"%s"}}\n' "$tid" >>"$f"
    fi
    printf '{"type":"turn_context","payload":{"sandbox_policy":{"type":"%s"}}}\n' \
        "$eff" >>"$f"
fi
"""


def install_fake_codex(bin_dir: Path) -> Path:
    """Write the fake ``codex`` into ``bin_dir`` and return its path."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    codex = bin_dir / "codex"
    codex.write_text(_FAKE_CODEX)
    codex.chmod(0o755)
    return codex


def review_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    """A subprocess env with the fake on PATH and an isolated ``CODEX_HOME``.

    ``TMPDIR`` and ``CODEX_HOME`` are redirected under ``tmp_path`` so each test
    owns them — the read-only proof reads the fake rollout from this
    ``CODEX_HOME``, never the developer's real one. The CI-signal variables are
    cleared so a test running under Actions still exercises the local path.
    """
    env = os.environ.copy()
    env.pop("GITHUB_ACTIONS", None)
    env.pop("CODEX_REVIEW_NO_SANDBOX", None)
    for key in list(env):
        if key.startswith("FAKE_CODEX_"):
            del env[key]
    bin_dir = tmp_path / "bin"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(exist_ok=True)
    private_tmp = tmp_path / "tmp"
    private_tmp.mkdir(exist_ok=True)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["CODEX_HOME"] = str(codex_home)
    env["TMPDIR"] = str(private_tmp)
    env.update(overrides)
    return env


def artifact_for(repo: Path, sha: str, persona: str = "adversarial") -> Path | None:
    """The review artifact recorded for ``(sha, persona)``, or ``None``.

    ADR-0027 §6 names an artifact by the anchor it is *selected* by — the loop
    identity, persona, base and tree — rather than by the commit it happens to be
    filed under, so a test cannot construct its path from a SHA. It finds it the
    way ``ship`` does: by the recorded provenance. That is the point of the
    rename, so the helper reads the fields rather than reconstructing the name.
    """
    review_dir = repo / ".review"
    if not review_dir.is_dir():
        return None
    for candidate in sorted(review_dir.glob("*.md")):
        header = candidate.read_text().splitlines()[0]
        if f" sha={sha} " in header and f" persona={persona} " in header:
            return candidate
    return None


def require_artifact(repo: Path, sha: str, persona: str = "adversarial") -> Path:
    """``artifact_for``, asserting the artifact is there."""
    found = artifact_for(repo, sha, persona)
    assert found is not None, f"no {persona} artifact recorded for {sha}"
    return found


def bash() -> str:
    """The bash interpreter path, asserted present."""
    resolved = shutil.which("bash")
    assert resolved is not None
    return resolved


#: How much of each captured stream a failure message carries. The script's own
#: diagnosis is a handful of lines on stderr, so the tail is where it is; a cap
#: keeps a runaway stream from burying it in a pytest report.
_TAIL_CHARS = 4000


def _tail(stream: str | None, label: str) -> str:
    """The last ``_TAIL_CHARS`` of ``stream``, labelled and indented."""
    if not stream:
        return f"--- {label}: empty ---"
    clipped = stream[-_TAIL_CHARS:]
    elided = "" if len(clipped) == len(stream) else f" (last {_TAIL_CHARS} chars)"
    body = "\n".join(f"  | {line}" for line in clipped.splitlines())
    return f"--- {label}{elided} ---\n{body}"


class ReviewFailed(subprocess.CalledProcessError):
    """A non-zero ``codex-review.sh``, carrying what the script actually said.

    ``subprocess.run(check=True)`` raises a plain ``CalledProcessError`` whose
    ``str()`` is the command line and the exit status — the captured streams sit
    on the exception and are never rendered. Under a flake that is the whole
    diagnosis lost: four occurrences of issue #1792 were reported with no message
    attached, because the sentence the script printed saying *why* it refused was
    on ``e.stderr`` and pytest prints only ``str(e)``.

    Subclasses rather than replaces ``CalledProcessError`` so ``returncode``,
    ``stdout`` and ``stderr`` stay where a caller expects them, and any
    ``except subprocess.CalledProcessError`` still catches it.
    """

    def __str__(self) -> str:
        """The usual one-liner, followed by both captured streams."""
        return "\n".join(
            [
                super().__str__(),
                _tail(self.stderr, "stderr (the script's own diagnosis)"),
                _tail(self.stdout, "stdout"),
            ]
        )


def run_review(  # noqa: PLR0913  # a test driver forwarding the script's knobs
    repo: Path,
    tmp_path: Path,
    persona: str = "adversarial",
    base: str | None = "main",
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
    **env_overrides: str,
) -> subprocess.CompletedProcess[str]:
    """Install the fake and drive ``codex-review.sh`` as a subprocess.

    ``base=None`` omits the base argument, so the script's own default-base
    resolution runs. Environment can be steered with ``FAKE_CODEX_*`` keyword
    overrides, or with an ``env`` dict when the keys are computed.

    Raises:
        ReviewFailed: When ``check`` and the script exits non-zero. The captured
            stderr and stdout are in the message, so a failure diagnoses itself
            in the pytest report rather than costing someone a reproduction.
    """
    install_fake_codex(tmp_path / "bin")
    args = [persona] if base is None else [persona, base]
    merged = {**(env or {}), **env_overrides}
    completed = subprocess.run(  # noqa: S603  # resolved bash, in-repo script, test env
        [bash(), str(SCRIPT), *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=review_env(tmp_path, **merged),
    )
    if check and completed.returncode != 0:
        raise ReviewFailed(
            completed.returncode,
            completed.args,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed
