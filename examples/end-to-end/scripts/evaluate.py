"""Compare the processed example with its ground truth. Evaluation only.

Usage (project root):
  .venv/Scripts/python.exe examples/end-to-end/scripts/evaluate.py [--job output/jobs/e2e-circular-queue]
      [--materials output/e2e-circular-queue/materials] [--out output/e2e-circular-queue/evaluation]

This is the only step that reads expected_events.json and narration_script.json.
It reports, without changing any course file:
  - ASR character error rate (raw and corrected) against the narration script
  - expected visual events vs. 1 fps scan events, page runs, difference events
    and the reviewed occurrences (misses and extra detections listed)
  - data checks: raw ASR hash, corrected timing, evidence images, reading base
  - presence of the content-baseline facts in the authored notes (a keyword
    check, not a teaching-quality review)
Numbers describe one synthetic voice on one machine; they are not an accuracy
estimate for real lecture recordings.
"""
import argparse
import json
from pathlib import Path
import re
import sys

EXAMPLE = Path(__file__).resolve().parents[1]
ROOT = EXAMPLE.parents[1]
sys.path.insert(0, str(ROOT))
from pipeline_common import atomic_json, digest, read_json  # noqa: E402

PAGE_KINDS = {'page_change', 'revisit', 'brief_page', 'return', 'challenge_flash', 'return_after_flash'}
LOCAL_KINDS = {'reveal', 'annotation_add', 'annotation_erase'}
NUMERALS = dict(zip('0123456789', '零一二三四五六七八九'))
TERMS = ['佇列', 'enqueue', 'dequeue', 'front', 'rear', '索引', '取餘數', 'count', '實作', '這一課']


def flatten(text, numerals=False):
    if numerals:
        text = ''.join(NUMERALS.get(c, c) for c in text)
    return re.sub(r'[\s\W_]+', '', text.lower())


def edit_distance(a, b):
    previous = list(range(len(b)+1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j]+1, current[j-1]+1, previous[j-1]+(x != y)))
        previous = current
    return previous[-1]


def cer(hypothesis, reference):
    return round(edit_distance(hypothesis, reference)/max(1, len(reference)), 4)


def asr_report(script, raw, corrected):
    from traditional_chinese import traditional
    reference = ''.join(s['text'] for s in script['segments'])
    raw_text = ''.join(r['text'] for r in raw)
    fixed = ''.join(r['text'] for r in corrected)
    ref = flatten(reference, True)
    return dict(
        reference_characters=len(ref),
        cer_raw_as_is=cer(flatten(raw_text, True), ref),
        cer_raw_after_opencc=cer(flatten(traditional(raw_text), True), ref),
        cer_corrected=cer(flatten(fixed, True), ref),
        normalization='lower-case; punctuation and spaces removed; digits mapped to 零一二…; script spells numbers in Chinese',
        term_counts={term: dict(script=reference.lower().count(term.lower()), raw=traditional(raw_text).lower().count(term.lower()),
                                corrected=fixed.lower().count(term.lower())) for term in TERMS},
        note='Synthetic zh-TW voice (Windows SAPI Hanhan); not representative of real lecture audio')


def page_index(deck):
    return {page['id']: f'{deck["deck_id"]}:{i+1}' for i, page in enumerate(deck['pages'])}


