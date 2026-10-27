"""Validate authored reading paragraphs against immutable timed source snapshots."""
import json


def load_reading_paragraphs(path, transcript, revision):
    if not path.is_file():
        return []
    doc = json.loads(path.read_text(encoding='utf-8'))
    if doc.get('schema') != 2:
        return []
    if doc.get('base_sha256') != revision:
        # An updated source must remain readable even before re-authoring.
        return []
    result, covered = [], []
    for row in doc.get('paragraphs', []):
        ids = row.get('source_ids')
        if (not isinstance(ids, list) or not ids
                or any(type(i) is not int or not 0 <= i < len(transcript) for i in ids)
                or ids != list(range(ids[0], ids[-1]+1))
                or row.get('start') != transcript[ids[0]]['start']
                or row.get('end') != transcript[ids[-1]]['end']
                or not isinstance(row.get('text'), str) or not row['text'].strip()
                or not isinstance(row.get('originals'), list)
                or len(row['originals']) != len(ids)
                or any(not isinstance(s, str) for s in row['originals'])):
            raise ValueError('Invalid reading paragraph source mapping')
        covered.extend(ids)
        result.append(row)
    if covered != list(range(len(transcript))):
        raise ValueError('Reading paragraphs must cover every source exactly once')
    return result
