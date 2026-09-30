"""Opt-in timing only; no audio or caption text leaves the machine.

Cross-process comparison uses monotonic clocks anchored to Unix time once per
process. Native and Python clocks are not assumed to share an epoch.
"""
import json
import os
import time

_path = os.getenv("LIVETR3_BACKEND_TRACE")
_handle = open(_path, "a", buffering=1) if _path else None
_monotonic_anchor = time.monotonic()
_unix_anchor = time.time()


def trace(stage: str, **fields) -> None:
    if _handle is None:
        return
    now = time.monotonic()
    _handle.write(json.dumps({"stage": stage, "monotonic": now,
                             "unix": _unix_anchor + now - _monotonic_anchor,
                             "pid": os.getpid(), **fields}, separators=(",", ":")) + "\n")