def visual_report(expected, deck, visual, evidence, decisions):
    pages = page_index(deck)
    scan = read_json(visual/'change-scan.json')
    alignment = read_json(visual/'alignment.json')
    differences = read_json(visual/'differences.json')['events']
    from build_evidence import ordered_decisions
    _, diff_decisions = ordered_decisions(decisions, alignment, {'events': differences})
    runs = alignment['intervals']
    used_scan, used_runs, used_diffs, rows = set(), set(), set(), []
    for event in expected['events']:
        if event['kind'] == 'start':
            continue
        t, after = event['time'], pages[event['page_after']]
        row = dict(id=event['id'], kind=event['kind'], time=t, page_after=after, state_seconds=event['state_seconds'],
                   challenge=bool(event.get('challenge')), label=event.get('label', ''))
        if event['kind'] in PAGE_KINDS:
            # A cut at t first appears in the probe slot ceil(t); allow one extra probe.
            scans = [i for i, e in enumerate(scan['events']) if t <= e['after'] <= t+2]
            run = [i for i, r in enumerate(runs) if t <= r['start'] <= t+2 and r['page_id'] == after]
            row.update(scan_event=[scan['events'][i] for i in scans][:1], run=run[:1],
                       detected=bool(run), latency=(runs[run[0]]['start']-t) if run else None)
            used_scan.update(scans[:1]); used_runs.update(run[:1])
        else:
            hits = [i for i, d in enumerate(differences) if d['before_time'] < t <= d['after_time'] and d['page_id'] == after]
            row.update(difference=[f'D{i+1:02}' for i in hits], detected=bool(hits),
                       reviewed_as=[diff_decisions[i]['decision'] for i in hits],
                       review_matches_kind=all(diff_decisions[i]['decision'] == event['kind'] for i in hits) if hits else None,
                       latency=(differences[hits[0]]['after_time']-t) if hits else None)
            used_diffs.update(hits)
        rows.append(row)
    expected_runs = []
    for state in expected['states']:
        page = pages[state['state']['page']]
        if not expected_runs or expected_runs[-1] != page:
            expected_runs.append(page)
    occurrence_pages = []
    for row in evidence:
        if not occurrence_pages or occurrence_pages[-1] != row['page_id']:
            occurrence_pages.append(row['page_id'])
    main = [r for r in rows if not r['challenge']]
    return dict(
        expected_events=len(rows), main_events=len(main), main_detected=sum(r['detected'] for r in main),
        challenge_events=[r for r in rows if r['challenge']], events=rows,
        missed=[r for r in rows if not r['detected']],
        extra_scan_events=[e for i, e in enumerate(scan['events']) if i not in used_scan],
        extra_page_runs=[r for i, r in enumerate(runs) if i not in used_runs and i],
        extra_difference_events=[f'D{i+1:02}' for i in range(len(differences)) if i not in used_diffs],
        expected_page_sequence=expected_runs, occurrence_page_sequence=occurrence_pages,
        page_sequence_matches=expected_runs == occurrence_pages,
        occurrences=len(evidence), uncertain_observations=sum(o['status'] != 'candidate' for o in alignment['observations']))


def data_checks(job):
    course = job/'course'
    status = read_json(job/'status.json')
    raw = read_json(course/'transcript.json')
    corrected = read_json(course/'transcript.corrected.json')
    evidence = read_json(course/'slide_evidence.json')
    reading = read_json(course/'transcript.reading.json')
    editorial = read_json(course/'editorial_chapters.json')
    media = read_json(job/'media.json')
    checks = {
        'raw_asr_hash_matches_stage_receipt': digest(course/'transcript.json') == status['stages']['transcribe']['artifacts']['course/transcript.json'],
        'editorial_raw_hash_matches': editorial['raw_transcript_sha256'] == digest(course/'transcript.json'),
        'corrected_keeps_count_and_times': len(raw) == len(corrected) and all(
            a['start'] == b['start'] and a['end'] == b['end'] for a, b in zip(raw, corrected)),
        'reading_base_is_current_corrected': reading['base_sha256'] == digest(course/'transcript.corrected.json'),
        'evidence_images_match_hashes': all(digest(course/'slides'/row['image']) == row['image_sha256'] for row in evidence),
        'evidence_covers_video': evidence[0]['start'] == 0 and abs(evidence[-1]['end']-media['duration']) < 1e-6 and all(
            a['end'] == b['start'] for a, b in zip(evidence, evidence[1:])),
        'every_segment_has_one_primary_occurrence': sorted(i for row in evidence for i in row['primary_transcript_ids']) == list(range(len(raw))),
        'editorial_times_within_video': all(0 <= p['time'] <= media['duration'] for c in editorial['chapters'] for p in c['paragraphs']),
        'media_hash_matches': digest(job/'media/lecture.mp4') == media['sha256'],
    }
    return checks


