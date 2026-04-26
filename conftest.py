import os
import sys

for _src in [
    "orchestrator/src",
    "agents/_base/src",
    "agents/pm/src",
    "services/approval-service/src",
    "services/pr-orchestrator/src",
]:
    _path = os.path.join(os.path.dirname(__file__), _src)
    if _path not in sys.path:
        sys.path.insert(0, _path)

import agents_base  # noqa: E402, F401
import approval_service  # noqa: E402, F401
import pm  # noqa: E402, F401
import pr_orchestrator  # noqa: E402, F401

import orchestrator  # noqa: E402, F401
