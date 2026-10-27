from pathlib import Path
import shutil
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import urllib.request

import pytest

import author_lecture as author
import lecture_pipeline as pipeline
import pipeline_common
from pipeline_common import atomic_json, digest, exclusive_lock, read_json


@pytest.fixture
def tmp_path():
    parent = pipeline.ROOT / 'data/tmp'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pipeline-test-', dir=parent) as folder:
        yield Path(folder)


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, 'JOBS', tmp_path / 'jobs')
    monkeypatch.setattr(pipeline, 'PIPELINE_LOCK', tmp_path / 'pipeline.lock')
    source = tmp_path / '課堂 video.mp4'
    source.write_bytes(b'original source')
    return pipeline.create_job(str(source), 'test-job', retries=0)


def test_resume_skips_completed_stage_and_detects_edited_artifact(job):
    worker = pipeline.Worker(job)
    artifact = job / 'source.json'
    calls = []
    def stage():
        calls.append(1)
        atomic_json(artifact, dict(value=1))
        return [artifact]
    worker.stage('source', stage)
    pipeline.Worker(job).stage('source', stage)
    assert len(calls) == 1
    atomic_json(artifact, dict(value=2))
    with pytest.raises(ValueError, match='產物遭變動'):
        pipeline.Worker(job).stage('source', stage)
    assert read_json(artifact)['value'] == 2


def test_failed_stage_resumes_without_repeating_previous_work(job):
    worker = pipeline.Worker(job)
    first = job / 'first.json'
    atomic_json(first, [1])
    worker.stage('source', lambda: [first])
    def fail():
        raise RuntimeError('network disconnected')
    with pytest.raises(RuntimeError):
        worker.stage('transcribe', fail)
    assert read_json(job / 'status.json')['stages']['transcribe']['state'] == 'failed'
    next_worker = pipeline.Worker(job)
    next_worker.stage('source', fail)
    second = job / 'second.json'
    atomic_json(second, [2])
    next_worker.stage('transcribe', lambda: [second])
    status = read_json(job / 'status.json')
    assert status['stages']['source']['attempts'] == 1
    assert status['stages']['transcribe']['attempts'] == 2


def test_cleanup_on_failure_and_cannot_report_success_when_cleanup_fails(job, monkeypatch):
    worker = pipeline.Worker(job)
    stopped = []
    def fail():
        raise RuntimeError('preflight failed')
    monkeypatch.setattr(worker, 'preflight', fail)
    monkeypatch.setattr(worker, 'ollama', lambda stop=False: stopped.append(stop))
    with pytest.raises(RuntimeError, match='preflight failed'):
        worker.run()
    assert stopped == [True]
    assert read_json(job / 'status.json')['state'] == 'failed'
    monkeypatch.setattr(worker, 'preflight', lambda: None)
    monkeypatch.setattr(worker, 'stage', lambda *args: None)
    monkeypatch.setattr(worker, 'ollama', lambda **kw: (_ for _ in ()).throw(RuntimeError('stop failed')))
    with pytest.raises(RuntimeError, match='stop failed'):
        worker.run()
    assert read_json(job / 'status.json')['ollama_cleanup'] == 'failed'


def test_exclusive_process_lock_releases_after_exception(tmp_path):
    path = tmp_path / 'process.lock'
    with exclusive_lock(path):
        with pytest.raises(RuntimeError, match='另一個'):
            with exclusive_lock(path):
                pass
    with exclusive_lock(path):
        pass


@pytest.mark.parametrize('bad', ['../overwrite', 'a/b', '.', 'x'*81])
def test_job_ids_cannot_escape_output(bad):
    with pytest.raises(ValueError):
        pipeline.job_path(bad)


def make_author_inputs(job):
    course = job / 'course'
    course.mkdir(exist_ok=True)
    tx = [dict(start=0, end=3, text='Stack 使用後進先出。'),
          dict(start=3, end=6, text='Queue 使用先進先出。')]
    atomic_json(course / 'transcript.json', tx)
    atomic_json(course / 'slide_evidence.json', [dict(occurrence_id=i+1, start=i*3,
                end=(i+1)*3, image=f'{i}.png', title='課程', primary_transcript_ids=[i],
                ocr=dict(quick_text='Stack Queue'), vlm_signals=None) for i in range(2)])
    return course


def result(ids):
    return dict(title='資料結構', problem='資料結構依序取出元素。',
                lesson=[dict(source_ids=ids, heading='取出順序', text='依據插入順序決定先取出哪個元素。')],
                corrections=[], flags=[])


