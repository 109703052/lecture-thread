import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

import pytest

import course_config
from build_reader import build
from course_config import load_course
from serve_reader import create_server, ReaderHandler

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace():
    parent = ROOT / 'data/tmp'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='course-manifest-', dir=parent) as folder:
        yield Path(folder)


def make_course(root, name):
    root.mkdir(parents=True, exist_ok=True)
    web = root / 'web'
    shutil.copytree(ROOT / 'examples/demo', web / 'course',
                    ignore=shutil.ignore_patterns('create_demo.py', 'README.md', '__pycache__'))
    tx = web / 'course/transcript.json'
    (web / 'course/transcript.corrected.json').write_bytes(tx.read_bytes())
    (web / 'cue.wav').write_bytes(b'original demo test media')
    manifest = root / 'course.json'
    manifest.write_text(json.dumps(dict(schema=1, id=name, title=name, description='Original demo',
                                        course_dir='web/course', web_root='web', output_html='index.html',
                                        media='web/cue.wav', media_kind='audio')), encoding='utf-8')
    return manifest


def test_manifest_paths_are_relative_to_the_manifest_not_cwd(workspace, monkeypatch):
    manifest = make_course(workspace / 'one', 'one')
    monkeypatch.chdir(workspace)
    course = load_course(manifest)
    assert course.course_dir == manifest.parent / 'web/course'
    assert course.url_for(course.media) == 'cue.wav'
    assert course.youtube_id == ''


@pytest.mark.parametrize('field,value', [
    ('media', '../outside.wav'), ('output_html', '../outside.html'),
    ('course_dir', '../outside'), ('id', '../private'),
    ('media_kind', 'unknown'), ('youtube_id', 'invalid'),
])
def test_invalid_manifest_cannot_export_outside_selected_root(workspace, field, value):
    manifest = make_course(workspace / 'invalid', 'invalid')
    doc = json.loads(manifest.read_text())
    doc[field] = value
    manifest.write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(ValueError):
        load_course(manifest)


def test_default_selects_local_only_when_present(workspace, monkeypatch):
    monkeypatch.setattr(course_config, 'ROOT', workspace)
    assert course_config.default_manifest() == workspace / 'courses/demo.json'
    (workspace / 'course.local.json').write_text('{}')
    assert course_config.default_manifest() == workspace / 'course.local.json'


def test_same_exporter_handles_two_courses_without_touching_originals(workspace):
    a, b = (make_course(workspace / name, name) for name in ['one', 'two'])
    originals = {m: hashlib.sha256((load_course(m).course_dir / 'transcript.json').read_bytes()).hexdigest()
                 for m in [a, b]}
    for manifest in [a, b]:
        data = build(manifest)
        assert data['course_id'] == manifest.parent.name
        assert data['youtube_source_id'] == '' and data['media_kind'] == 'audio'
        assert len(data['segments']) == 4
        assert data['segments'][3]['image'].endswith('stack-annotated.svg')
        assert all((load_course(manifest).web_root / s['image']).is_file()
                   for s in data['segments'] if s['image'])
        assert hashlib.sha256((load_course(manifest).course_dir / 'transcript.json').read_bytes()).hexdigest() == originals[manifest]


def test_export_preserves_js_words_and_escapes_embedded_html(workspace):
    manifest = make_course(workspace / 'escaping', 'escaping')
    course = load_course(manifest)
    notes_file = course.course_dir / 'authored_notes.json'
    notes = json.loads(notes_file.read_text(encoding='utf-8'))
    text = 'JS JSON COURSE_TITLE </script><script>alert(1)</script>'
    notes[0]['lesson'][0]['text'] = text
    notes_file.write_text(json.dumps(notes), encoding='utf-8')
    build(course)
    html = course.output_html.read_text(encoding='utf-8')
    payload = re.search(r'<script type="application/json" id="course-data">(.*?)</script>', html, re.S)[1]
    assert json.loads(payload)['segments'][1]['sections'][0]['text'] == text
    assert '</script>' not in payload


def test_demo_server_saves_only_selected_course_and_does_not_serve_other_course(workspace):
    one, two = (load_course(make_course(workspace / name, name)) for name in ['one', 'two'])
    build(one)
    build(two)
    server = create_server(one, port=0)
    try:
        snapshot = server.edits_store.snapshot()
        assert snapshot['youtube_id'] == 'one'
        body = dict(segment_id=0, corrected='A demo-only edit', revision=snapshot['revision'],
                    transcript_revision=snapshot['transcript_revision'])
        server.edits_store.save(body)
        assert (one.course_dir / 'transcript.manual-edits.json').is_file()
        assert not (two.course_dir / 'transcript.manual-edits.json').exists()
        assert Path(server.RequestHandlerClass.keywords['directory']) == one.web_root
        handler = ReaderHandler.__new__(ReaderHandler)
        handler.directory = str(one.web_root)
        assert not Path(handler.translate_path('/../two/web/index.html')).exists()
        assert Path(handler.translate_path('/index.html')) == one.output_html
    finally:
        server.server_close()
