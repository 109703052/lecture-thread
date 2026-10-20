"""Keep playback navigation inside measured slide intervals, including speech gaps."""
OLD = """  const candidates = matchingBlocks(file,t);
  if(!candidates.length) return;
  const preferred = candidates.find(b=>b.segment_id===activeSegmentId) || candidates.find(b=>b.section_kind==='summary_note') || candidates[0];
  const segId = preferred.segment_id;
  showSegment(segId, false);
  const active = candidates.filter(b=>b.segment_id===segId);"""
NEW = """  const candidates = matchingBlocks(file,t);
  const containsTime = s => segFiles(s).includes(file) && Number(s.start_sec) <= t && t < Number(s.end_sec);
  const selected = segmentById(activeSegmentId);
  // The overview overlaps every slide. Only retain it when explicitly selected;
  // never use its text as a fallback for a slide's leading gap or silence.
  const owner = (selected && containsTime(selected) ? selected : null)
    || segments.find(s => !s.is_overview && containsTime(s));
  if(!owner) return;
  const segId = owner.segment_id;
  showSegment(segId, false);
  const active = candidates.filter(b=>b.segment_id===segId);
  if(!active.length){
    qa('[data-sync-block]').forEach(el=>el.classList.remove('is-active'));
    q('#now').textContent = '▶ '+file+' @ '+fmt(t)+' — '+owner.title;
    return;
  }"""

def patch_viewer(source):
    if source.count(OLD) != 1:
        raise RuntimeError('Viewer sync source changed; review adapter before exporting')
    return source.replace(OLD, NEW)
