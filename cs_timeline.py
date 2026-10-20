"""Use measured occurrence bounds instead of the upstream last-bullet +45s heuristic."""
from collections import defaultdict

def refine_timeline(timeline,evidence,duration):
    bounds={f"s{x['occurrence_id']}":(x['start'],x['end']) for x in evidence}
    overview=f's{len(evidence)+1}'
    bounds[overview]=(0,duration)
    for media in timeline['media_parts']:media['duration_sec']=duration
    groups=defaultdict(list)
    for block in timeline['note_blocks']:groups[block['section_id']].append(block)
    for blocks in groups.values():
        starts=sorted(set(b['start_sec'] for b in blocks))
        for b in blocks:
            end_bound=bounds[b['segment_id']][1]
            nxt=next((x for x in starts if x>b['start_sec']),end_bound)
            b['end_sec']=min(duration,max(b['start_sec'],min(nxt,end_bound)))
    for chapter in timeline['chapters']:
        blocks=groups[chapter['section_id']]
        chapter['start_sec']=min(b['start_sec'] for b in blocks)
        chapter['end_sec']=max(b['end_sec'] for b in blocks)
    for segment in timeline['segments']:
        segment['is_overview']=segment['segment_id']==overview
        start,end=bounds[segment['segment_id']]
        segment.update(start_sec=start,end_sec=end,duration_sec=round(end-start,3))
    media=timeline['media_parts'][0]['file']
    timeline['slide_blocks']=[dict(media_file=media,start_sec=e['start'],end_sec=e['end'],frame=e['image'],text=e['title']+'\n'+(e['ocr'] or {}).get('quick_text','')) for e in evidence]
    timeline['lecture_profile']='computer-science'
    timeline['timing_method']='2-second frame sampling; original transcript timestamps preserved'
    return timeline
