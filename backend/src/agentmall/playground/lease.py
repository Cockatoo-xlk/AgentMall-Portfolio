"""One server per persistent budget. Never unlink an active lock file."""

import fcntl
import os
from pathlib import Path

from agentmall.playground.policy import PlaygroundRejected


class ServerLease:
    def __init__(self, state_dir):
        directory = Path(state_dir)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink():
            raise PlaygroundRejected("PRIVATE_PATH_REQUIRED")
        self.fd = os.open(directory / "server.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            self.fd = None
            raise PlaygroundRejected("PLAYGROUND_ALREADY_RUNNING") from None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
