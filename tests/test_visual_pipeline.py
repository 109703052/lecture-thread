from pathlib import Path
import pytest
from PIL import Image

from ocr_cache import OCRCache
from pipeline_common import atomic_json, read_json
from visual_pipeline import bind_inputs, boundary_times, crop_box, recognize_regions


def test_cache_reuses_pixels_across_filenames_and_processes(tmp_path):
    a, b = tmp_path/'a.png', tmp_path/'revisit.bmp'
    Image.new('RGB', (20, 20), 'white').save(a)
    Image.open(a).save(b)
    calls = []
    def recognize(path):
        calls.append(path)
        return 'word', .9, [[[0, 0], 'word', .9]], None
    cache = OCRCache(tmp_path/'cache', {'version': 1})
    first = cache.recognize(a, recognize)
    first[2].clear()
    again = OCRCache(tmp_path/'cache', {'version': 1}).recognize(b, recognize)
    assert again[2] and len(calls) == 1
    image = Image.open(b); image.putpixel((10, 10), (0, 0, 0)); image.save(b)
    cache.recognize(b, recognize)
    OCRCache(tmp_path/'cache', {'version': 2}).recognize(a, recognize)
    assert len(calls) == 3  # tiny changes and engine updates never share analysis


def test_failed_ocr_and_corrupt_cache_are_retried(tmp_path):
    image = tmp_path/'a.png'
    Image.new('RGB', (10, 10)).save(image)
    cache = OCRCache(tmp_path/'cache', {})
    cache.recognize(image, lambda p: ('', 0, [], 'temporary failure'))
    assert not list((tmp_path/'cache').glob('*.json'))
    cache.recognize(image, lambda p: ('ok', 1, [], None))
    next((tmp_path/'cache').glob('*.json')).write_text('{bad')
    assert cache.recognize(image, lambda p: ('retried', 1, [], None))[0] == 'retried'


def test_region_boxes_are_scaled_padded_and_clamped():
    assert crop_box([100, 50, 20, 10], [960, 540], [1920, 1080]) == (176, 76, 264, 144)
    assert crop_box([0, 0, 960, 540], [960, 540], [1920, 1080]) == (0, 0, 1920, 1080)


def test_boundaries_preserve_short_page_before_after_and_end():
    assert boundary_times([dict(before=4, after=5), dict(before=5, after=6)], 7) == [4, 5, 6]


def test_resume_rejects_different_source_without_overwriting(tmp_path):
    bind_inputs(tmp_path, {'video': 'a'})
    with pytest.raises(ValueError, match='changed'):
        bind_inputs(tmp_path, {'video': 'b'})
    assert read_json(tmp_path/'inputs.json') == {'video': 'a'}


def test_region_ocr_preserves_before_after_and_unknown_pages(tmp_path, monkeypatch):
    import visual_pipeline
    paths = []
    for i in range(2):
        path = tmp_path/f'{i}.png'
        Image.new('RGB', (192, 108), ('white', 'black')[i]).save(path)
        paths.append(path)
    monkeypatch.setattr(visual_pipeline, 'source_frame', lambda cap, time, out, **kw: paths[time])
    event = dict(page_id=None, before_time=0, after_time=1,
                 boxes_in_video_coordinates=[[100, 50, 20, 10]], canvas_size=[960, 540])
    result = recognize_regions([event], None, tmp_path, OCRCache(tmp_path/'cache', {}),
                               lambda path: ('', 0, [], None))
    assert result['complete'] and len(result['events']) == 1
    row = result['events'][0]
    assert row['page_id'] is None
    assert row['before']['source_sha256'] != row['after']['source_sha256']
    assert row['after']['regions'][0]['text'] == ''  # empty OCR does not drop the event


def test_visual_cli_uses_scoped_runner_and_absolute_paths(tmp_path, monkeypatch):
    import lecture_pipeline as pipeline
    calls = []
    monkeypatch.setattr(pipeline, 'PIPELINE_LOCK', tmp_path/'lock')
    monkeypatch.setattr(pipeline.subprocess, 'run', lambda argv, **kw: calls.append(argv))
    assert pipeline.main(['visual', '--job', str(tmp_path), '--references', str(tmp_path/'refs.json'),
                          '--out', str(tmp_path/'review'), '--ocr-regions']) == 0
    assert calls[0][1] == str(pipeline.ROOT/'run.py')
    assert '--ocr-regions' in calls[0]


def test_upstream_adapter_reuses_ocr_without_removing_occurrences(tmp_path, monkeypatch):
    import ocr_cache
    from profile_stage import load_stage
    script = Path(__file__).resolve().parents[1]/'vendor/lecture-to-notes/scripts/quick_ocr.py'
    if not script.exists():
        pytest.skip('optional upstream checkout unavailable')
    module = load_stage(script)
    slides = tmp_path/'slides'; slides.mkdir()
    Image.new('RGB', (20, 20), 'white').save(slides/'same.png')
    atomic_json(slides/'timestamps.json', [dict(slide=i+1, first_ts=i*5, timestamp=i*5+4,
        filename='same.png') for i in range(3)])
    # Test the actual upstream main loop with a counted CPU recognizer.
    calls = []
    module.rapidocr_text_ex = lambda p, engine: (calls.append(p) or ('test', 1., [], None))
    monkeypatch.setattr(ocr_cache, 'engine_signature', lambda: {'engine': 'test'})
    ocr_cache.install(module)
    monkeypatch.setattr(module, 'rapidocr_engine', lambda: object())
    monkeypatch.setattr('sys.argv', ['quick_ocr.py', str(tmp_path)])
    module.main()
    assert len(calls) == 1
    rows = read_json(tmp_path/'slides_raw.json')
    assert len(rows) == 3
    assert [r['timestamp_start'] for r in rows] == [0, 5, 10]
