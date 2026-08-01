"""``python -m ai_assistant.service`` — the same entry point as the console script.

Present so the hub can be started from a checkout without an installed script,
which is what a supervisor unit under development and an end-to-end test both
need. It adds no behaviour: :func:`~ai_assistant.service.hub.main` is the one
entry point and this only spells its exit code as the process's.
"""

from __future__ import annotations

import sys

from ai_assistant.service.hub import main

if __name__ == "__main__":
    sys.exit(main())
