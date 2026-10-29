"""Turn reviewed visual candidates into the course evidence that editorial_publish.py reads.

Usage (project root):
  .venv/Scripts/python.exe examples/end-to-end/scripts/build_evidence.py --job output/jobs/<id>
      --references REFS [--visual DIR] [--decisions FILE] [--title TEXT] [--description TEXT]

Inputs: the `lecture.cmd visual` output and a filled decisions.json from
review_visual.py (no "pending"; bound to the alignment/difference hashes).
Writes, in <job>/course/: slide_evidence.json (one occurrence per reviewed page
run, split at every accepted reveal/annotation/erasure), slides/occ-*.png,
visual_provenance.json; and <job>/course.reader.json for the reader.

Occurrences are never merged: a revisit or a detour is its own occurrence. The
expected-event ground truth is not an input.
"""
import argparse
from pathlib import Path
import shutil
import sys

EXAMPLE = Path(__file__).resolve().parents[1]
ROOT = EXAMPLE.parents[1]
sys.path.insert(0, str(ROOT))
from build_cs_deliverable import assign_segments  # noqa: E402
from pipeline_common import atomic_json, digest, read_json  # noqa: E402
from review_visual import DIFF_DECISIONS, RUN_DECISIONS  # noqa: E402


def ordered_decisions(decisions, alignment, differences):
    """Resolve review rows by immutable IDs and verify their source metadata."""
    ordered = []
    for key, prefix, sources in (('runs', 'R', alignment['intervals']),
                                  ('differences', 'D', differences['events'])):
        rows = decisions[key]
        ids = [row.get('id') for row in rows]
        expected = [f'{prefix}{i+1:02}' for i in range(len(sources))]
        if len(ids) != len(set(ids)) or set(ids) != set(expected):
            raise ValueError(f'{key}: duplicate, missing or unknown decision IDs')
        by_id = {row['id']: row for row in rows}
        result = [by_id[i] for i in expected]
        for source, row in zip(sources, result):
            fields = ({'start': 'start', 'last_observed': 'last_observed',
                       'candidate_page': 'page_id', 'status': 'status'} if key == 'runs'
                      else {'page_id': 'page_id', 'before_time': 'before_time', 'after_time': 'after_time'})
            if any(field not in row or row[field] != source[target] for field, target in fields.items()):
                raise ValueError(f'{row["id"]}: source metadata differs; rebuild the review packet')
        ordered.append(result)
    return tuple(ordered)


def check_decisions(decisions, alignment, differences, visual):
    if decisions.get('alignment_sha256') != digest(visual/'alignment.json') or \
            decisions.get('differences_sha256') != digest(visual/'differences.json'):
        raise ValueError('decisions.json was made for a different visual output; rebuild the review packet')
    if not decisions.get('reviewer', '').strip() or not decisions.get('method', '').strip():
        raise ValueError('decisions.json must name the reviewer and the review method')
    if len(decisions['runs']) != len(alignment['intervals']) or len(decisions['differences']) != len(differences['events']):
        raise ValueError('decisions.json must contain every run and difference event')
    run_rows, diff_rows = ordered_decisions(decisions, alignment, differences)
    for row in run_rows:
        if row['decision'] not in RUN_DECISIONS:
            raise ValueError(f'{row["id"]}: decision must be one of {RUN_DECISIONS}')
        if row['decision'] == 'split':
            raise ValueError(f'{row["id"]}: split runs need an explicit difference decision; not supported here')
        if row['decision'] != 'noise' and not row.get('page_id'):
            raise ValueError(f'{row["id"]}: a confirmed or corrected run needs page_id')
    for row in diff_rows:
        if row['decision'] not in DIFF_DECISIONS:
            raise ValueError(f'{row["id"]}: decision must be one of {DIFF_DECISIONS}')
        if row['decision'] != 'noise' and not row.get('meaning', '').strip():
            raise ValueError(f'{row["id"]}: describe what changed in "meaning"')


def frame_for(time, visual, alignment):
    """Prefer the full-resolution decoded frame; else the lossless 960 px comparison frame."""
    full = visual/'source-frames'/f'{float(time):.6f}.png'
    if full.is_file():
        return full, 'full-resolution frame decoded at this time'
    row = next(r for r in alignment['observations'] if r['time'] == time)
    if row.get('comparison_image'):
        return Path(row['comparison_image']), '960 px lossless comparison frame from the shared decode'
    return Path(row['image']), '5 s base sample (JPEG)'


