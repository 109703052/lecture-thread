import json
import subprocess
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from viewer_sync import patch_viewer
from cs_timeline import refine_timeline
from course_config import load_course
COURSE=load_course()
TIMELINE=COURSE.web_root/COURSE.output_html.stem/'_timeline.json'

@pytest.mark.skipif(not all(p.is_file() for p in [
    TIMELINE,
    COURSE.course_dir/'slide_evidence.json',
    ROOT/'vendor/lecture-to-notes/scripts/layout2/viewer.js',
]), reason='Requires local course export and optional upstream checkout')
def test_real_viewer_navigation_with_course_timeline():
    course=COURSE.course_dir
    t=json.loads((TIMELINE).read_text(encoding='utf-8'))
    evidence=json.loads((course/'slide_evidence.json').read_text(encoding='utf-8'))
    t=refine_timeline(t,evidence,evidence[-1]['end'])
    source=patch_viewer((ROOT/'vendor/lecture-to-notes/scripts/layout2/viewer.js').read_text(encoding='utf-8'))
    functions=source[source.index('function matchingBlocks('):source.index("for(const paneSel of ['#summary-pane','#replay-pane']){\n  const pane = q(paneSel);")]
    harness="""
const assert=require('node:assert/strict');
const segments=TIMELINE.segments, blocks=TIMELINE.note_blocks;
let activeSegmentId='',currentView='segment',autoScroll=false;
const player={paused:false}, now={textContent:''};
function q(s){return s==='#player'?player:s==='#now'?now:null}
function qa(){return []}
function segmentById(id){return segments.find(s=>s.segment_id===id)}
function segFiles(s){return s.media_files||[s.media_file]}
function showSegment(id){activeSegmentId=id}
function fmt(t){return String(t)}
function setAutoScroll(){}
function effectiveAutoScroll(){return false}
const CSS={escape:s=>s};
"""
    checks="""
const content=segments.filter(s=>!s.is_overview);
const overview=segments.find(s=>s.is_overview);
for(const s of content){
  activeSegmentId=s.segment_id;
  const f=segFiles(s)[0];
  // Card click: forced synchronization must keep the selected page in a gap.
  player.paused=true;
  activateForTime(f,s.start_sec,false,true);
  assert.equal(activeSegmentId,s.segment_id,'card '+s.segment_number);
  player.paused=false;
  activateForTime(f,s.start_sec+0.1,false);
  assert.equal(activeSegmentId,s.segment_id,'play '+s.segment_number);
}
for(let i=0;i<content.length-1;i++){
  activeSegmentId=content[i].segment_id;
  activateForTime(segFiles(content[i+1])[0],content[i+1].start_sec,false);
  assert.equal(activeSegmentId,content[i+1].segment_id,'boundary '+i);
}
activeSegmentId=overview.segment_id;
activateForTime(segFiles(overview)[0],39,false);
assert.equal(activeSegmentId,overview.segment_id,'explicit overview remains readable');
currentView='home';
activateForTime(segFiles(content[0])[0],39,false);
assert.equal(currentView,'home');
console.log(content.length+' card clicks and playback starts; boundaries, overview and home passed');
"""
    result=subprocess.run(['node','-'],input='const TIMELINE='+json.dumps(t)+';'+harness+functions+checks,text=True,encoding='utf-8',capture_output=True)
    assert result.returncode==0,result.stderr
