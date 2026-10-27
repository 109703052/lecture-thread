"""Build a separate static reader package with YouTube video and AAC audio."""
import argparse
import json
import subprocess
from pathlib import Path

from build_reader import build
from course_config import load_course


def export(manifest, destination, audio_url=None):
    course = load_course(manifest)
    destination = Path(destination).resolve()
    # A fresh directory prevents stale/private files from entering a publication.
    if destination.exists():
        raise ValueError('Choose a new output directory; existing directories are never overwritten')
    if not course.youtube_id:
        raise ValueError('This export requires a YouTube video ID')
    destination.mkdir(parents=True)
    if not audio_url:
        subprocess.run([
            'ffmpeg', '-nostdin', '-v', 'error', '-n', '-i', str(course.media),
            '-map', '0:a:0', '-vn', '-c:a', 'aac', '-b:a', '64k',
            '-movflags', '+faststart', str(destination / 'audio.m4a'),
        ], check=True)
    build(course, publish_dir=destination, audio_url=audio_url or 'audio.m4a')
    (destination / 'publication.json').write_text(json.dumps({
        'course_id': course.id, 'youtube_id': course.youtube_id,
        'audio_url': audio_url or 'audio.m4a', 'read_only': True,
    }, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audio-url', help='HTTPS URL of an already uploaded full-length audio file')
    args = parser.parse_args()
    try:
        export(args.course, args.output, args.audio_url)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
