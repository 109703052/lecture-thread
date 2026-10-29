import copy
import json
from pathlib import Path
import tempfile

import pytest

from build_reader import build
from course_config import load_course
from editorial_content import validate_editorial
from editorial_publish import publish, audit_publication
from manual_edits import ManualEditsStore
from pipeline_common import atomic_json, digest, read_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def editorial_course(monkeypatch):
    with tempfile.TemporaryDirectory(dir=ROOT/'data/tmp', prefix='editorial-publish-test-') as folder:
        root = Path(folder)
        # Isolate the test lock from a real lecture preprocessing run.
        monkeypatch.setattr('editorial_publish.ROOT', root)
        (root/'reader.js').write_bytes((ROOT/'reader.js').read_bytes())
        out = root/'course'
        (out/'slides').mkdir(parents=True)
        for name in ['a.svg', 'a-annotation.svg', 'b.svg']:
            (out/'slides'/name).write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        tx = [dict(start=0, end=3, text='第一句。'), dict(start=3, end=6, text='简体第二句。'),
              dict(start=6, end=9, text='第三句。')]
        atomic_json(out/'transcript.json', tx)
        evidence = [dict(occurrence_id=i+1, start=a, end=b, image=name, title='原始標題', primary_transcript_ids=ids)
                    for i, (a, b, name, ids) in enumerate([
                        (0, 2, 'a.svg', [0]), (2, 6, 'a-annotation.svg', [1]), (6, 10, 'b.svg', [2])])]
        atomic_json(out/'slide_evidence.json', evidence)
        (root/'media.wav').write_bytes(b'test media')
        doc = dict(schema=1, author='Codex', course_date='0917', title='直接撰寫的課程', overview='完整教學脈絡。',
                   raw_transcript_sha256=digest(out/'transcript.json'), chapters=[
                       dict(title='第一章', start=0, end=6, summary='第一個核心問題。', paragraphs=[
                           dict(heading='原理解釋', time=0, text='直接撰寫的第一段。', source_ids=[0]),
                           dict(heading='條件與例子', time=3, text='直接撰寫的第二段。', source_ids=[1])],
                            checks=[dict(time=3, source_ids=[1], message='數字需要核對。')]),
                       dict(title='第二章', start=6, end=10, summary='第二個核心問題。', paragraphs=[
                           dict(heading='結論', time=6, text='直接撰寫的第三段。', source_ids=[2])], checks=[])])
        atomic_json(out/'editorial_chapters.json', doc)
        manifest = root/'course.local.json'
        atomic_json(manifest, dict(schema=1, id='editorial-test', title='舊課名', description='測試',
                                  course_dir='course', web_root='.', output_html='index.html', media='media.wav'))
        yield root, out, tx, evidence, doc, manifest


def test_rejects_stale_hash_or_coverage_holes_before_publication(editorial_course):
    root, out, tx, evidence, doc, manifest = editorial_course
    broken = copy.deepcopy(doc)
    broken['chapters'][0]['paragraphs'][1]['source_ids'] = [0]
    with pytest.raises(ValueError, match='exactly once'):
        validate_editorial(broken, tx, 10, doc['raw_transcript_sha256'])
    broken = copy.deepcopy(doc)
    broken['chapters'][1]['start'] = 7
    with pytest.raises(ValueError, match='continuously'):
        validate_editorial(broken, tx, 10, doc['raw_transcript_sha256'])
    broken = copy.deepcopy(doc)
    broken['raw_transcript_sha256'] = 'stale'
    atomic_json(out/'editorial_chapters.json', broken)
    (root/'index.html').write_text('previous reader')
    with pytest.raises(ValueError, match='hash changed'):
        publish(manifest)
    assert (root/'index.html').read_text() == 'previous reader'
    assert not (out/'backups').exists()


def test_publish_preserves_revisits_sources_and_existing_manual_base(editorial_course):
    root, out, tx, evidence, doc, manifest = editorial_course
    atomic_json(out/'transcript.corrected.json', tx)
    atomic_json(out/'authored_notes.json', [{'lesson': 'Qwen legacy must not be displayed'}])
    (root/'index.html').write_text('previous reader')
    original = digest(out/'transcript.json')
    corrected = digest(out/'transcript.corrected.json')
    edits = ManualEditsStore(out, 'editorial-test')
    snapshot = edits.snapshot()
    edits.save(dict(segment_id=0, corrected='使用者人工修訂', revision=snapshot['revision'],
                    transcript_revision=snapshot['transcript_revision']))
    manual_hash = digest(out/'transcript.manual-edits.json')
    report = publish(manifest)
    data = read_json(out/'reading_alignment.json')
    assert report['preserved_occurrences'] == 3
    assert len(data['segments']) == 6  # Overview + two chapters + all three occurrences.
    assert [s['occurrence_id'] for s in data['segments'] if s.get('occurrence_id')] == [1, 2, 3]
    assert data['segments'][-2]['image'].endswith('a-annotation.svg')
    assert data['segments'][1]['sections'][0]['source_ids'] == [0]
    assert 'Qwen legacy must not be displayed' not in (root/'index.html').read_text(encoding='utf-8')
    assert digest(out/'transcript.json') == original
    assert digest(out/'transcript.corrected.json') == corrected
    assert digest(out/'transcript.manual-edits.json') == manual_hash
    assert data['manual_edits']['edits']['0']['corrected'] == '使用者人工修訂'
    provenance = read_json(out/'authoring_provenance.json')
    assert provenance['author'] == 'Codex' and not provenance['audio_verified']
    backup = Path(provenance['backup'])
    assert any(p.read_text(encoding='utf-8') == 'previous reader' for p in backup.glob('*-index.html'))
    assert '數字需要核對' in (root/'待核對清單.md').read_text(encoding='utf-8')
    assert '原始標題' in (root/'畫面來源對照.md').read_text(encoding='utf-8')
    assert audit_publication(manifest)['metadata_valid']
    (root/'index.html').write_text('stale reader')
    with pytest.raises(ValueError, match='course data'):
        audit_publication(manifest)


def test_missing_display_transcript_only_normalizes_characters(editorial_course):
    root, out, tx, evidence, doc, manifest = editorial_course
    raw = digest(out/'transcript.json')
    publish(manifest)
    corrected = read_json(out/'transcript.corrected.json')
    assert corrected[1]['text'] == '簡體第二句。'
    assert corrected[0] == tx[0] and corrected[2] == tx[2]
    assert digest(out/'transcript.json') == raw
    corrections = read_json(out/'transcript.corrections.json')
    assert len(corrections) == 1 and corrections[0]['status'] == 'script-normalized'


def test_deck_evidence_provenance_is_not_labelled_as_new_vlm(editorial_course):
    root, out, tx, evidence, doc, manifest = editorial_course
    atomic_json(out/'visual_provenance.json', {'method':'Original deck and video alignment; no new VLM'})
    publish(manifest)
    assert read_json(out/'authoring_provenance.json')['visual_analysis']=='Original deck and video alignment; no new VLM'
    assert audit_publication(manifest)['metadata_valid']
    atomic_json(out/'visual_provenance.json', {'method':'Changed evidence'})
    with pytest.raises(ValueError, match='visual provenance'):
        audit_publication(manifest)
