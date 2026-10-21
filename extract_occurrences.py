"""Lossless sampled-frame occurrences: merge adjacent pixel-identical frames only."""
import argparse
import hashlib
from pathlib import Path
import subprocess

from pipeline_common import atomic_json


def extract(video, course, interval=2):
    from PIL import Image
    course = Path(course)
    samples = course / '_samples'
    slides = course / 'slides'
    samples.mkdir(parents=True, exist_ok=True)
    slides.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-vf',
                    f'fps=1/{interval}:round=up', str(samples / 'frame_%06d.png')], check=True)
    frames = sorted(samples.glob('frame_*.png'))
    if not frames:
        raise ValueError('影片沒有可擷取的畫面')
    rows, previous = [], None
    hashes = {}
    import shutil
    for i, frame in enumerate(frames):
        with Image.open(frame) as image:
            image = image.convert('RGB')
            value = hashlib.sha256(str(image.size).encode()+image.tobytes()).hexdigest()
        at = i * interval
        if value == previous:
            rows[-1]['timestamp'] = at
            rows[-1]['group_size'] += 1
        else:
            # Revisit stays an occurrence, even when the image is shared.
            filename = hashes.setdefault(value, frame.name)
            if not (slides / filename).exists():
                shutil.copyfile(frame, slides / filename)
            rows.append(dict(slide=len(rows)+1, first_ts=at, timestamp=at,
                             filename=filename, group_size=1, pixel_sha256=value))
        previous = value
    atomic_json(slides / 'timestamps.json', rows)
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('course', type=Path)
    parser.add_argument('--interval', type=int, default=2)
    args = parser.parse_args()
    if args.interval < 1:
        parser.error('interval must be positive')
    rows = extract(args.video, args.course, args.interval)
    print(f'Preserved {len(rows)} occurrences; all sampled PNGs retained.')
