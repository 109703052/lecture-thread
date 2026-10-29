import pytest
from PIL import Image

from frame_cache import frame_manifest, validate_frame_cache
from pipeline_common import atomic_json, digest
from scan_slide_changes import COMPARE_RULE, COMPARE_WIDTH, scan
from visual_pipeline import RunFacts, crop_artifact
from ocr_cache import OCRCache


def extracted(tmp_path):
    frames = tmp_path/'frames'
    frames.mkdir()
    for i in range(1, 4):
        Image.new('RGB', (20, 20), (i*50, 0, 0)).save(frames/f'frame-{i:06d}.jpg')
    return frames, dict(media_sha256='video', interval=5, width=960, quality=2,
                        **frame_manifest(frames))


@pytest.mark.parametrize('damage', ['missing', 'renamed', 'modified', 'extra', 'legacy'])
def test_scan_resume_rejects_invalid_frames_before_reuse(tmp_path, damage):
    frames, receipt = extracted(tmp_path)
    atomic_json(tmp_path/'extraction.json', receipt)
    signature = dict(video_sha256='video', width=320, height=224, fps=1, threshold=25, area=.025,
                     base_frames=dict(folder=str(frames.resolve()), interval=5, width=960, quality=2),
                     comparison_frames=dict(folder=str((tmp_path/'compare').resolve()), width=COMPARE_WIDTH,
                                            format='png', rule=COMPARE_RULE))
    atomic_json(tmp_path/'scan.json', dict(inputs=signature, probes=15, events=[]))
    if damage == 'missing':
        (frames/'frame-000002.jpg').unlink()
    elif damage == 'renamed':
        (frames/'frame-000002.jpg').rename(frames/'frame-000004.jpg')
    elif damage == 'modified':
        Image.new('RGB', (20, 20), 'black').save(frames/'frame-000002.jpg')
    elif damage == 'extra':
        Image.new('RGB', (20, 20)).save(frames/'frame-000004.jpg')
    else:
        receipt.pop('frame_sha256')
        atomic_json(tmp_path/'extraction.json', receipt)
    with pytest.raises(ValueError, match='Frame cache'):
        scan(tmp_path/'unused-video', tmp_path/'scan.json', frames, video_sha256='video')


def test_manifest_checks_count_and_keeps_original_slots(tmp_path):
    frames, receipt = extracted(tmp_path)
    assert [p.name for p in validate_frame_cache(frames, receipt, 3)] == [
        'frame-000001.jpg', 'frame-000002.jpg', 'frame-000003.jpg']
    with pytest.raises(ValueError, match='count'):
        validate_frame_cache(frames, receipt, 4)


def test_direct_alignment_rejects_missing_frame_before_writing_timestamps(tmp_path):
    from deck_alignment import run
    frames, receipt = extracted(tmp_path)
    atomic_json(tmp_path/'extraction.json', receipt)
    atomic_json(tmp_path/'media.json', dict(sha256='video', duration=15))
    atomic_json(tmp_path/'refs.json', [])
    (frames/'frame-000002.jpg').unlink()
    with pytest.raises(ValueError, match='sequence'):
        run(tmp_path, tmp_path/'refs.json', tmp_path/'out', frame_cache=tmp_path)
    assert not (tmp_path/'out/alignment.json').exists()


@pytest.mark.parametrize('damage', ['wrong_pixel_id', 'missing_pixel_id', 'legacy_receipt'])
def test_corrupt_crop_receipt_never_reuses_other_image_ocr(tmp_path, damage):
    cache = OCRCache(tmp_path/'ocr', {'engine': 'test'})
    artifacts = []
    for color in ['white', 'black']:
        source = tmp_path/f'{color}.png'
        Image.new('RGB', (30, 30), color).save(source)
        crop, saved = crop_artifact(source, digest(source), (0, 0, 30, 30), [0, 0, 30, 30],
                                    [30, 30], tmp_path/'crops', RunFacts(), {})
        cache.recognize(crop, lambda p, text=color: (text, 1, [], None), identity=saved['pixel_sha256'])
        artifacts.append((source, crop, saved))
    source, crop, saved = artifacts[0]
    correct_id = saved['pixel_sha256']
    if damage == 'wrong_pixel_id':
        saved['pixel_sha256'] = artifacts[1][2]['pixel_sha256']
    elif damage == 'missing_pixel_id':
        saved.pop('pixel_sha256')
    else:
        saved.pop('receipt_sha256')
    atomic_json(crop.with_suffix('.json'), saved)
    stats = {}
    crop, repaired = crop_artifact(source, digest(source), (0, 0, 30, 30), [0, 0, 30, 30],
                                   [30, 30], tmp_path/'crops', RunFacts(), stats)
    assert stats['crops_written'] == 1 and repaired['pixel_sha256'] == correct_id
    result = cache.recognize(crop, lambda p: pytest.fail('valid white OCR should still be reusable'),
                             identity=repaired['pixel_sha256'])
    assert result[0] == 'white'
    stats = {}
    crop_artifact(source, digest(source), (0, 0, 30, 30), [0, 0, 30, 30],
                  [30, 30], tmp_path/'crops', RunFacts(), stats)
    assert stats['crops_reused'] == 1 and 'crops_written' not in stats
