"""Shared fixtures for the three operator-recipe script tests.

``scripts/deploy_hub.py``, ``scripts/clone_sync.py`` and ``scripts/review_sweep.py``
all want the same two things: the module loaded from its path (they are scripts,
not an installed package) and a throwaway git clone to reason about. Both live
here rather than in each file, so a change to how a fixture repository is built
happens once.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).parent))
from _repo_template import seed_bare_repo, seed_repo

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from types import ModuleType

SCRIPTS = Path(__file__).parents[2] / "scripts"
GIT = shutil.which("git") or "git"


def load(name: str) -> ModuleType:
    """Import one of the scripts by path.

    Args:
        name: The module name, e.g. ``deploy_hub``.

    Returns:
        The imported module.
    """
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` and return its stdout.

    Args:
        repo: The repository.
        *args: The git arguments.

    Returns:
        Standard output, stripped.
    """
    completed = subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [GIT, *args], cwd=str(repo), capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def init_repo(repo: Path, *, with_origin: bool = False) -> None:
    """Build a throwaway clone on ``main`` with one commit.

    Args:
        repo: Where to build it.
        with_origin: Also create a bare origin and push ``main`` to it, so
            ``origin/main`` resolves.
    """
    seed_repo(repo)
    (repo / "f.txt").write_text("one\n")
    (repo / ".gitignore").write_text(".review/\n")
    git(repo, "add", "f.txt", ".gitignore")
    git(repo, "commit", "-qm", "base")
    if with_origin:
        origin = repo.parent / f"{repo.name}-origin.git"
        seed_bare_repo(origin)
        git(repo, "remote", "add", "origin", str(origin))
        git(repo, "push", "-q", "origin", "main")


def run(
    script: str,
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one of the scripts as a subprocess.

    Args:
        script: The module name, e.g. ``clone_sync``.
        args: The command-line arguments.
        cwd: The working directory.
        env: The environment, replacing the inherited one when given.

    Returns:
        The completed process, output captured.
    """
    return subprocess.run(  # noqa: S603  # fixed interpreter + in-repo script
        [sys.executable, str(SCRIPTS / f"{script}.py"), *args],
        cwd=None if cwd is None else str(cwd),
        capture_output=True,
        text=True,
        check=False,
        env=None if env is None else dict(env),
    )
