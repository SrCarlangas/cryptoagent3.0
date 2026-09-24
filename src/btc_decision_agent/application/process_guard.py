"""Single-instance locking and local credential loading for agent processes.

These two concerns used to live inside the V4 entry script, which meant the current
agent could not run without importing the retired one. They belong to the package,
not to a script.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def load_env_file(path: str | Path = ".env") -> None:
    """Load a local KEY=VALUE file without logging values or clobbering exports.

    `setdefault` is deliberate: an explicitly exported variable always wins over
    the file, so a service unit's Environment= cannot be silently overridden.
    """
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key.replace("_", "").isalnum():
            os.environ.setdefault(key, value)


@contextmanager
def single_instance(path: str | Path) -> Iterator[None]:
    """Fail closed when another order-authority process owns the lock.

    This guards against two processes started from the SAME command racing each
    other. It cannot protect against two different agents configured with
    different lock files, which is why only one order-authority service is ever
    installed and enabled.
    """
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SystemExit(f"another agent process owns {lock_path}") from error
        stream.seek(0)
        stream.truncate()
        stream.write(str(os.getpid()))
        stream.flush()
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


__all__ = ["load_env_file", "single_instance"]
