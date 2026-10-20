"""Load an explicit CS profile without modifying the vendored upstream code."""
import importlib.util
import json
import re
import copy
from pathlib import Path
import sys
import yaml
ROOT=Path(__file__).resolve().parent
PROFILE=ROOT/'profiles/computer-science'

def load_stage(script):
    script=Path(script).resolve()
    sys.path.insert(0,str(script.parent))
    spec=importlib.util.spec_from_file_location('lecture_profile_stage',script)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if script.name=='vlm_signals.py':
        module.PROMPT=(PROFILE/'vlm-prompt.txt').read_text(encoding='utf-8-sig')
        module.FALLBACK_PROMPT=(PROFILE/'vlm-fallback.txt').read_text(encoding='utf-8-sig')
    elif script.name=='ground_slides.py':
        cfg=yaml.safe_load((PROFILE/'config.yaml').read_text(encoding='utf-8-sig'))
        module.DEFAULT_CONFIG=cfg
        original=module.compute_signals
        def compute(*args,**kwargs):
            slide, segments, config = args[:3]
            result=original(*args,**kwargs)
            window_ids=result['transcript_signals']['transcript_segment_ids']
            text=' '.join(str(v) for v in (slide.get('ocr') or {}).values())
            text+=' '+' '.join(segments[i].get('text','') for i in window_ids)
            tags=[]
            for tag, terms in config['keyword_grounding']['clinical_domain_map'].items():
                if any(re.search(r'(?<![A-Za-z0-9])'+re.escape(term)+r'(?![A-Za-z0-9])',text,re.I) for term in terms):
                    tags.append(tag)
            result['retrieval']['domain_tags']=tags
            result['retrieval']['clinical_domain']=tags  # upstream schema compatibility only
            result['transcript_signals']['skip_score_is_heuristic']=True
            return result
        module.compute_signals=compute
    elif script.name=='export_web.py':
        from cs_timeline import refine_timeline
        from viewer_sync import patch_viewer
        original_read_asset=module.read_asset
        def read_asset(name):
            source=original_read_asset(name)
            if name=='viewer.js' and (Path(module.COURSE)/'slide_evidence.json').exists():
                return patch_viewer(source)
            return source
        module.read_asset=read_asset
        original=module.build_timeline
        def build_timeline(resolver):
            sections,timeline=original(resolver)
            course=Path(module.COURSE)
            evidence_file=course/'slide_evidence.json'
            coverage_file=course/'coverage_report.json'
            if evidence_file.exists() and coverage_file.exists():
                evidence=json.loads(evidence_file.read_text(encoding='utf-8'))
                duration=json.loads(coverage_file.read_text(encoding='utf-8'))['duration_seconds']
                timeline=refine_timeline(timeline,evidence,duration)
            return sections,timeline
        module.build_timeline=build_timeline
    return module

if __name__=='__main__':
    script=sys.argv.pop(1)
    module=load_stage(script)
    if Path(script).name=='ground_slides.py' and '--config' not in sys.argv:
        sys.argv.extend(['--config',str(PROFILE/'config.yaml')])
    raise SystemExit(module.main() or 0)
