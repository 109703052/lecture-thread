"""Validate extracted frame sequences before assigning their time slots."""
from pathlib import Path

from pipeline_common import digest


def frame_manifest(folder):
    paths = sorted(Path(folder).glob('frame-*.jpg'))
    expected = [f'frame-{i:06d}.jpg' for i in range(1, len(paths)+1)]
    if not paths or [p.name for p in paths] != expected:
        raise ValueError('Frame cache sequence is incomplete; use a new output directory')
    return dict(frames=len(paths), frame_sha256={p.name: digest(p) for p in paths})


def validate_frame_cache(folder, receipt, expected_count=None):
    """Fail closed on legacy, missing, extra, renamed or modified frame files."""
    count = receipt.get('frames')
    hashes = receipt.get('frame_sha256')
    if type(count) is not int or count < 1 or not isinstance(hashes, dict):
        raise ValueError('Frame cache has no integrity manifest; use a new output directory')
    if expected_count is not None and count != expected_count:
        raise ValueError('Frame cache count differs from scan probes; use a new output directory')
    names = [f'frame-{i:06d}.jpg' for i in range(1, count+1)]
    paths = sorted(Path(folder).glob('frame-*.jpg'))
    if [p.name for p in paths] != names or set(hashes) != set(names):
        raise ValueError('Frame cache sequence is incomplete; use a new output directory')
    for path in paths:
        if digest(path) != hashes[path.name]:
            raise ValueError(f'Frame cache content changed: {path}; use a new output directory')
    return paths