def test_author_resume_preserves_original_and_only_retries_unfinished_batch(job, monkeypatch):
    course = make_author_inputs(job)
    raw = (course / 'transcript.json').read_bytes()
    calls = []
    def generate(payload, model, timeout):
        ids = payload['primary_ids']
        calls.append(ids)
        if ids == [1]:
            raise OSError('interrupted')
        return result(ids)
    monkeypatch.setattr(author, 'generate', generate)
    with pytest.raises(RuntimeError, match='interrupted'):
        author.author(course, retries=0)
    assert not (course / 'authored_notes.json').exists()
    monkeypatch.setattr(author, 'generate', lambda payload, *args: (calls.append(payload['primary_ids']) or result(payload['primary_ids'])))
    author.author(course, retries=0)
    assert calls == [[0], [1], [1]]
    assert (course / 'transcript.json').read_bytes() == raw
    assert len(read_json(course / 'authored_notes.json')) == 2
    # A changed prompt/model cannot silently reuse earlier notes.
    with pytest.raises(ValueError, match='inputs changed'):
        author.author(course, model='different')


def test_author_rejects_unsupported_sources_and_missing_coverage():
    for sources in ([1], [0, 0], [], [False]):
        with pytest.raises(ValueError):
            author.validate_response(result(sources), [0])
    value = result([0])
    value['corrections'] = [dict(segment_id=1, text='invented', reason='unknown')]
    with pytest.raises(ValueError):
        author.validate_response(value, [0])


def test_author_preserves_completed_outputs_on_conflict(job, monkeypatch):
    course = make_author_inputs(job)
    monkeypatch.setattr(author, 'generate', lambda payload, *args: result(payload['primary_ids']))
    atomic_json(course / 'transcript.corrected.json', ['human work'])
    with pytest.raises(ValueError, match='Preserving'):
        author.author(course)
    assert read_json(course / 'transcript.corrected.json') == ['human work']
    assert not (course / 'authored_notes.json').exists()


def test_editorial_course_cannot_fall_back_to_local_author_or_preflight(job, monkeypatch):
    worker = pipeline.Worker(job)
    atomic_json(worker.course / 'editorial_chapters.json', {'schema': 1, 'author': 'Codex'})
    calls = []
    monkeypatch.setattr(worker, 'ollama', lambda *args, **kwargs: calls.append('ollama'))
    monkeypatch.setattr(worker, 'command', lambda *args, **kwargs: calls.append('command'))
    for operation in [worker.preflight, worker.author]:
        with pytest.raises(ValueError, match='editorial_publish.py'):
            operation()
    assert calls == []


def test_delivery_checks_coverage_and_raw_hash(job, monkeypatch):
    course = make_author_inputs(job)
    slides = course / 'slides'
    slides.mkdir()
    for i in range(2):
        (slides / f'{i}.png').write_bytes(b'image')
    atomic_json(job / 'media.json', dict(duration=6))
    worker = pipeline.Worker(job)
    worker.stage('transcribe', lambda: [course / 'transcript.json'])
    monkeypatch.setattr(author, 'generate', lambda payload, *args: result(payload['primary_ids']))
    author.author(course)
    report, flags = pipeline.validate_deliverable(job)
    assert report['raw_transcript_unchanged'] and report['assigned_segments'] == 2
    original = read_json(course / 'transcript.json')
    original[0]['text'] = 'modified'
    atomic_json(course / 'transcript.json', original)
    with pytest.raises(ValueError, match='Original transcript modified'):
        pipeline.validate_deliverable(job)


def test_source_identity_and_duplicate_job_protection(job, monkeypatch):
    config = read_json(job / 'job.json')
    source = Path(config['source'])
    with pytest.raises(FileExistsError):
        pipeline.create_job(str(source), 'test-job')
    assert source.read_bytes() == b'original source'


def test_no_arbitrary_remote_downloads():
    with pytest.raises(ValueError, match='YouTube'):
        pipeline.youtube_id('https://example.com/lecture.mp4')
    assert pipeline.youtube_id('https://youtu.be/abcdefghijk') == 'abcdefghijk'


def test_revisit_and_annotations_are_not_semantically_deduplicated(job):
    worker = pipeline.Worker(job)
    rows = [dict(filename=f'{i}.png', slide_id=i+1) for i in range(4)]
    atomic_json(worker.course / 'slides_raw.json', rows)
    (worker.course / 'slides').mkdir()
    atomic_json(worker.course / 'slides/timestamps.json',
                [dict(pixel_sha256=h) for h in ['stack', 'queue', 'stack', 'stack+annotation']])
    worker.dedup()
    enriched = read_json(worker.course / 'slides_dedup.json')
    assert len(enriched) == 4
    assert [r['dedup']['is_canonical'] for r in enriched] == [True, True, False, True]


