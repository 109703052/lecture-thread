import json
import pytest
from build_reader import load_reading_transcript


def test_reading_layer_preserves_source_and_rejects_stale_mapping(tmp_path):
    source = [{'text': '原句', 'start': 0, 'end': 2}]
    path = tmp_path / 'transcript.reading.json'
    assert load_reading_transcript(path, source, 'rev') == {}
    doc = {'schema': 1, 'base_sha256': 'rev', 'segments': [
        {'segment_id': 0, 'original': '原句', 'text': '原句。', 'paragraph_end': True}]}
    path.write_text(json.dumps(doc), encoding='utf-8')
    assert load_reading_transcript(path, source, 'rev')['0']['text'] == '原句。'
    assert source[0]['text'] == '原句'
    with pytest.raises(ValueError, match='base changed'):
        load_reading_transcript(path, source, 'new')
    doc['segments'][0]['original'] = '不同原句'
    path.write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(ValueError, match='source mapping'):
        load_reading_transcript(path, source, 'rev')
