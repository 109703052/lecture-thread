"""Reuse must never change evidence: shared decode, deck feature index and crop artifacts."""
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from ocr_cache import OCRCache, pixel_identity
from pipeline_common import atomic_json, digest, read_json

needs_ffmpeg = pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg unavailable')


def make_deck(path, twin=False):
    import pymupdf
    doc = pymupdf.open()
    for p in range(3):
        page = doc.new_page(width=960, height=540)
        page.insert_text((40, 50), f'Topic {p+1}: storage layer {p*7}', fontsize=30)
        for i in range(9):
            page.insert_text((40, 100+i*38), f'{i+1}. item {p}-{i} wear leveling block {p*31+i}', fontsize=17)
        for i in range(4):
            x = 640+(p*53+i*29) % 180
            page.draw_rect(pymupdf.Rect(x, 90+i*80, x+90, 140+i*80), color=(0, 0, 0), fill=(.2*p, .5, .7))
    if twin:  # exact duplicate of page 2: matching must stay ambiguous
        copy = pymupdf.open()
        copy.insert_pdf(doc, from_page=1, to_page=1)
        doc.insert_pdf(copy)
        copy.close()
    doc.save(path)
    doc.close()
    return dict(deck_id='t', source=str(path), source_sha256=digest(path), render_pdf=str(path),
                render_sha256=digest(path), slide_count=4 if twin else 3)


def page_images(pdf, width):
    import pymupdf
    with pymupdf.open(pdf) as doc:
        out = []
        for page in doc:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(width/960, width/960))
            out.append(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, 2::-1].copy())
        return out


def make_job(tmp_path):
    """23.4 s at 5 fps: 1.2 s transient page, revisit, a tiny mark drawn then erased,
    and a mark after the final 5 s sample."""
    import cv2
    ref = make_deck(tmp_path/'deck.pdf')
    pages = page_images(tmp_path/'deck.pdf', 640)
    job = tmp_path/'job'
    (job/'media').mkdir(parents=True)
    video = job/'media/lecture.mp4'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 5, (640, 360))
    for tick in range(117):
        sec = tick/5
        n = 1 if 6 <= sec < 7.2 else 2 if 12 <= sec < 21 else 0
        frame = pages[n].copy()
        if 13 <= sec < 16:
            cv2.line(frame, (100, 330), (140, 330), (0, 0, 0), 2)
        if sec >= 22.4:  # after the last boundary frame (22 s)
            cv2.putText(frame, 'Q', (600, 350), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1)
        writer.write(frame)
    writer.release()
    atomic_json(job/'media.json', dict(sha256=digest(video), duration=23.4))
    atomic_json(tmp_path/'refs.json', [ref])
    return job, tmp_path/'refs.json'


@needs_ffmpeg
def test_one_decode_yields_identical_base_samples_and_probes(tmp_path):
    from scan_slide_changes import scan
    job, _ = make_job(tmp_path)
    video = job/'media/lecture.mp4'
    old = tmp_path/'old'; old.mkdir()
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-vf', 'fps=1/5:round=up,scale=960:-2',
                    '-q:v', '2', str(old/'frame-%06d.jpg')], check=True)
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-vf', 'fps=1:round=up,scale=320:224',
                          '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1'], capture_output=True, check=True).stdout
    probes = np.frombuffer(raw, np.uint8).reshape(-1, 224, 320)
    shared = tmp_path/'shared/frames'; shared.mkdir(parents=True)
    (shared/'frame-999999.jpg').write_bytes(b'interrupted decode')
    result = scan(video, tmp_path/'scan.json', shared, 5)
    assert [digest(p) for p in sorted(old.glob('*.jpg'))] == [digest(p) for p in sorted(shared.glob('*.jpg'))]
    assert result['probes'] == len(probes) == 24  # tail second 23 is probed
    pairs = [(e['before'], e['after']) for e in result['events']]
    assert (5, 6) in pairs and (7, 8) in pairs  # sub-5 s page: arrival and return
    assert read_json(tmp_path/'shared/extraction.json')['frames'] == 5
    assert scan(video, tmp_path/'scan.json', shared, 5) == result  # resume needs no decode