def plan_occurrences(alignment, differences, decisions, duration):
    """Pure: reviewed runs + accepted differences -> ordered occurrence boundaries."""
    run_rows, diff_rows = ordered_decisions(decisions, alignment, differences)
    if any(row['decision'] == 'noise' for row in run_rows):
        raise ValueError('Noise runs cannot be published: preserve their intervals for review; '
                         'non-slide evidence is not supported by this example bridge')
    runs = list(zip(alignment['intervals'], run_rows))
    occurrences, seen = [], set()
    for index, (run, row) in enumerate(runs):
        page = row['page_id']
        kind = 'start' if index == 0 else 'revisit' if page in seen else 'page_change'
        occurrences.append(dict(start=run['start'], page_id=page, change=kind, run=row['id'],
                                timing='page boundary between 1 fps probes (about ±1 s)' if index else 'video start'))
        seen.add(page)
        end = runs[index+1][0]['start'] if index+1 < len(runs) else duration
        for event, decision in zip(differences['events'], diff_rows):
            if decision['decision'] == 'noise' or not run['start'] < event['after_time'] < end:
                continue
            if event['page_id'] != run['page_id']:
                raise ValueError(f'{decision["id"]} lies in {row["id"]} but compares another page')
            occurrences.append(dict(start=event['after_time'], page_id=page, change=decision['decision'],
                                    run=row['id'], difference=decision['id'], meaning=decision['meaning'],
                                    timing=f'change happened after {event["before_time"]} s and was observed at '
                                           f'{event["after_time"]} s (5 s samples)'))
    occurrences.sort(key=lambda row: row['start'])
    for i, row in enumerate(occurrences):
        row['end'] = occurrences[i+1]['start'] if i+1 < len(occurrences) else duration
        if not row['start'] < row['end']:
            raise ValueError('Occurrence boundaries must increase')
    return occurrences


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--visual', type=Path)
    parser.add_argument('--decisions', type=Path)
    parser.add_argument('--references', type=Path, required=True, help='references.json given to lecture.cmd visual')
    parser.add_argument('--id', help='Reader course id (default: job id)')
    parser.add_argument('--title', default='循環佇列：如何分辨空與滿（原創端到端範例）')
    parser.add_argument('--description', default='原創端到端範例。旁白為 Windows 內建合成語音（Microsoft Hanhan），'
                        '不是真人授課；逐字稿為語音辨識結果，另以旁白腳本校訂。')
    args = parser.parse_args(argv)
    job = args.job.resolve()
    visual = (args.visual or job/'visual-review').resolve()
    decisions_path = (args.decisions or job/'visual-human-review/decisions.json').resolve()
    course = job/'course'
    alignment, differences = read_json(visual/'alignment.json'), read_json(visual/'differences.json')
    decisions = read_json(decisions_path)
    if digest(args.references) != read_json(visual/'inputs.json')['references_sha256']:
        raise ValueError('--references is not the registry this visual output was built from')
    refs = read_json(args.references)
    check_decisions(decisions, alignment, differences, visual)
    media = read_json(job/'media.json')
    transcript = read_json(course/'transcript.json')
    raw_sha = digest(course/'transcript.json')
    baselines = {row['page_id']: row for row in read_json(visual/'page-baselines.json')}
    ocr = read_json(visual/'region-ocr.json') if (visual/'region-ocr.json').exists() else None
    occurrences = plan_occurrences(alignment, differences, decisions, media['duration'])
    owners = assign_segments(transcript, [(row['start'], row['end']) for row in occurrences])
    slides = course/'slides'
    slides.mkdir(exist_ok=True)
    evidence = []
    for i, (row, primary) in enumerate(zip(occurrences, owners)):
        source, origin = frame_for(row['start'], visual, alignment)
        name = f'occ-{i+1:02}-{float(row["start"]):07.2f}s{source.suffix}'
        shutil.copyfile(source, slides/name)
        text = baselines[row['page_id']]['text']
        clues = []
        if ocr and row.get('difference'):
            index = int(row['difference'][1:])-1
            clues = [region['text'] for region in ocr['events'][index]['after']['regions']]
        evidence.append(dict(
            occurrence_id=i+1, start=row['start'], end=row['end'], image=name, image_origin=origin,
            image_sha256=digest(slides/name), page_id=row['page_id'],
            title=next(line for line in text.splitlines() if line.strip()),
            visual_change=row['change'], visual_change_meaning=row.get('meaning', ''),
            review_run=row['run'], review_difference=row.get('difference'),
            deck_text_layer=text, deck_text_note='Rendered PDF text layer: final deck state, may include unrevealed lines',
            region_ocr_clues=clues, primary_transcript_ids=primary,
            overlapping_transcript_ids=[j for j, s in enumerate(transcript) if s['start'] < row['end'] and s['end'] > row['start']],
            timing_precision=row['timing']))
    atomic_json(course/'slide_evidence.json', evidence)
    atomic_json(course/'visual_provenance.json', dict(
        schema=1,
        method=('lecture.cmd visual (deck alignment on 5 s samples, 1 fps change probes, full-resolution boundaries, '
                'local differences, CPU region OCR) followed by a recorded human review (decisions.json). '
                'No VLM inference. Region OCR is a clue only.'),
        alignment_sha256=digest(visual/'alignment.json'), differences_sha256=digest(visual/'differences.json'),
        region_ocr_sha256=digest(visual/'region-ocr.json') if ocr else None,
        decisions=str(decisions_path), decisions_sha256=digest(decisions_path), reviewer=decisions['reviewer'],
        references=refs, total_occurrences=len(evidence),
        protected_inputs={'transcript.json': raw_sha}, slide_evidence_sha256=digest(course/'slide_evidence.json')))
    manifest = job/'course.reader.json'
    atomic_json(manifest, dict(schema=1, id=args.id or job.name, title=args.title, description=args.description,
                               course_dir='course', web_root='.', output_html='index.html',
                               media='media/lecture.mp4', media_kind='video', youtube_id=''))
    print(f'{len(evidence)} occurrences -> {course/"slide_evidence.json"}\nReader manifest: {manifest}')
    for row in evidence:
        print(f'  {row["occurrence_id"]:02} {row["start"]:>7} {row["page_id"]} {row["visual_change"]:<16} '
              f'ASR {row["primary_transcript_ids"][:1]}..{row["primary_transcript_ids"][-1:]}')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
