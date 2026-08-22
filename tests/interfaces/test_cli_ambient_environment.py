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
it *exports the variable* for its own duration and then asserts the default
reading anyway.

The ordering is load-bearing and is pytest's, not a convention. The variable is
set by a **module**-scoped fixture and cleared by the function-scoped one, and
pytest instantiates higher-scoped fixtures first — which is the order an ambient
variable genuinely has, established before any test in the module is set up.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.config import Settings
from ai_assistant.interfaces import cli
from ai_assistant.wire import HubEngineClient

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: Any syntactically plausible address will do: what is under test is that the
#: variable does not reach ``Settings``, not what would happen if it did.
_AMBIENT_ADDRESS = "100.64.0.9"


@pytest.fixture(scope="module", autouse=True)
def _ambient_remote_hub_address() -> Iterator[None]:
    """Stand in for the shell of an owner whose laptop is a client of a remote hub.

    Module-scoped so it is established before the function-scoped guard runs, and
    opened as its own context because ``monkeypatch`` is function-scoped and cannot
    be asked for here.
    """
    with pytest.MonkeyPatch.context() as ambient:
        ambient.setenv("ASSISTANT_REMOTE_HUB_ADDRESS", _AMBIENT_ADDRESS)
        yield


pytestmark = pytest.mark.usefixtures("hermetic_assistant_env")


def test_an_exported_remote_hub_address_does_not_reach_a_test_built_settings(
    tmp_path: Path,
) -> None:
    """The reading is the default one, and the variable is gone rather than overridden.

    Both halves are asserted because either alone can pass for the wrong reason. The
    client check alone would pass if the guard were removed and the transport choice
    later stopped reading the setting; the environment check alone would pass without
    ever showing that the choice a test makes follows from it. Together they are the
    claim the eleven tests rest on: a ``Settings`` a test builds is the suite's, and
    the shell that started the process contributes nothing to it.
    """
    assert "ASSISTANT_REMOTE_HUB_ADDRESS" not in os.environ

    settings = Settings(data_dir=tmp_path)

    assert settings.remote_hub_address is None
    assert isinstance(cli._client_for(settings), HubEngineClient)