def test_context_chunking_has_no_dropped_transcript_ids():
    tx = [dict(start=i*10, end=i*10+10, text='x'*800) for i in range(8)]
    chunks = author.batches(list(range(8)), tx)
    assert [i for chunk in chunks for i in chunk] == list(range(8))
    assert all(sum(len(tx[i]['text']) for i in chunk) <= 2000 for chunk in chunks)


@pytest.mark.parametrize('replacement', ['9 個 Stack 元素。', '完全不同的一句話，取代所有原本內容。'])
def test_author_rejects_number_changes_and_sentence_replacement(job, monkeypatch, replacement):
    course = make_author_inputs(job)
    tx = read_json(course / 'transcript.json')
    tx[0]['text'] = '8 個 Stack 元素。'
    atomic_json(course / 'transcript.json', tx)
    raw_hash = digest(course / 'transcript.json')
    def generate(payload, *args):
        value = result(payload['primary_ids'])
        if payload['primary_ids'] == [0]:
            value['corrections'] = [dict(segment_id=0, text=replacement, reason='model suggestion')]
        return value
    monkeypatch.setattr(author, 'generate', generate)
    author.author(course, retries=0)
    assert digest(course / 'transcript.json') == raw_hash
    assert read_json(course / 'transcript.corrected.json')[0]['text'] == '8 個 Stack 元素。'
    assert read_json(course / 'transcript.corrections.json') == []
    assert any('未採用 AI 校字' in flag['message'] for flag in read_json(course / 'author_flags.json'))
    lesson = read_json(course / 'authored_notes.json')[0]['lesson'][0]
    assert '8 個 Stack 元素。' in lesson['text']
    assert replacement not in lesson['text']


def test_preflight_rejects_changed_job_before_starting_models(job):
    config = read_json(job / 'job.json')
    config['interval'] = 10
    atomic_json(job / 'job.json', config)
    with pytest.raises(ValueError, match='任務設定已變動'):
        pipeline.Worker(job).preflight()


def test_extraction_keeps_revisits_and_small_annotations(tmp_path):
    Image = pytest.importorskip('PIL.Image')
    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg is an optional full-pipeline dependency')
    from extract_occurrences import extract
    input_dir = tmp_path / 'input'
    input_dir.mkdir()
    a = Image.new('RGB', (160, 100), 'white')
    b = Image.new('RGB', (160, 100), 'blue')
    annotated = a.copy()
    # A tiny annotation must remain a distinct occurrence.
    annotated.putpixel((150, 90), (0, 0, 0))
    for index, image in enumerate([a, a, b, a, a, annotated], 1):
        image.save(input_dir / f'frame_{index:02}.png')
    video = tmp_path / 'fixture.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', '1', '-i',
                    str(input_dir / 'frame_%02d.png'), '-c:v', 'ffv1', str(video)], check=True)
    rows = extract(video, tmp_path / 'course', interval=1)
    assert [row['first_ts'] for row in rows] == [0, 2, 3, 5]
    assert rows[0]['filename'] == rows[2]['filename']
    assert rows[0]['filename'] != rows[3]['filename']
    assert len(list((tmp_path / 'course/_samples').glob('*.png'))) == 6


def test_background_lock_failure_is_recorded_instead_of_staying_queued(job):
    with exclusive_lock(pipeline.PIPELINE_LOCK):
        assert pipeline.main(['_worker', job.name]) == 1
    status = read_json(job / 'status.json')
    assert status['state'] == 'failed' and '另一個' in status['error']


def test_atomic_status_retries_windows_sharing_violation(tmp_path, monkeypatch):
    target = tmp_path / 'status.json'
    atomic_json(target, dict(state='previous'))
    original = pipeline_common.os.replace
    calls = []
    def replace(source, destination):
        calls.append(1)
        if len(calls) < 3:
            assert read_json(target)['state'] == 'previous'
            raise PermissionError('Windows reader still holds a handle')
        original(source, destination)
    monkeypatch.setattr(pipeline_common.os, 'replace', replace)
    monkeypatch.setattr(pipeline_common.time, 'sleep', lambda *_: None)
    atomic_json(target, dict(state='next'))
    assert len(calls) == 3 and read_json(target)['state'] == 'next'


def test_failed_atomic_replace_keeps_previous_snapshot(tmp_path, monkeypatch):
    target = tmp_path / 'status.json'
    atomic_json(target, dict(state='previous'))
    monkeypatch.setattr(pipeline_common.os, 'replace', lambda *_: (_ for _ in ()).throw(PermissionError('locked')))
    monkeypatch.setattr(pipeline_common.time, 'sleep', lambda *_: None)
    with pytest.raises(PermissionError):
        atomic_json(target, dict(state='next'))
    assert read_json(target)['state'] == 'previous'
    assert list(tmp_path.glob('*.tmp')) == []


