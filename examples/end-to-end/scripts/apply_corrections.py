"""Build transcript.corrected.json + transcript.corrections.json from a reviewed plan.

Usage (project root):
  .venv/Scripts/python.exe examples/end-to-end/scripts/apply_corrections.py --job output/jobs/<id> --plan PLAN.json

The plan lists exact replacements per segment, each with its basis. The tool
first applies the project's Traditional Chinese normalization (OpenCC s2tw),
then each replacement; a `find` that is absent fails instead of guessing.
transcript.json (raw ASR) is never written. Segment count, order and times are
kept. Existing manual-edit or reading layers block a rebuild of the base.

Plan format:
  {"schema": 1, "raw_transcript_sha256": "...", "reviewer": "...", "method": "...",
   "corrections": [{"segment_id": 0, "find": "註列", "replace": "佇列", "count": 2,
                    "basis": "narration-script", "reason": "..."}]}
basis: narration-script | slide-text | normalization-fix
"""
import argparse
import copy
from pathlib import Path
import sys

EXAMPLE = Path(__file__).resolve().parents[1]
ROOT = EXAMPLE.parents[1]
sys.path.insert(0, str(ROOT))
from pipeline_common import atomic_json, digest, read_json  # noqa: E402
from traditional_chinese import normalize_transcript  # noqa: E402

BASES = {'narration-script': '合成旁白腳本（本範例的 ground truth）',
         'slide-text': '同時間投影片文字',
         'normalization-fix': '修正字形轉換造成的錯字'}


def apply_plan(raw, plan):
    """Pure: raw ASR + plan -> (corrected transcript, audit rows)."""
    corrected, changes = copy.deepcopy(raw), []
    normalize_transcript(corrected, changes)
    audit = {row['segment_id']: row for row in changes}
    for op in plan['corrections']:
        i = op['segment_id']
        if op['basis'] not in BASES or not op.get('reason', '').strip():
            raise ValueError(f'Segment {i}: correction needs a known basis and a reason')
        text = corrected[i]['text']
        found = text.count(op['find'])
        if found == 0 or found != op.get('count', 1):
            raise ValueError(f'Segment {i}: expected {op.get("count", 1)} × {op["find"]!r}, found {found}')
        corrected[i]['text'] = text.replace(op['find'], op['replace'])
        row = audit.get(i)
        if row is None:
            row = audit[i] = dict(segment_id=i, original=raw[i]['text'], audio_verified=False)
            changes.append(row)
        row.update(corrected=corrected[i]['text'], status='corrected')
        row.setdefault('operations', []).append(dict(find=op['find'], replace=op['replace'], basis=op['basis'],
                                                    basis_label=BASES[op['basis']], reason=op['reason']))
    for row in changes:
        row['start'], row['end'] = raw[row['segment_id']]['start'], raw[row['segment_id']]['end']
        row['verification'] = 'script/slide comparison; not audio-verified'
    changes.sort(key=lambda row: row['segment_id'])
    return corrected, changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args(argv)
    course = args.job.resolve()/'course'
    raw = read_json(course/'transcript.json')
    plan = read_json(args.plan)
    if plan.get('raw_transcript_sha256') != digest(course/'transcript.json'):
        raise SystemExit('The plan was written for a different raw ASR; review the new transcript first')
    for layer in ('transcript.manual-edits.json', 'transcript.reading.json'):
        if (course/layer).exists() and (course/'transcript.corrected.json').exists():
            raise SystemExit(f'{layer} is based on the current corrected transcript; '
                             'rebuilding the base would orphan it. Use a new job or move that layer aside deliberately.')
    corrected, changes = apply_plan(raw, plan)
    atomic_json(course/'transcript.corrected.json', corrected)
    atomic_json(course/'transcript.corrections.json', changes)
    atomic_json(course/'transcript.corrections.provenance.json', dict(
        schema=1, plan=str(args.plan.resolve()), plan_sha256=digest(args.plan), reviewer=plan.get('reviewer'),
        method=plan.get('method'), raw_transcript_sha256=digest(course/'transcript.json'),
        corrected_sha256=digest(course/'transcript.corrected.json'), audio_verified=False))
    edited = sum(row['status'] == 'corrected' for row in changes)
    print(f'{len(corrected)} segments; {edited} corrected, {len(changes)-edited} normalization-only; '
          f'corrected sha256 {digest(course/"transcript.corrected.json")}')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
