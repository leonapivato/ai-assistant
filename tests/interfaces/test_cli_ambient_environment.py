"""The gate's verdict on the CLI does not depend on the shell that ran it (#1368).

The eleven tests this module pins were green on CI and red on the machine of
anyone configured as a client of a remote hub, because ``Settings`` reads every
field its constructor was not given from the environment and
``ASSISTANT_REMOTE_HUB_ADDRESS`` is exported on such a machine. The assertions
then looked for the loopback instruction and found the enrolment one. CI is what
hid it: a bare environment is the one case where the exposure cannot show.

``hermetic_assistant_env`` (``tests/conftest.py``) is the fix, and the modules that
needed it carry it as a module-level ``usefixtures`` mark. What that leaves
unproven is the fixture itself — every module carrying it runs in an environment
where, on CI, there is nothing to clear. So this module supplies the missing half:
it *configures the machine the way an owner's is* for its own duration, and then
asserts the default reading anyway.

Both channels are supplied, because a guard that closed one would move the exposure
rather than end it. ``Settings`` reads ``ASSISTANT_*`` from the process environment
**and** a ``.env`` resolved against the working directory (``model_config``), and
with the variables swept the file is what a value would then arrive through — a
clone holding a ``.env`` being the ordinary way this project is configured.

The ordering is load-bearing and is pytest's, not a convention. The ambient
configuration is established by a **module**-scoped fixture and closed by the
function-scoped one, and pytest instantiates higher-scoped fixtures first — which
is the order an ambient value genuinely has, in place before any test in the module
is set up.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.config import Settings
from ai_assistant.interfaces import cli
from ai_assistant.wire import HubEngineClient

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Any syntactically plausible address will do: what is under test is that the
#: variable does not reach ``Settings``, not what would happen if it did.
_AMBIENT_ADDRESS = "100.64.0.9"


@pytest.fixture(scope="module", autouse=True)
def _ambient_configuration(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Stand in for the machine of an owner whose laptop is a client of a remote hub.

    Both channels at once: the variable exported into the process, and a ``.env`` in
    the directory the process runs from. Module-scoped so it is established before
    the function-scoped guard runs, and opened as its own context because
    ``monkeypatch`` is function-scoped and cannot be asked for here.
    """
    with pytest.MonkeyPatch.context() as ambient:
        ambient.setenv("ASSISTANT_REMOTE_HUB_ADDRESS", _AMBIENT_ADDRESS)
        clone = tmp_path_factory.mktemp("ambient-clone")
        (clone / ".env").write_text(
            f"ASSISTANT_REMOTE_HUB_ADDRESS={_AMBIENT_ADDRESS}\n", encoding="utf-8"
        )
        ambient.chdir(clone)
        yield


pytestmark = pytest.mark.usefixtures("hermetic_assistant_env")


def test_an_ambient_remote_hub_address_does_not_reach_a_test_built_settings(
    tmp_path: Path,
) -> None:
    """The reading is the default one, on a machine configured to give another.

    The two channels are asserted separately from the reading because each can pass
    for the wrong reason on its own: the client check would survive the guard's
    removal if the transport choice later stopped consulting the setting, and the
    channel checks alone never show that the choice a test makes follows from them.
    The ``.env`` is asserted *present* rather than absent — the file is real and
    stays real; the claim is that it is not read.

    Together they are what the eleven tests rest on: a ``Settings`` a test builds is
    the suite's, and the machine the suite runs on contributes nothing to it.
    """
    assert "ASSISTANT_REMOTE_HUB_ADDRESS" not in os.environ
    assert (Path.cwd() / ".env").exists()

    settings = Settings(data_dir=tmp_path)

    assert settings.remote_hub_address is None
    assert isinstance(cli._client_for(settings), HubEngineClient)