def test_immutable_publish_never_replaces_existing_original(tmp_path):
    path = tmp_path / 'transcript.json'
    pipeline_common.publish_immutable(path, b'original')
    pipeline_common.publish_immutable(path, b'original')
    with pytest.raises(ValueError, match='immutable original'):
        pipeline_common.publish_immutable(path, b'changed')
    assert path.read_bytes() == b'original'


def test_asr_receipt_recovers_crash_between_publish_and_status(job, monkeypatch):
    worker = pipeline.Worker(job)
    worker.media.parent.mkdir()
    worker.media.write_bytes(b'media')
    atomic_json(job / 'media.json', dict(duration=6))
    temporary = job / '_transcribe'
    temporary.mkdir()
    atomic_json(temporary / 'transcript.json', [dict(start=0, end=6, text='Stack 課程。')])
    atomic_json(temporary / 'published-original.json', dict(media_sha256=digest(worker.media),
                transcript_sha256=digest(temporary / 'transcript.json')))
    monkeypatch.setattr(worker, 'command', lambda *args, **kwargs: pytest.fail('ASR must not rerun'))
    worker.transcribe()
    assert (worker.course / 'transcript.json').read_bytes() == (temporary / 'transcript.json').read_bytes()
    worker.transcribe()


@pytest.mark.parametrize('reused_pid', [False, True])
def test_orphan_recovery_never_kills_reused_pid(job, monkeypatch, reused_pid):
    worker = pipeline.Worker(job)
    worker.status.update(child_pid=12345, child_created_at=10)
    killed = []
    child = SimpleNamespace(kill=lambda: killed.append('child'))
    process = SimpleNamespace(create_time=lambda: 20 if reused_pid else 10,
                cmdline=lambda: [str(pipeline.PYTHON), str(pipeline.ROOT / 'run.py')],
                children=lambda **kw: [child], kill=lambda: killed.append('parent'), wait=lambda **kw: None)
    monkeypatch.setitem(sys.modules, 'psutil', SimpleNamespace(Process=lambda pid: process,
                                                            NoSuchProcess=ProcessLookupError))
    worker.recover_child()
    assert killed == ([] if reused_pid else ['child', 'parent'])
    assert 'child_pid' not in worker.status


@pytest.mark.parametrize('action', ['start', 'stop'])
def test_ollama_refuses_unknown_listener_and_never_claims_shutdown(tmp_path, monkeypatch, action):
    service = tmp_path / 'ollama_service.py'
    service.write_bytes((pipeline.ROOT / 'ollama_service.py').read_bytes())
    monkeypatch.setattr(sys, 'argv', [str(service)] + (['stop'] if action == 'stop' else []))
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *args, **kw: SimpleNamespace(close=lambda: None))
    expected = 'shutdown is not confirmed' if action == 'stop' else 'unknown server'
    with pytest.raises(RuntimeError, match=expected):
        runpy.run_path(str(service), run_name='__main__')


def test_ollama_reused_pid_is_not_terminated(tmp_path, monkeypatch):
    service = tmp_path / 'ollama_service.py'
    service.write_bytes((pipeline.ROOT / 'ollama_service.py').read_bytes())
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/ollama.pid').write_text('12345')
    atomic_json(tmp_path / 'data/ollama-process.json', dict(pid=12345, created_at=10))
    process = SimpleNamespace(exe=lambda: str(tmp_path / 'tools/ollama/ollama.exe'), create_time=lambda: 20,
                              terminate=lambda: pytest.fail('must not terminate a reused PID'))
    monkeypatch.setitem(sys.modules, 'psutil', SimpleNamespace(Process=lambda pid: process,
                                                            NoSuchProcess=ProcessLookupError))
    monkeypatch.setattr(sys, 'argv', [str(service), 'stop'])
    with pytest.raises(RuntimeError, match='PID was reused'):
        runpy.run_path(str(service), run_name='__main__')


def test_author_normalizes_uncorrected_asr_to_traditional(job, monkeypatch):
    course = make_author_inputs(job)
    tx = read_json(course / 'transcript.json')
    tx[0]['text'] = '这个设备传输 8 bit 数据。'
    atomic_json(course / 'transcript.json', tx)
    raw_hash = digest(course / 'transcript.json')
    monkeypatch.setattr(author, 'generate', lambda payload, *args: result(payload['primary_ids']))
    author.author(course, retries=0)
    assert digest(course / 'transcript.json') == raw_hash
    corrected = read_json(course / 'transcript.corrected.json')
    assert corrected[0]['text'] == '這個設備傳輸 8 bit 數據。'
    assert (corrected[0]['start'], corrected[0]['end']) == (tx[0]['start'], tx[0]['end'])
    assert read_json(course / 'transcript.corrections.json')[0]['status'] == 'script-normalized'
