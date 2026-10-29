import json
import pytest
from bilingual_layer import load_translations
from reading_layer import load_reading_paragraphs


def document():
    return dict(schema=1, source_language='en', target_language='zh-Hant', base_sha256='revision',
                segments=[dict(segment_id=0, start=0, end=3, original='A bit.', text='一個位元。')])


def test_translation_never_replaces_source_and_stale_base_is_hidden(tmp_path):
    path = tmp_path/'translation.json'
    path.write_text(json.dumps(document()), encoding='utf-8')
    source = [dict(start=0, end=3, text='A bit.')]
    assert load_translations(path, source, 'revision')['0']['text'] == '一個位元。'
    assert source[0]['text'] == 'A bit.'
    assert load_translations(path, source, 'new-revision') == {}


@pytest.mark.parametrize('change', [dict(segment_id=1), dict(original='A byte.'), dict(start=1), dict(text='')])
def test_translation_rejects_misaligned_sources(tmp_path, change):
    doc = document()
    doc['segments'][0].update(change)
    path = tmp_path/'translation.json'
    path.write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(ValueError):
        load_translations(path, [dict(start=0, end=3, text='A bit.')], 'revision')


@pytest.mark.parametrize('ids', [[0], [1, 0], []])
def test_chinese_reading_must_preserve_all_source_links(tmp_path, ids):
    source = [dict(start=0, end=1, text='A'), dict(start=1, end=2, text='B')]
    row = dict(source_ids=[0, 1], start=0, end=2, originals=['A', 'B'], text='A and B.',
               text_zh='甲與乙。', sentences_zh=[dict(text='甲與乙。', source_ids=ids)])
    path = tmp_path/'reading.json'
    path.write_text(json.dumps(dict(schema=2, base_sha256='rev', paragraphs=[row])), encoding='utf-8')
    with pytest.raises(ValueError):
        load_reading_paragraphs(path, source, 'rev')