def content_report(baseline, editorial):
    text = editorial['overview'] + '\n' + '\n'.join(p['text'] for c in editorial['chapters'] for p in c['paragraphs'])
    facts = {
        'empty rule': 'front == rear' in text,
        'full rule': '(rear + 1) % N == front' in text,
        'advance formula': '(i + 1) % N' in text,
        'max N - 1': 'N - 1' in text,
        'wrap 4 -> 0': '(4 + 1) % 5 = 0' in text or '5 % 5 = 0' in text,
        'full check (1 + 1) % 5 = 2': '(1 + 1) % 5 = 2' in text,
        'trace front 0->2': 'front 從 0 移到 2' in text,
        'trace rear 3 then 0 then 1': all(s in text for s in ('rear = 3', 'rear 繞回 0', 'rear 前進成 1')),
        'G rejected': '拒絕' in text,
        'count design only mentioned': 'count' in text and '不和它混用' in text,
    }
    return dict(keyword_checks=facts, all_present=all(facts.values()),
                note='Keyword presence is not evidence of a correct or complete explanation; see the teaching-quality review')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--job', type=Path, default=ROOT/'output/jobs/e2e-circular-queue')
    parser.add_argument('--materials', type=Path, default=ROOT/'output/e2e-circular-queue/materials')
    parser.add_argument('--visual', type=Path)
    parser.add_argument('--out', type=Path, default=ROOT/'output/e2e-circular-queue/evaluation')
    args = parser.parse_args(argv)
    job, materials = args.job.resolve(), args.materials.resolve()
    visual = (args.visual or job/'visual-review').resolve()
    expected = read_json(materials/'expected_events.json')
    if expected['video_sha256'] != read_json(job/'job.json')['source_fingerprint']['sha256']:
        raise SystemExit('expected_events.json belongs to a different video than this job')
    course = job/'course'
    evidence = read_json(course/'slide_evidence.json')
    report = dict(
        schema=1,
        asr=asr_report(read_json(materials/'narration_script.json'), read_json(course/'transcript.json'),
                       read_json(course/'transcript.corrected.json')),
        visual=visual_report(expected, read_json(materials/'deck.json'), visual, evidence,
                             read_json(job/'visual-human-review/decisions.json')),
        data=data_checks(job),
        content=content_report(read_json(EXAMPLE/'course/content-baseline.json'), read_json(course/'editorial_chapters.json')))
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_json(args.out/'evaluation.json', report)
    v, a = report['visual'], report['asr']
    lines = ['# 原創範例評估', '', '> 只比較本範例；合成語音結果不代表真實授課錄音。', '',
             '## ASR（對照旁白腳本）', '',
             f'- 參考字數 {a["reference_characters"]}；CER：原始 {a["cer_raw_as_is"]:.1%}、OpenCC 後 {a["cer_raw_after_opencc"]:.1%}、校訂後 {a["cer_corrected"]:.1%}',
             '', '| 詞 | 腳本 | 原始（OpenCC 後） | 校訂 |', '|---|---|---|---|']
    lines += [f'| {k} | {c["script"]} | {c["raw"]} | {c["corrected"]} |' for k, c in a['term_counts'].items()]
    lines += ['', '## 視覺事件', '', f'- 主要事件 {v["main_detected"]}/{v["main_events"]} 被偵測；挑戰事件 {len(v["challenge_events"])} 個',
              f'- 頁面順序（預期）：{" → ".join(v["expected_page_sequence"])}',
              f'- 頁面順序（核對後出現區間）：{" → ".join(v["occurrence_page_sequence"])}',
              f'- 額外換頁事件 {len(v["extra_scan_events"])}、額外頁面區間 {len(v["extra_page_runs"])}、額外差異事件 {len(v["extra_difference_events"])}',
              '', '| 事件 | 類型 | 時間 | 持續 | 偵測 | 依據 | 延遲 |', '|---|---|---|---|---|---|---|']
    for r in v['events']:
        basis = (f'run {r["run"][0]+1}' if r.get('run') else '') or ','.join(r.get('difference', [])) or '—'
        latency = '—' if r['latency'] is None else f'{r["latency"]:+.1f} s'
        lines.append(f'| {r["id"]}{"（挑戰）" if r["challenge"] else ""} | {r["kind"]} | {r["time"]:.1f} | {r["state_seconds"]:.1f} s | '
                     f'{"是" if r["detected"] else "否"} | {basis} | {latency} |')
    lines += ['', '## 資料檢查', ''] + [f'- {k}: {"通過" if ok else "失敗"}' for k, ok in report['data'].items()]
    lines += ['', '## 講義關鍵內容（關鍵字檢查，不等於教學品質）', '']
    lines += [f'- {k}: {"有" if ok else "缺"}' for k, ok in report['content']['keyword_checks'].items()]
    (args.out/'evaluation.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('\n'.join(lines))
    return 0 if all(report['data'].values()) else 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
