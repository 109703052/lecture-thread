"""Validate the exact bytes and headers required for browser media seeks."""
import io
import sys
import tempfile
from email.message import Message
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve_reader import ReaderHandler


@pytest.fixture
def tmp_path():
    # Keep test files in the project, including in the restricted desktop sandbox.
    parent = Path(__file__).resolve().parents[1] / 'data' / 'tmp'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='reader-server-', dir=parent) as folder:
        yield Path(folder)


def request(tmp_path, value=None):
    (tmp_path / 'clip.mp4').write_bytes(b'0123456789')
    handler = ReaderHandler.__new__(ReaderHandler)
    handler.directory = str(tmp_path)
    handler.path = '/clip.mp4'
    handler.headers = Message()
    if value:
        handler.headers['Range'] = value
    headers = {}
    statuses = []
    handler.send_response = statuses.append
    handler.send_header = headers.__setitem__
    handler.end_headers = lambda: None
    source = handler.send_head()
    output = io.BytesIO()
    if source:
        with source:
            handler.copyfile(source, output)
    return statuses[0], headers, output.getvalue()


def test_reader_server_full_and_seek_ranges(tmp_path):
    status, headers, data = request(tmp_path)
    assert status == 200 and data == b'0123456789'
    assert headers['Accept-Ranges'] == 'bytes'
    status, headers, data = request(tmp_path, 'bytes=3-6')
    assert status == 206 and data == b'3456'
    assert headers['Content-Range'] == 'bytes 3-6/10'
    assert headers['Content-Length'] == '4'
    assert request(tmp_path, 'bytes=8-')[2] == b'89'
    assert request(tmp_path, 'bytes=-3')[2] == b'789'


def test_reader_server_rejects_invalid_or_outside_ranges(tmp_path):
    for value in ['bytes=10-', 'bytes=8-3', 'bytes=-0', 'bytes=0-1,3-4']:
        status, headers, data = request(tmp_path, value)
        assert status == 416 and data == b''
        assert headers['Content-Range'] == 'bytes */10'
