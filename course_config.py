"""Course manifests shared by the exporter and loopback reader (stdlib only)."""
from dataclasses import dataclass
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class CourseConfig:
    manifest: Path
    id: str
    title: str
    description: str
    course_dir: Path
    web_root: Path
    output_html: Path
    media: Path
    media_kind: str
    youtube_id: str

    def url_for(self, path):
        # Every served resource must belong to the selected course's web root.
        return Path(path).resolve().relative_to(self.web_root).as_posix()


def default_manifest():
    local = ROOT / 'course.local.json'
    return local if local.is_file() else ROOT / 'courses' / 'demo.json'


def load_course(path=None):
    manifest = Path(path or default_manifest()).resolve()
    doc = json.loads(manifest.read_text(encoding='utf-8-sig'))
    if not isinstance(doc, dict) or type(doc.get('schema')) is not int or doc['schema'] != 1:
        raise ValueError('Course manifest schema must be 1')
    course_id = doc.get('id', '')
    if not isinstance(course_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', course_id):
        raise ValueError('Course id must be a stable, non-empty identifier')
    title = doc.get('title')
    if not isinstance(title, str) or not title.strip():
        raise ValueError('Course title is required')
    def resolve(key):
        value = doc.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f'Course manifest requires {key}')
        return (manifest.parent / value).resolve()
    web_root = resolve('web_root')
    output_name = doc.get('output_html', 'index.html')
    if not isinstance(output_name, str) or not output_name:
        raise ValueError('output_html must be a non-empty HTML path')
    output = web_root / output_name
    media = resolve('media')
    kind = doc.get('media_kind', 'video')
    if kind not in {'audio', 'video'}:
        raise ValueError('media_kind must be audio or video')
    youtube_id = doc.get('youtube_id', '')
    if not isinstance(youtube_id, str) or (youtube_id and not re.fullmatch(r'[A-Za-z0-9_-]{11}', youtube_id)):
        raise ValueError('youtube_id must be empty or an 11-character YouTube id')
    course = CourseConfig(manifest, course_id, title.strip(), str(doc.get('description', '')),
                          resolve('course_dir'), web_root, output.resolve(), media, kind, youtube_id)
    course.url_for(output)
    course.url_for(media)
    course.url_for(course.course_dir)
    if output.suffix.lower() != '.html':
        raise ValueError('output_html must end in .html')
    return course
