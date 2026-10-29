"""Fill a schema-2 transcript.reading.json from an authored reading draft.

Usage (project root):
  .venv/Scripts/python.exe examples/end-to-end/scripts/build_reading_layer.py --job output/jobs/<id> --draft DRAFT.json

The draft holds only what a person (or an AI assistant under review) writes:
  {"author": "...", "authoring_method": "...",
   "paragraphs": [{"source_ids": [1, 2], "text": "...", "sentences": [{"text": "...", "source_ids": [1]}, ...]}]}
This tool adds the mechanical fields the reader validates (originals copied from
transcript.corrected.json, start/end, base and raw hashes) and runs the same
validation as the reader. It never edits the corrected transcript.
"""
import argparse
from pathlib import Path
import sys

EXAMPLE = Path(__file__).resolve().parents[1]
ROOT = EXAMPLE.parents[1]
sys.path.insert(0, str(ROOT))
from pipeline_common import atomic_json, digest, read_json  # noqa: E402
from reading_layer import load_reading_paragraphs  # noqa: E402


def assemble(draft, corrected, base_sha256, raw_sha256, manual_revision):
    paragraphs = []
    for row in draft['paragraphs']:
        ids = row['source_ids']
        paragraphs.append(dict(source_ids=ids, start=corrected[ids[0]]['start'], end=corrected[ids[-1]]['end'],
                               originals=[corrected[i]['text'] for i in ids], text=row['text'],
                               sentences=row['sentences']))
    return dict(schema=2, author=draft['author'], status='reviewed', base_sha256=base_sha256, raw_sha256=raw_sha256,
                manual_revision=manual_revision, authoring_method=draft['authoring_method'], paragraphs=paragraphs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--draft', type=Path, required=True)
    args = parser.parse_args(argv)
    course = args.job.resolve()/'course'
    corrected = read_json(course/'transcript.corrected.json')
    edits = course/'transcript.manual-edits.json'
    doc = assemble(read_json(args.draft), corrected, digest(course/'transcript.corrected.json'),
                   digest(course/'transcript.json'), digest(edits) if edits.exists() else 'missing')
    target = course/'transcript.reading.json'
    staged = target.with_suffix('.staged.json')
    atomic_json(staged, doc)
    try:
        rows = load_reading_paragraphs(staged, corrected, doc['base_sha256'])  # same checks as the reader
    except ValueError:
        staged.unlink()
        raise
    staged.replace(target)
    print(f'{len(rows)} reading paragraphs, {sum(len(r["sentences"]) for r in rows)} sentences -> {target}')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