@needs_ffmpeg
def test_pipeline_shares_index_and_reuses_everything_on_resume(tmp_path):
    import deck_alignment
    from visual_pipeline import run
    job, refs = make_job(tmp_path)
    cache = tmp_path/'features'
    builds = []
    original = deck_alignment.Matcher.__init__
    def counted(self, *a, **kw):
        builds.append(1); original(self, *a, **kw)
    deck_alignment.Matcher.__init__ = counted
    try:
        first = run(job, refs, tmp_path/'review', feature_cache=cache)
        again = run(job, refs, tmp_path/'review', feature_cache=cache)
        other = run(job, refs, tmp_path/'review2', feature_cache=cache)
    finally:
        deck_alignment.Matcher.__init__ = original
    assert first['work']['full_video_decodes'] == 1 and first['work']['pages_computed'] == 3
    assert again['work']['full_video_decodes'] == 0 and again['work']['matcher_builds'] == 0
    assert other['work']['pages_loaded'] == 3 and other['work']['pages_computed'] == 0
    assert len(builds) == 2  # one per run that had uncached frames, never two per run
    a = read_json(tmp_path/'review/alignment.json')
    b = read_json(tmp_path/'review2/alignment.json')
    strip = lambda rows: [(r['time'], r['image_sha256'], r['status'], r['page_id'], r['candidates']) for r in rows]
    assert strip(a['observations']) == strip(b['observations'])
    runs = [(r['page_id'], r['start']) for r in a['intervals']]
    assert ('t:2', 6) in runs  # transient page recovered from the 1 s probes
    assert [p for p, _ in runs].count('t:1') >= 2  # revisit kept as its own interval
    assert 23 in [r['time'] for r in a['observations']]  # tail probe after last 5 s sample
    events = read_json(tmp_path/'review/differences.json')['events']
    assert any(e['before_time'] < 13 <= e['after_time'] for e in events)  # mark drawn
    assert any(e['before_time'] < 16 <= e['after_time'] for e in events)  # mark erased
    assert any(e['after_time'] == 23 for e in events)  # tail mark


def test_feature_cache_is_exact_and_rebuilds_when_damaged_or_foreign(tmp_path):
    from deck_alignment import Matcher, decide, feature_signature, load_features
    ref = make_deck(tmp_path/'deck.pdf', twin=True)
    frame = tmp_path/'frame.png'
    Image.fromarray(page_images(tmp_path/'deck.pdf', 1280)[1][:, :, ::-1]).save(frame)
    fresh = Matcher([ref]).analyze(frame)
    built = Matcher([ref], tmp_path/'cache')
    loaded = Matcher([ref], tmp_path/'cache')
    assert built.pages_computed == 4 and loaded.pages_loaded == 4
    assert loaded.analyze(frame) == built.analyze(frame) == fresh
    assert decide(fresh) == ('ambiguous', None)  # duplicate pages are never forced
    target = next((tmp_path/'cache').glob('*.npz'))
    target.write_bytes(target.read_bytes()[:200])
    damaged = Matcher([ref], tmp_path/'cache')
    assert damaged.pages_computed == 4 and damaged.analyze(frame) == fresh
    other = dict(ref, render_sha256='0'*64)
    assert load_features(tmp_path/'cache', feature_signature(other))[1] is None
    # A file renamed to another deck's key still fails the stored signature check.
    shutil.copy(target, tmp_path/'cache'/(load_features(tmp_path/'cache', feature_signature(other))[0]+'.npz'))
    assert load_features(tmp_path/'cache', feature_signature(other))[1] is None


def test_fully_cached_alignment_never_builds_the_index(tmp_path):
    from deck_alignment import SharedMatcher, run
    ref = make_deck(tmp_path/'deck.pdf')
    atomic_json(tmp_path/'refs.json', [ref])
    course = tmp_path/'course'
    (course/'frames/frames').mkdir(parents=True)
    atomic_json(course/'media.json', dict(sha256='v', duration=10))
    rows = []
    for i in range(2):
        path = course/f'frames/frames/frame-{i+1:06d}.jpg'
        Image.new('RGB', (96, 54), (i*200, 0, 0)).save(path)
        rows.append(dict(image_sha256=digest(path), candidates=[]))
    from frame_cache import frame_manifest
    atomic_json(course/'frames/extraction.json', dict(media_sha256='v', interval=5, width=960,
                                                    **frame_manifest(course/'frames/frames')))
    (tmp_path/'out').mkdir()
    (tmp_path/'out/analysis.jsonl').write_text(''.join(__import__('json').dumps(r)+'\n' for r in rows))
    shared = SharedMatcher([ref])
    result = run(course, tmp_path/'refs.json', tmp_path/'out', frame_cache=course/'frames', matcher=shared)
    assert shared.builds == 0 and [o['status'] for o in result['observations']] == ['unmatched']*2


