import json
import pytest
from reading_layer import load_reading_paragraphs

def fixture(tmp_path):
    tx=[dict(start=0,end=2,text='a'),dict(start=2,end=3,text='b')]
    row=dict(source_ids=[0,1],start=0,end=3,originals=['edited a','b'],text='polished')
    doc=dict(schema=2,base_sha256='rev',paragraphs=[row])
    return tmp_path/'reading.json',tx,doc

def test_source_revision_change_falls_back(tmp_path):
    path,tx,doc=fixture(tmp_path)
    path.write_text(json.dumps(doc),encoding='utf-8')
    assert load_reading_paragraphs(path,tx,'rev')==doc['paragraphs']
    assert load_reading_paragraphs(path,tx,'new')==[]
    assert tx[0]['text']=='a'

@pytest.mark.parametrize('change',['time','duplicate','missing','order','snapshot','blank'])
def test_rejects_bad_source_mapping(tmp_path,change):
    path,tx,doc=fixture(tmp_path);p=doc['paragraphs'][0]
    if change=='time':p['end']=4
    if change=='duplicate':doc['paragraphs'].append(p.copy())
    if change=='missing':p.update(source_ids=[0],end=2,originals=['a'])
    if change=='order':p['source_ids']=[1,0]
    if change=='snapshot':p['originals']=['a']
    if change=='blank':p['text']=' '
    path.write_text(json.dumps(doc),encoding='utf-8')
    with pytest.raises(ValueError):load_reading_paragraphs(path,tx,'rev')


def with_sentences(doc, sentences):
    doc['paragraphs'][0]['sentences'] = sentences
    return doc


def test_accepts_sentence_map_with_shared_boundary(tmp_path):
    path,tx,doc=fixture(tmp_path)
    with_sentences(doc,[dict(text='pol',source_ids=[0,1]),dict(text='ished',source_ids=[1])])
    path.write_text(json.dumps(doc),encoding='utf-8')
    assert load_reading_paragraphs(path,tx,'rev')[0]['sentences'][1]['source_ids']==[1]


@pytest.mark.parametrize('sentences',[
    [dict(text='polish',source_ids=[0,1])],                              # text not split exactly
    [dict(text='pol',source_ids=[0]),dict(text='ished',source_ids=[0])],  # last original unreachable
    [dict(text='pol',source_ids=[1]),dict(text='ished',source_ids=[0])],  # out of order
    [dict(text='pol',source_ids=[0,2]),dict(text='ished',source_ids=[1])],# outside paragraph / gap
    [dict(text='polished',source_ids=[])],
    [],
])
def test_rejects_bad_sentence_map(tmp_path,sentences):
    path,tx,doc=fixture(tmp_path)
    with_sentences(doc,sentences)
    path.write_text(json.dumps(doc),encoding='utf-8')
    with pytest.raises(ValueError):load_reading_paragraphs(path,tx,'rev')
