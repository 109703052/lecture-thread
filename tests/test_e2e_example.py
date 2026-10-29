"""Original end-to-end example: generators and bridge tools, without TTS, ASR or models."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from editorial_content import validate_editorial
from pipeline_common import atomic_json, digest
from reading_layer import load_reading_paragraphs

EXAMPLE = Path(__file__).resolve().parents[1]/'examples/end-to-end'
sys.path.insert(0, str(EXAMPLE/'scripts'))


def tool(name):
    spec = importlib.util.spec_from_file_location(f'e2e_{name}', EXAMPLE/'scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sources():
    read = lambda name: json.loads((EXAMPLE/'course'/name).read_text(encoding='utf-8'))
    return read('deck.json'), read('storyboard.json')


def test_tracked_sources_are_consistent_and_plan_every_event_kind():
    gen = tool('generate_materials')
    deck, story = sources()
    gen.validate_sources(deck, story)
    durations = {seg['id']: 8.0 for seg in story['segments']}
    plan = gen.plan_timeline(story, durations)
    kinds = [e['kind'] for e in plan['events']]
    for kind in ('page_change', 'revisit', 'reveal', 'annotation_add', 'annotation_erase',
                 'brief_page', 'return', 'challenge_flash', 'return_after_flash'):
        assert kind in kinds, kind
    states = plan['states']
    assert states[0]['start'] == 0 and states[-1]['end'] == plan['duration']
    assert all(a['end'] == b['start'] and a['state'] != b['state'] for a, b in zip(states, states[1:]))
    # Main events last at least one 5 s sample at realistic speech length; the flash is the only sub-second one.
    short = [e for e in plan['events'] if e['state_seconds'] < 1]
    assert [e['kind'] for e in short] == ['challenge_flash'] and short[0]['challenge']
    # A mark persists across a detour and comes back with its page.
    detour = next(e for e in plan['events'] if e['kind'] == 'return')
    back = next(s for s in states if s['start'] == detour['time'])
    assert back['state']['marks'] == ['wrap-arrow']


def test_validation_rejects_marks_from_another_page_and_overlong_inserts():
    gen = tool('generate_materials')
    deck, story = sources()
    broken = json.loads(json.dumps(story))
    broken['segments'][1]['add_marks'] = ['wrap-arrow']  # belongs to the trace page
    with pytest.raises(ValueError, match='does not belong'):
        gen.validate_sources(deck, broken)
    durations = {seg['id']: 2.0 for seg in story['segments']}
    with pytest.raises(ValueError, match='beyond its narration'):
        gen.plan_timeline(story, durations)


def test_deck_pdf_has_text_layer_and_annotations_change_only_video_frames(tmp_path):
    pytest.importorskip('pymupdf')
    import numpy as np
    from PIL import Image
    gen = tool('generate_materials')
    deck, _ = sources()
    gen.build_deck(deck, tmp_path/'deck.pdf')
    import pymupdf
    with pymupdf.open(tmp_path/'deck.pdf') as doc:
        assert len(doc) == len(deck['pages'])
        text = doc[3].get_text()
    assert '逐步追蹤' in text and '4→0' not in text  # live annotations are not part of the deck
    plain, marked = tmp_path/'plain.png', tmp_path/'marked.png'
    gen.render_state(deck, dict(page='trace', reveal=None, marks=[]), plain)
    gen.render_state(deck, dict(page='trace', reveal=None, marks=['wrap-arrow']), marked)
    a, b = (np.asarray(Image.open(p).convert('L'), dtype=np.int16) for p in (plain, marked))
    changed = np.mean(np.abs(a-b) > 25)
    assert 0 < changed < .025  # small: below the 1 fps scan's area threshold by design


def test_correction_plan_is_exact_and_keeps_timing():
    fix = tool('apply_corrections')
    raw = [dict(start=0.0, end=2.0, text='循环注列最多只存4个'), dict(start=2.0, end=3.0, text='如果这时候在InQG')]
    plan = dict(corrections=[
        dict(segment_id=0, find='注列', replace='佇列', basis='narration-script', reason='script'),
        dict(segment_id=0, find='最多隻存', replace='最多只存', basis='normalization-fix', reason='OpenCC 隻'),
        dict(segment_id=1, find='在InQG', replace='再enqueue G', basis='narration-script', reason='script')])
    corrected, audit = fix.apply_plan(raw, plan)
    assert [r['text'] for r in corrected] == ['循環佇列最多只存4個', '如果這時候再enqueue G']
    assert [(r['start'], r['end']) for r in corrected] == [(0.0, 2.0), (2.0, 3.0)]
    assert raw[0]['text'] == '循环注列最多只存4个'  # the raw list is not mutated
    assert all(row['audio_verified'] is False and row['status'] == 'corrected' for row in audit)
    plan['corrections'].append(dict(segment_id=1, find='不存在', replace='x', basis='slide-text', reason='r'))
    with pytest.raises(ValueError, match='expected 1'):
        fix.apply_plan(raw, plan)


def visual_fixture():
    alignment = dict(intervals=[
        dict(start=0, end=15, last_observed=14, status='candidate', page_id='d:1', observations=4),
        dict(start=15, end=40, last_observed=39, status='candidate', page_id='d:2', observations=6),
        dict(start=40, end=50, last_observed=49, status='candidate', page_id='d:1', observations=3)])
    differences = dict(events=[
        dict(page_id='d:2', before_time=20, after_time=25),
        dict(page_id='d:2', before_time=30, after_time=35)])
    decisions = dict(runs=[dict(id=f'R{i:02}', decision='confirmed', page_id=r['page_id'], candidate_page=r['page_id'],
                                                   start=r['start'], last_observed=r['last_observed'], status=r['status']) for i, r in enumerate(alignment['intervals'], 1)],
                     differences=[dict(id='D01', decision='annotation_add', meaning='arrow'),
                                  dict(id='D02', decision='noise', meaning='')])
    for row, event in zip(decisions['differences'], differences['events']):
        row.update(event)
    return alignment, differences, decisions


def test_evidence_keeps_revisits_and_splits_only_at_accepted_changes():
    build = tool('build_evidence')
    alignment, differences, decisions = visual_fixture()
    rows = build.plan_occurrences(alignment, differences, decisions, 50.0)
    assert [(r['start'], r['end'], r['page_id'], r['change']) for r in rows] == [
        (0, 15, 'd:1', 'start'), (15, 25, 'd:2', 'page_change'), (25, 40, 'd:2', 'annotation_add'),
        (40, 50.0, 'd:1', 'revisit')]


def test_decisions_must_be_complete_and_bound_to_the_visual_output(tmp_path):
    build = tool('build_evidence')
    alignment, differences, decisions = visual_fixture()
    atomic_json(tmp_path/'alignment.json', alignment)
    atomic_json(tmp_path/'differences.json', differences)
    decisions.update(alignment_sha256=digest(tmp_path/'alignment.json'),
                     differences_sha256=digest(tmp_path/'differences.json'), reviewer='r', method='looked')
    build.check_decisions(decisions, alignment, differences, tmp_path)
    decisions['differences'][0]['decision'] = 'pending'
    with pytest.raises(ValueError, match='decision must be one of'):
        build.check_decisions(decisions, alignment, differences, tmp_path)
    decisions['differences'][0]['decision'] = 'annotation_add'
    decisions['alignment_sha256'] = 'stale'
    with pytest.raises(ValueError, match='different visual output'):
        build.check_decisions(decisions, alignment, differences, tmp_path)


def test_reading_draft_assembles_into_a_valid_reader_layer(tmp_path):
    reading = tool('build_reading_layer')
    corrected = [dict(start=0, end=1, text='那個 front 是零'), dict(start=1, end=2, text='rear 也是零')]
    draft = dict(author='Claude Code', authoring_method='m', paragraphs=[dict(
        source_ids=[0, 1], text='front 和 rear 都是 0。',
        sentences=[dict(text='front 和 rear 都是 0。', source_ids=[0, 1])])])
    doc = reading.assemble(draft, corrected, 'base', 'raw', 'missing')
    atomic_json(tmp_path/'r.json', doc)
    rows = load_reading_paragraphs(tmp_path/'r.json', corrected, 'base')
    assert rows[0]['originals'] == ['那個 front 是零', 'rear 也是零'] and rows[0]['end'] == 2


def test_evaluation_cer_ignores_punctuation_and_digit_spelling():
    evaluate = tool('evaluate')
    reference = evaluate.flatten('容量五，最多存四個。', True)
    assert evaluate.cer(evaluate.flatten('容量5最多存4個', True), reference) == 0
    assert evaluate.cer(evaluate.flatten('容量5最多存', True), reference) == round(2/len(reference), 4)


def test_direct_authors_are_named_and_others_rejected():
    tx = [dict(start=0, end=1, text='a')]
    doc = dict(schema=1, author='Claude Code', course_date='d', title='t', overview='o', raw_transcript_sha256='h',
               chapters=[dict(title='c', summary='s', start=0, end=1, paragraphs=[
                   dict(heading='h', text='x', time=0, source_ids=[0])])])
    assert validate_editorial(doc, tx, 1, 'h') is doc
    doc['author'] = 'qwen2.5:7b'
    with pytest.raises(ValueError, match='author one of'):
        validate_editorial(doc, tx, 1, 'h')



def test_reordered_decisions_keep_the_same_evidence():
    build = tool('build_evidence')
    alignment, differences, decisions = visual_fixture()
    expected = build.plan_occurrences(alignment, differences, decisions, 50)
    decisions['runs'].reverse()
    decisions['differences'].reverse()
    assert build.plan_occurrences(alignment, differences, decisions, 50) == expected


@pytest.mark.parametrize('key', ['runs', 'differences'])
@pytest.mark.parametrize('damage', ['duplicate', 'missing', 'unknown', 'metadata'])
def test_decision_identity_damage_is_rejected(key, damage):
    build = tool('build_evidence')
    alignment, differences, decisions = visual_fixture()
    rows = decisions[key]
    if damage == 'duplicate':
        rows[-1] = dict(rows[0])
    elif damage == 'missing':
        rows.pop()
    elif damage == 'unknown':
        rows[0]['id'] = 'unknown'
    else:
        rows[0]['start' if key == 'runs' else 'after_time'] = 999
    with pytest.raises(ValueError, match='decision IDs|source metadata'):
        build.plan_occurrences(alignment, differences, decisions, 50)


@pytest.mark.parametrize('noise_indices', [[0], [1], [2], [0, 1, 2]])
def test_noise_runs_block_evidence_without_extending_neighbours(noise_indices):
    build = tool('build_evidence')
    alignment, differences, decisions = visual_fixture()
    for i in noise_indices:
        decisions['runs'][i]['decision'] = 'noise'
    with pytest.raises(ValueError, match='Noise runs cannot be published'):
        build.plan_occurrences(alignment, differences, decisions, 50)


def test_pdf_generation_is_byte_reproducible(tmp_path):
    gen = tool('generate_materials')
    deck, _ = sources()
    gen.build_deck(deck, tmp_path/'a.pdf')
    gen.build_deck(deck, tmp_path/'b.pdf')
    assert digest(tmp_path/'a.pdf') == digest(tmp_path/'b.pdf')


def material_receipt(gen, folder):
    names = ('deck.pdf', 'deck.json', 'narration.wav', 'lecture.mp4',
             'expected_events.json', 'narration_script.json')
    for name in names:
        (folder/name).write_bytes(name.encode())
    receipt = dict(sources={name: digest(gen.COURSE/name) for name in
                           ('deck.json', 'storyboard.json', 'content-baseline.json')},
                   generator_sha256=digest(Path(gen.__file__)),
                   files={name: dict(sha256=digest(folder/name)) for name in names})
    atomic_json(folder/'materials.json', receipt)
    return receipt


def test_unchanged_materials_reuse_without_writes_or_inference(tmp_path, monkeypatch):
    gen = tool('generate_materials')
    material_receipt(gen, tmp_path)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    def unexpected(*args, **kwargs):
        pytest.fail('reuse must not generate PDF, speech or video')
    monkeypatch.setattr(gen, 'build_deck', unexpected)
    monkeypatch.setattr(gen, 'synthesize', unexpected)
    monkeypatch.setattr(gen.subprocess, 'run', unexpected)
    assert gen.main(['--out', str(tmp_path)]) == 0
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize('damage', ['source', 'generator', 'missing', 'modified', 'receipt'])
def test_material_reuse_rejects_stale_or_damaged_artifacts(tmp_path, damage):
    gen = tool('generate_materials')
    saved = material_receipt(gen, tmp_path)
    if damage == 'source':
        saved['sources']['deck.json'] = 'stale'
    elif damage == 'generator':
        saved['generator_sha256'] = 'stale'
    elif damage == 'missing':
        (tmp_path/'deck.pdf').unlink()
    elif damage == 'modified':
        (tmp_path/'deck.pdf').write_bytes(b'changed')
    atomic_json(tmp_path/'materials.json', saved)
    if damage == 'receipt':
        (tmp_path/'materials.json').unlink()
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError, match='new --out'):
        gen.reuse_materials(tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
