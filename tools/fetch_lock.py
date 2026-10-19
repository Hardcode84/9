# SPDX-License-Identifier: Apache-2.0
"""Hold an exclusive local fetch lock until the supplied file closes."""

import os


def acquire(stream):
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        stream.write(b"\0")
        stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(stream, fcntl.LOCK_EX)
