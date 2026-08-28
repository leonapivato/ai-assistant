"""One initialised git directory per process, copied wherever a test wants a repo.

Every module under ``tests/scripts`` builds throwaway repositories, and each build
opened with the same three subprocesses: ``git init``, and a ``git config`` for
each of the two identity fields a commit needs. Measured on this branch, that
prefix is about 6 ms of a ~9 ms build, and ``tests/scripts`` builds one repository
per test in thirteen modules.

None of it is per-repository work. ``git init`` writes a fixed directory whose
only path-dependent content is none at all -- ``core.repositoryformatversion``,
``filemode``, ``bare`` and ``logallrefupdates``, plus an empty object store and an
unborn ``HEAD`` -- so the whole of it can be built once and copied. The copy is
about 2 ms, and each test still gets a repository of its very own: nothing is
shared once it lands.

**Not a fixture**, because every caller here is a module-level helper taking a
``tmp_path``, and threading a session fixture through them would put a parameter
on every test that builds a repository. The template is built on first use and
removed at interpreter exit, which under ``-n auto`` means once per worker.
"""

from __future__ import annotations

import atexit
import shutil
import subprocess
import tempfile
from functools import cache
from pathlib import Path

GIT = shutil.which("git") or "git"

#: The identity every throwaway repository here commits under. One value, because
#: nothing asserts on it and a second would only be a way for two modules to
#: disagree.
AUTHOR_EMAIL = "t@example.com"
AUTHOR_NAME = "Test"


@cache
def _template_root() -> Path:
    """Build both templates once, and arrange for their removal.

    Returns:
        A directory holding ``worktree/.git`` and ``bare.git``.
    """
    root = Path(tempfile.mkdtemp(prefix="scripts-repo-template-"))
    atexit.register(shutil.rmtree, root, True)  # `ignore_errors`, positional-only

    worktree = root / "worktree"
    worktree.mkdir()
    _git(worktree, "init", "-q", "-b", "main")
    _git(worktree, "config", "user.email", AUTHOR_EMAIL)
    _git(worktree, "config", "user.name", AUTHOR_NAME)

    subprocess.run(  # noqa: S603  # resolved git path, temporary directory
        [GIT, "init", "-q", "--bare", "-b", "main", str(root / "bare.git")], check=True
    )
    return root


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603  # resolved git path, temporary directory
        [GIT, *args], cwd=str(repo), check=True, capture_output=True, text=True
    )


def seed_repo(repo: Path) -> None:
    """Give ``repo`` an initialised git directory on an unborn ``main``.

    Equivalent to ``git init -b main`` followed by the two identity settings, and
    the same whichever of the two spellings a module used to reach it: a bare
    ``git init`` plus ``symbolic-ref HEAD refs/heads/main`` sets exactly what
    ``-b main`` sets.

    Args:
        repo: The working tree. Created, with its parents, if it does not exist.
    """
    repo.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_template_root() / "worktree" / ".git", repo / ".git")


def seed_bare_repo(repo: Path) -> None:
    """Give ``repo`` a bare git directory on an unborn ``main``.

    Args:
        repo: The bare repository, conventionally named ``*.git``. It must not
            already exist.
    """
    shutil.copytree(_template_root() / "bare.git", repo)
