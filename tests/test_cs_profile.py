import importlib.util
from pathlib import Path
import pytest
import tempfile
ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'vendor/lecture-to-notes/scripts/vlm_signals.py').is_file():
    pytest.skip('Optional upstream checkout is not included in the source', allow_module_level=True)
spec=importlib.util.spec_from_file_location('profile_stage',ROOT/'profile_stage.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

def test_cs_prompt_and_fallback():
    m=p.load_stage(ROOT/'vendor/lecture-to-notes/scripts/vlm_signals.py')
    assert 'computer science' in m.PROMPT
    assert 'computer science' in m.FALLBACK_PROMPT
    assert 'diagnostic_algorithm' not in m.PROMPT
    assert 'kaplan_meier' not in m.FALLBACK_PROMPT
    assert 'contains_clinical_imaging: false' in m.PROMPT

def test_domain_no_substring_false_positive():
    m=p.load_stage(ROOT/'vendor/lecture-to-notes/scripts/ground_slides.py')
    cfg=m.DEFAULT_CONFIG
    def tags(text):
        slide={'timestamp_start':0,'timestamp_end':10,'ocr':{'quick_text':text}}
        return m.compute_signals(slide,[{'start':0,'end':9,'text':text}],cfg,None,0)['retrieval']['domain_tags']
    assert 'memory' not in tags('a diagram of a program')
    assert 'memory' in tags('DRAM refresh and SRAM')
    assert 'storage' in tags('SSD and NAND flash')
    assert not cfg['keyword_grounding']['drug_suffixes']
    assert not cfg['keyword_grounding']['medical_term_suffixes']


@pytest.fixture
def profile_tmp_path():
    parent = ROOT/'data/tmp'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='vlm-adapter-test-',dir=parent) as folder:
        yield Path(folder)


def test_vlm_checkpoint_retries_sharing_violation_without_mutating_global_os(profile_tmp_path, monkeypatch):
    import os
    import pipeline_common
    module = p.load_stage(ROOT/'vendor/lecture-to-notes/scripts/vlm_signals.py')
    source = profile_tmp_path/'checkpoint.tmp'
    target = profile_tmp_path/'checkpoint.json'
    source.write_text('saved', encoding='utf-8')
    calls = []
    original = os.replace
    def replace(a,b):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError('temporary reader handle')
        original(a,b)
    monkeypatch.setattr(pipeline_common.os,'replace',replace)
    monkeypatch.setattr(pipeline_common.time,'sleep',lambda *_:None)
    assert module.os is not os
    module.os.replace(source,target)
    assert target.read_text() == 'saved' and len(calls)==2
    assert module.atomic_write_json is pipeline_common.atomic_json
