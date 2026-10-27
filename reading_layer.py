"""Validate authored reading paragraphs against immutable timed source snapshots."""
import json


def validate_sentences(sentences, ids, text):
    """Each polished sentence names the contiguous originals it condenses.

    Ranges run in source order and together cover the paragraph, so every
    original stays reachable; adjacent ranges may share one boundary original
    when the speaker's sentence was split.
    """
    if (not isinstance(sentences, list) or not sentences
            or any(not isinstance(s, dict) or not isinstance(s.get('text'), str) or not s['text'].strip()
                   for s in sentences)
            or ''.join(s['text'] for s in sentences) != text):
        raise ValueError('Reading sentences must split the paragraph text exactly')
    expected = ids[0]
    for s in sentences:
        sids = s.get('source_ids')
        if (not isinstance(sids, list) or not sids
                or any(type(i) is not int for i in sids)
                or sids != list(range(sids[0], sids[-1]+1))
                or sids[0] not in (expected - 1, expected) or sids[0] < ids[0]
                or sids[-1] > ids[-1]):
            raise ValueError('Invalid reading sentence source mapping')
        expected = sids[-1] + 1
    if expected != ids[-1] + 1:
        raise ValueError('Reading sentences must cover every original in the paragraph')


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
        if 'sentences' in row:
            validate_sentences(row['sentences'], ids, row['text'])
        covered.extend(ids)
        result.append(row)
    if covered != list(range(len(transcript))):
        raise ValueError('Reading paragraphs must cover every source exactly once')
    return result
