"""Load separately authored translations without replacing English source text."""
import json


def load_translations(path, transcript, revision):
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding='utf-8'))
    if doc.get('schema') != 1 or doc.get('source_language') != 'en' or doc.get('target_language') != 'zh-Hant':
        raise ValueError('Invalid bilingual transcript schema/languages')
    if doc.get('base_sha256') != revision:
        return {}
    rows = doc.get('segments')
    if not isinstance(rows, list) or len(rows) != len(transcript):
        raise ValueError('Translations must cover every source segment')
    result = {}
    for i, (row, source) in enumerate(zip(rows, transcript)):
        if (type(row.get('segment_id')) is not int or row['segment_id'] != i
                or row.get('original') != source['text']
                or row.get('start') != source['start'] or row.get('end') != source['end']
                or not isinstance(row.get('text'), str) or not row['text'].strip()):
            raise ValueError(f'Invalid translation source mapping at {i}')
        result[str(i)] = row
    return result
