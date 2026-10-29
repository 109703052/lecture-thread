"""Check the built public demo: reader page, embedded payload, slides and audio."""
import json
from pathlib import Path
import re
import sys
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from course_config import load_course


def verify_demo():
    course = load_course(ROOT / 'courses/demo.json')
    source = Path(__file__).resolve().parent
    html = course.output_html.read_text(encoding='utf-8')
    for placeholder in ('__COURSE_PAYLOAD__', '/*READER_JS*/', '/*READER_CSS*/'):
        if placeholder in html:
            raise AssertionError(f'{course.output_html} still contains {placeholder}')
    match = re.search(r'<script type="application/json" id="course-data">(.*?)</script>', html, re.S)
    if not match:
        raise AssertionError(f'{course.output_html} has no embedded course data')
    data = json.loads(match.group(1))
    evidence = json.loads((source / 'slide_evidence.json').read_text(encoding='utf-8'))
    transcript = json.loads((source / 'transcript.json').read_text(encoding='utf-8'))
    assert data['course_id'] == course.id == 'lecturethread-demo'
    # The overview plus one section per slide occurrence, revisits included.
    assert len(data['segments']) == 1 + len(evidence)
    assert len(data['transcript']) == len(transcript)
    for segment in data['segments']:
        if segment['image']:
            image = course.web_root / segment['image']
            assert image.is_file() and image.stat().st_size, f'missing slide {image}'
    media = course.web_root / data['video_src']
    with wave.open(str(media), 'rb') as audio:
        duration = audio.getnframes() / audio.getframerate()
    assert data['media_kind'] == 'audio' and abs(duration - data['media_duration']) < .01
    assert abs(duration - 36) < .01, f'Expected 36 s demo audio, got {duration:g} s'
    print(f'Verified {course.output_html}: {len(data["segments"])} sections, '
          f'{len(data["transcript"])} transcript lines, {duration:g} s synthetic audio.')


if __name__ == '__main__':
    verify_demo()
