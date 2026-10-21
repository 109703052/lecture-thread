"""Small, dependency-free primitives shared by the overnight worker."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from contextlib import contextmanager


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def replace_with_retry(source, target):
    """Retry transient Windows sharing violations without truncating the visible file."""
    for attempt in range(10):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(min(.025 * 2 ** attempt, .4))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers/virus scanners can briefly deny FILE_SHARE_DELETE.
        # Retry the atomic replacement; never truncate the visible previous snapshot.
        replace_with_retry(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def publish_immutable(path, content):
    """Publish complete original bytes atomically without ever replacing an existing file."""
    path = Path(path)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f'Preserving immutable original: {path}')
        return
    fd, name = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Windows rename fails if the destination exists; POSIX rename would overwrite.
            if os.name == 'nt':
                os.rename(name, path)
            else:
                os.link(name, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ValueError(f'Preserving immutable original: {path}')
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def exclusive_lock(path):
    """Nonblocking OS lock; the OS releases it after a crash (no stale PID lock)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if not path.stat().st_size:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('另一個課程任務仍在執行；請先等它結束。') from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
