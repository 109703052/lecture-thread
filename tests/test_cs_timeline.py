import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cs_timeline',ROOT/'cs_timeline.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_timeline_uses_media_end_and_preserves_revisit():
    evidence=[dict(occurrence_id=1,start=0,end=10,image='same.jpg',title='first',ocr={}),dict(occurrence_id=2,start=10,end=20,image='same.jpg',title='return',ocr={})]
    blocks=[dict(section_id='s1-l3',segment_id='s1',start_sec=0,end_sec=45),dict(section_id='s1-l3',segment_id='s1',start_sec=0,end_sec=45),dict(section_id='s2-l3',segment_id='s2',start_sec=19,end_sec=64)]
    t=dict(media_parts=[dict(file='v.mp4')],note_blocks=blocks,chapters=[dict(section_id='s1-l3'),dict(section_id='s2-l3')],segments=[dict(segment_id='s1'),dict(segment_id='s2')])
    got=m.refine_timeline(t,evidence,20)
    assert [b['end_sec'] for b in got['note_blocks']]==[10,10,20]
    assert len(got['slide_blocks'])==2
    assert got['segments'][1]['start_sec']==10
    assert got['media_parts'][0]['duration_sec']==20
