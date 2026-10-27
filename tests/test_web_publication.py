import hashlib
import json
from pathlib import Path

import pytest

from build_reader import build
from course_config import CourseConfig
from export_web_readonly import export


def test_publication_copies_only_referenced_assets_and_preserves_local_files(tmp_path):
    root = tmp_path / 'local'
    course_dir = root / 'course'
    (course_dir / 'slides').mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / 'examples/demo'
    for name in ['authored_notes.json', 'transcript.json', 'slide_evidence.json']:
        (course_dir / name).write_bytes((source / name).read_bytes())
    (course_dir / 'transcript.corrected.json').write_bytes((source / 'transcript.json').read_bytes())
    evidence = json.loads((course_dir / 'slide_evidence.json').read_text(encoding='utf-8'))
    for row in evidence:
        (course_dir / 'slides' / row['image']).write_bytes(b'image fixture')
    media = root / 'private.mp4'
    media.write_bytes(b'private source')
    output = root / 'index.html'
    output.write_text('local reader', encoding='utf-8')
    alignment = course_dir / 'reading_alignment.json'
    alignment.write_text('local alignment', encoding='utf-8')
    course = CourseConfig(root/'course.json','test','Test','',course_dir,root,output,media,'video','AP9JV9cCZTk')
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    published = tmp_path / 'public'
    data = build(course, publish_dir=published, audio_url='https://media.example.test/audio.m4a')
    assert data['read_only'] and data['video_provider'] == 'youtube'
    assert not data['video_src']
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p,digest in before.items())
    assert not list(published.rglob('*.mp4'))
    assert all((published/s['image']).is_file() for s in data['segments'] if s['image'])
    html = (published/'index.html').read_text(encoding='utf-8')
    assert 'id="reload-edits"' not in html
    assert 'id="edit-storage-status"' not in html
    assert data['transcript'] == json.loads((source/'transcript.json').read_text(encoding='utf-8'))
    with pytest.raises(ValueError, match='HTTPS'):
        build(course, publish_dir=tmp_path/'bad', audio_url='http://insecure.test/audio.m4a')
