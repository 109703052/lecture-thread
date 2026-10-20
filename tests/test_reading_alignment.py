import json
import sys
import pytest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from build_reader import align
from course_config import load_course
COURSE=load_course()

def test_crossing_sentence_maps_to_both_reading_paragraphs():
    tx=[dict(start=8,end=12),dict(start=12,end=15)]
    assert align(0,10,tx)==[0]
    assert align(10,15,tx)==[0,1]
    assert align(15,20,tx)==[]

@pytest.mark.skipif(not (COURSE.course_dir/'reading_alignment.json').is_file(),
                    reason='Local course export is not distributed with the source')
def test_delivered_course_and_comparison_workspace():
    data=json.loads((COURSE.course_dir/'reading_alignment.json').read_text(encoding='utf-8'))
    notes=json.loads((COURSE.course_dir/'authored_notes.json').read_text(encoding='utf-8'))
    assert len(data['segments'])==len(notes)+1
    assert sum(len(s['sections']) for s in data['segments'][1:])==sum(len(n['lesson']) for n in notes)
    assert data['course_id']==COURSE.id
    for s in data['segments']:
        if s['image']:assert (COURSE.web_root/s['image']).is_file()
        for p in s['sections']:
            assert p['source_ids']==align(p['time'],p['end'],data['transcript'])
    html=(COURSE.output_html).read_text(encoding='utf-8')
    assert 'preload="none"' in html and '<iframe' not in html
    assert (COURSE.web_root/data['video_src']).is_file()
    assert data['youtube_id']==COURSE.id
    assert '<details class="figure"' not in html
    assert 'id="restore-ratio"' in html and 'id="hide-video"' in html
    assert 'id="toggle-transcript"' in html and 'id="chapter-nav" hidden' in html