def region_fixture(tmp_path, monkeypatch):
    import visual_pipeline
    paths = []
    for i in range(3):
        image = Image.new('RGB', (1920, 1080), 'white')
        if i == 1:
            image.putpixel((210, 110), (0, 0, 0))  # one-pixel mark, then erased
        path = tmp_path/f'{i}.png'
        image.save(path)
        paths.append(path)
    monkeypatch.setattr(visual_pipeline, 'source_frame', lambda cap, time, out, **kw: paths[time])
    box = dict(boxes_in_video_coordinates=[[100, 50, 20, 10]], canvas_size=[960, 540])
    return [dict(page_id='t:1', before_time=0, after_time=1, **box),
            dict(page_id=None, before_time=1, after_time=2, **box)]


def test_crops_are_reused_until_source_region_or_version_changes(tmp_path, monkeypatch):
    import visual_pipeline
    from visual_pipeline import RunFacts, recognize_regions
    events = region_fixture(tmp_path, monkeypatch)
    calls = []
    def recognize(path):
        calls.append(path)
        return '', 0., [], None  # empty OCR keeps the event
    stats = {}
    first = recognize_regions(events, None, tmp_path, OCRCache(tmp_path/'cache', {}), recognize, RunFacts(), stats)
    assert stats['crops_written'] == 2 and stats['crops_reused'] == 2  # white crops share one file
    assert len(calls) == 2  # unmarked and marked pixels; the erased side reuses unmarked OCR
    rows = first['events']
    assert rows[0]['after']['regions'][0]['image_sha256'] != rows[0]['before']['regions'][0]['image_sha256']
    assert rows[1]['page_id'] is None and rows[1]['before']['time'] == 1 and rows[1]['after']['time'] == 2
    for row in rows:
        crop = Path(row['after']['regions'][0]['image'])
        with Image.open(crop) as image:  # identity handed to OCR equals decoded pixels
            assert pixel_identity(image) == read_json(crop.with_suffix('.json'))['pixel_sha256']
    stats = {}
    again = recognize_regions(events, None, tmp_path, OCRCache(tmp_path/'cache', {}), recognize, RunFacts(), stats)
    assert stats.get('crops_written', 0) == 0 and len(calls) == 2
    assert again['events'] == rows
    crop = Path(rows[0]['after']['regions'][0]['image'])
    crop.with_suffix('.json').write_text('{bad')
    Image.new('RGB', (4, 4)).save(Path(rows[0]['before']['regions'][0]['image']))  # tampered file
    stats = {}
    recognize_regions(events, None, tmp_path, OCRCache(tmp_path/'cache', {}), recognize, RunFacts(), stats)
    assert stats['crops_written'] == 2
    monkeypatch.setattr(visual_pipeline, 'CROP_VERSION', 2)
    stats = {}
    recognize_regions(events, None, tmp_path, OCRCache(tmp_path/'cache', {}), recognize, RunFacts(), stats)
    assert stats['crops_written'] == 2 and len(calls) == 2  # new artifacts, same pixels, OCR reused


def test_interrupted_region_ocr_resumes_without_repeating_finished_work(tmp_path, monkeypatch):
    from visual_pipeline import RunFacts, recognize_regions
    events = region_fixture(tmp_path, monkeypatch)
    calls = []
    def flaky(path):
        calls.append(path)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return 'x', 1., [], None
    with pytest.raises(KeyboardInterrupt):
        recognize_regions(events, None, tmp_path, OCRCache(tmp_path/'cache', {}), flaky, RunFacts(), {})
    assert not (tmp_path/'region-ocr.json').exists() or read_json(tmp_path/'region-ocr.json')['complete'] is False
    stats = {}
    result = recognize_regions(events, None, tmp_path, OCRCache(tmp_path/'cache', {}), flaky, RunFacts(), stats)
    assert result['complete'] and len(result['events']) == 2 and len(calls) == 3
    assert result['cache_hits'] == 3 and result['cache_misses'] == 1


def test_source_images_stay_bounded_in_memory(tmp_path):
    from visual_pipeline import RunFacts
    facts = RunFacts(max_images=2)
    for i in range(5):
        path = tmp_path/f'{i}.png'
        Image.new('RGB', (8, 8), (i, 0, 0)).save(path)
        facts.image(path)
    assert len(facts.images) == 2 and facts.image_decodes == 5
    facts.image(tmp_path/'4.png')
    assert facts.image_decodes == 5
