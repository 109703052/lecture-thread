"""Difference review must compare frames made the same way, without hiding real small changes."""
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from pipeline_common import atomic_json, digest, read_json

needs_ffmpeg = pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg unavailable')
W, H = 1280, 720


def slide():
    """Dense thin text and fine lines: the content where scalers and JPEG disagree most."""
    import cv2
    frame = np.full((H, W, 3), 255, np.uint8)
    cv2.rectangle(frame, (0, 0), (W, 90), (200, 200, 200), -1)
    cv2.putText(frame, 'Device Interaction Methods', (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (40, 40, 40), 3)
    for i in range(14):
        cv2.putText(frame, f'{i+1}. memory-mapped I/O address space x{i*37:04d} -> buffer[{i}]',
                    (30, 130+i*40), cv2.FONT_HERSHEY_SIMPLEX, .62, (20, 20, 20), 1, cv2.LINE_AA)
    for x in range(820, 1240, 6):
        cv2.line(frame, (x, 140), (x+30, 600), (90, 60, 160), 1, cv2.LINE_AA)
    return frame


def make_video(path, seconds, draw=lambda frame, sec: None, fps=10):
    """H.264 4:2:0 like the real lectures, so the codec adds its own noise."""
    path.parent.mkdir(parents=True, exist_ok=True)
    base = slide()
    with subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
                           '-s', f'{W}x{H}', '-r', str(fps), '-i', 'pipe:0', '-c:v', 'libx264',
                           '-preset', 'veryfast', '-crf', '30', '-g', '50', '-pix_fmt', 'yuv420p', str(path)],
                          stdin=subprocess.PIPE) as p:
        for tick in range(int(seconds*fps)):
            frame = base.copy()
            draw(frame, tick/fps)
            p.stdin.write(frame.tobytes())
        p.stdin.close()
        assert p.wait() == 0


def deck(tmp_path):
    import pymupdf
    import cv2
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    png = tmp_path/'slide.png'
    cv2.imwrite(str(png), slide())
    page.insert_image(page.rect, filename=str(png))
    path = tmp_path/'deck.pdf'
    doc.save(path)
    doc.close()
    return [dict(deck_id='t', source=str(path), source_sha256=digest(path), render_pdf=str(path),
                 render_sha256=digest(path), slide_count=1)]


@needs_ffmpeg
def test_mixed_jpeg_and_seek_frames_are_the_false_difference_source(tmp_path):
    """Reproduces the observed noise: a static slide, 5 s JPEG vs full-resolution seek frame."""
    import cv2
    from deck_differences import regions, video_plane
    from scan_slide_changes import comparison_name, scan
    from visual_pipeline import source_frame
    video = tmp_path/'static.mp4'
    make_video(video, 12)
    decoded = tmp_path/'shared'
    result = scan(video, tmp_path/'scan.json', decoded/'frames', 5)
    assert result['events'] == []
    capture = cv2.VideoCapture(str(video))
    seek = source_frame(capture, 6, tmp_path/'seek')
    capture.release()
    jpeg = decoded/'frames/frame-000002.jpg'  # 5 s sample
    mixed, boxes = regions(video_plane(str(jpeg))[0], video_plane(str(seek))[0])
    assert mixed > 0 and boxes  # identical content, different encoding/scaling path
    same, _ = regions(video_plane(str(decoded/'compare'/comparison_name(5)))[0],
                      video_plane(str(decoded/'compare'/comparison_name(10)))[0])
    assert same == 0
    # The kept comparison slots are exactly what observations need; the rest were deleted.
    kept = sorted(p.name for p in (decoded/'compare').glob('*.png'))
    assert kept == [comparison_name(s) for s in (0, 5, 10, 11)]  # base samples + final probe


