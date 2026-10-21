"""Bounded context reads. Whole-document readers deliberately stay separate."""
import errno
import os
import stat
from contextlib import contextmanager

# The existing FORGE request-body ceiling, also used for local context work.
HISTORY_BYTES = 1_000_000
BLOCK = 8192
HEADER_BYTES = 4096


@contextmanager
def regular(path, nofollow=False):
    """Open without waiting for a FIFO writer; check the opened inode too.
    `nofollow` refuses a symlink in the file's place: for a record of
    spark's own, never for a file the user named."""
    flags = os.O_RDONLY | os.O_NONBLOCK
    if nofollow:
        flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "not a regular file")
        f = os.fdopen(fd, "rb", buffering=0)
        fd = None
        with f:
            yield f
    finally:
        if fd is not None:
            os.close(fd)


def newest_lines(f, start=0, budget=HISTORY_BYTES):
    """Whole lines, newest first, from a fixed EOF and a bounded byte window.

    None marks an omitted prefix, including a line crossing the window.
    A final line without a newline is returned for the caller to validate.
    No read or retained partial line can grow beyond budget.
    """
    end = os.fstat(f.fileno()).st_size
    floor = max(start, end - budget)
    pos, pending = end, b""
    while pos > floor:
        size = min(BLOCK, pos - floor)
        pos -= size
        f.seek(pos)
        parts = (f.read(size) + pending).split(b"\n")
        pending = parts.pop(0)
        yield from reversed(parts)
    if floor == start:
        if pending:
            yield pending
    else:
        yield None


def oldest_lines(f, budget):
    """Whole lines from the current position, bounded before allocation."""
    pending = b""
    while budget:
        chunk = f.read(min(BLOCK, budget))
        budget -= len(chunk)
        if not chunk:
            if pending:
                yield pending
            return
        parts = (pending + chunk).split(b"\n")
        pending = parts.pop()
        yield from parts
    yield None
