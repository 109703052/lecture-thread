import json
import io
import sys
import tempfile
from email.message import Message
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from manual_edits import EditError, ManualEditsStore
from serve_reader import ReaderHandler


@pytest.fixture
def store():
    parent = ROOT / 'data' / 'tmp'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='manual-edits-', dir=parent) as folder:
        path = Path(folder)
        transcript = [{'start': 0, 'end': 2, 'text': '原句一'}, {'start': 2, 'end': 4, 'text': '原句二'}]
        for name in ['transcript.json', 'transcript.corrected.json']:
            (path / name).write_text(json.dumps(transcript, ensure_ascii=False), encoding='utf-8')
        yield ManualEditsStore(path, 'fixture')


def request(snapshot, index=0, text='人工修訂'):
    return dict(segment_id=index, corrected=text, revision=snapshot['revision'],
                transcript_revision=snapshot['transcript_revision'])


def test_save_sidecar_preserves_sources_and_loads_in_new_store(store):
    originals = {p: p.read_bytes() for p in store.course.glob('transcript*.json')}
    saved = store.save(request(store.snapshot()))
    assert saved['edits']['0']['corrected'] == '人工修訂'
    assert all(p.read_bytes() == content for p, content in originals.items())
    assert ManualEditsStore(store.course, 'fixture').snapshot() == saved
    doc = json.loads(store.path.read_text(encoding='utf-8'))
    assert doc['edits'][0]['segment_id'] == 0
    assert doc['edits'][0]['original'] == '原句一'


def test_stale_tabs_conflict_then_explicit_retry_preserves_other_edits(store):
    initial = store.snapshot()
    first = store.save(request(initial))
    with pytest.raises(EditError) as error:
        store.save(request(initial, 1, '第二句修訂'))
    assert error.value.status == 409 and error.value.snapshot == first
    second = store.save(request(error.value.snapshot, 1, '第二句修訂'))
    assert len(second['edits']) == 2
    reverted = store.save(request(second, 0, '原句一'))
    assert '0' not in reverted['edits'] and '1' in reverted['edits']
    assert reverted['revision'] != initial['revision']


def test_concurrent_stores_allow_only_one_writer_for_a_revision(store):
    snapshot = store.snapshot()
    other = ManualEditsStore(store.course, 'fixture')
    def save(target):
        try:
            target.save(request(snapshot))
            return 200
        except EditError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, [store, other])) == [200, 409]


def test_failed_atomic_replace_leaves_previous_file_and_cleans_temp(store, monkeypatch):
    snapshot = store.save(request(store.snapshot()))
    previous = store.path.read_bytes()
    def fail(*args):
        raise OSError('simulated write failure')
    monkeypatch.setattr('manual_edits.os.replace', fail)
    with pytest.raises(OSError):
        store.save(request(snapshot, 0, '不應寫入'))
    assert store.path.read_bytes() == previous
    assert not list(store.course.glob('.manual-edits-*.tmp'))


def test_external_file_change_and_new_ai_base_are_not_overwritten(store):
    snapshot = store.save(request(store.snapshot()))
    store.path.write_bytes(store.path.read_bytes() + b'\n')
    with pytest.raises(EditError):
        store.save(request(snapshot))
    previous = store.path.read_bytes()
    (store.course / 'transcript.corrected.json').write_text('[]', encoding='utf-8')
    with pytest.raises(EditError):
        store.save(request(snapshot))
    assert store.path.read_bytes() == previous


def test_corrupt_manual_file_is_preserved_without_overwrite(store):
    initial = store.snapshot()
    store.path.write_bytes(b'{broken')
    with pytest.raises(EditError):
        store.save(request(initial))
    assert store.path.read_bytes() == b'{broken'


@pytest.mark.parametrize('index,text', [(True, '字'), (-1, '字'), (20, '字'), (0, ''), (0, ' '), (0, '字' * 20001)],
                         ids=['bool', 'negative', 'outside', 'empty', 'blank', 'large'])
def test_invalid_edits_do_not_create_a_sidecar(store, index, text):
    with pytest.raises(EditError):
        store.save(request(store.snapshot(), index, text))
    assert not store.path.exists()


def api_request(store, body, headers=None):
    handler = ReaderHandler.__new__(ReaderHandler)
    handler.server = SimpleNamespace(server_port=8766, edit_token='test-token', edits_store=store)
    handler.path = '/api/transcript-edits'
    encoded = json.dumps(body).encode()
    handler.rfile, handler.wfile = io.BytesIO(encoded), io.BytesIO()
    handler.headers = Message()
    values = {'Host': '127.0.0.1:8766', 'Origin': 'http://127.0.0.1:8766',
              'Content-Type': 'application/json', 'X-LectureThread-Token': 'test-token',
              'Content-Length': str(len(encoded))}
    values.update(headers or {})
    for name, value in values.items():
        handler.headers[name] = value
    statuses = []
    handler.send_response = statuses.append
    handler.send_header = lambda *args: None
    handler.end_headers = lambda: None
    handler.do_POST()
    return statuses[0], json.loads(handler.wfile.getvalue())


def test_http_api_requires_same_origin_host_and_session_token(store):
    snapshot = store.snapshot()
    for header in [{'Origin': 'https://evil.example'}, {'Host': 'evil.example:8766'},
                   {'X-LectureThread-Token': 'wrong'}, {'Sec-Fetch-Site': 'cross-site'}]:
        assert api_request(store, request(snapshot), header)[0] == 403
        assert not store.path.exists()
    assert api_request(store, request(snapshot), {'Content-Type': 'text/plain'})[0] == 415
    assert api_request(store, request(snapshot))[0] == 200
    status, payload = api_request(store, request(snapshot))
    assert status == 409 and payload['snapshot']['edits']['0']['corrected'] == '人工修訂'