@needs_ffmpeg
def test_comparison_frames_are_the_probe_frames_with_one_scaler(tmp_path):
    from scan_slide_changes import comparison_name, scan
    from PIL import Image
    video = tmp_path/'v.mp4'
    make_video(video, 7.3, lambda f, s: f.__setitem__((slice(300, 420), slice(100, 1100)), 0) if 2 <= s < 4 else None)
    decoded = tmp_path/'shared'
    result = scan(video, tmp_path/'scan.json', decoded/'frames', 5)
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-vf', 'fps=1:round=up,scale=960:-2',
                          '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'], capture_output=True, check=True).stdout
    probes = np.frombuffer(raw, np.uint8).reshape(result['probes'], -1, 960, 3)
    kept = sorted((decoded/'compare').glob('*.png'))
    assert len(kept) < result['probes']
    for path in kept:
        slot = int(path.stem.split('-')[1])-1
        assert np.array_equal(np.asarray(Image.open(path).convert('RGB')), probes[slot])
    assert {(e['before'], e['after']) for e in result['events']} >= {(1, 2), (3, 4)}
    names = {p.name for p in kept}
    assert {comparison_name(s) for s in (1, 2, 3, 4, 5)} <= names  # event neighbours kept


@needs_ffmpeg
def test_resume_rejects_damaged_or_missing_comparison_frames(tmp_path):
    from scan_slide_changes import scan
    video = tmp_path/'v.mp4'
    make_video(video, 6)
    decoded = tmp_path/'shared'
    first = scan(video, tmp_path/'scan.json', decoded/'frames', 5)
    assert scan(video, tmp_path/'scan.json', decoded/'frames', 5) == first
    target = sorted((decoded/'compare').glob('*.png'))[0]
    original = target.read_bytes()
    target.write_bytes(original[:-1]+bytes([original[-1] ^ 1]))
    with pytest.raises(ValueError, match='Comparison frame'):
        scan(video, tmp_path/'scan.json', decoded/'frames', 5)
    target.unlink()
    with pytest.raises(ValueError, match='Comparison frame'):
        scan(video, tmp_path/'scan.json', decoded/'frames', 5)
    target.write_bytes(original)
    receipt = read_json(decoded/'extraction.json')
    receipt.pop('comparison')  # legacy receipt: never trusted just because files exist
    atomic_json(decoded/'extraction.json', receipt)
    with pytest.raises(ValueError, match='Comparison frame'):
        scan(video, tmp_path/'scan.json', decoded/'frames', 5)


@needs_ffmpeg
def test_pipeline_drops_codec_noise_but_keeps_minus_erasure_and_reveal(tmp_path):
    """Small changes below the 1 fps area threshold, plus a page-scale event that adds
    seek-frame boundaries next to unchanged 5 s samples."""
    import cv2
    from visual_pipeline import run

    def draw(frame, sec):
        if 3.4 <= sec < 8.4:
            frame[402:405, 640:652] = 0  # a minus sign, 12x3 px at 1280 (9x2 at 960)
        if sec >= 11.4:
            cv2.putText(frame, 'step 2', (60, 700), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 200), 1)
        if 16.5 <= sec < 17.6:  # brief overlay seen by probe 17: boundary frames 16/17/18/19
            frame[100:600, 100:1200] = (30, 30, 30)
    job = tmp_path/'job'
    make_video(job/'media/lecture.mp4', 24, draw)
    atomic_json(job/'media.json', dict(sha256=digest(job/'media/lecture.mp4'), duration=24.0))
    atomic_json(tmp_path/'refs.json', deck(tmp_path))
    report = run(job, tmp_path/'refs.json', tmp_path/'review', feature_cache=tmp_path/'features')
    alignment = read_json(tmp_path/'review/alignment.json')
    times = [row['time'] for row in alignment['observations']]
    assert {16, 17, 18, 19} <= set(times)  # boundary observations retained
    assert all(Path(row['comparison_image']).exists() for row in alignment['observations'])
    events = read_json(tmp_path/'review/differences.json')['events']
    spans = [(e['before_time'], e['after_time']) for e in events]
    covers = lambda t: any(a < t <= b for a, b in spans)
    assert covers(3.4) and covers(8.4) and covers(11.4)  # drawn, erased, revealed
    # Unchanged pairs around the overlay (15->16, 18->19, 19->20) must not report codec/scaler noise.
    for a, b in spans:
        assert any(a < t <= b for t in (3.4, 8.4, 11.4, 16.5, 17.6)), (a, b)
    assert report['difference_events'] == len(events)
