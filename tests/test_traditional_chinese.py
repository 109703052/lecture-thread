from traditional_chinese import traditional, normalize_transcript
from author_lecture import screen_corrections


def test_traditional_prose_preserves_technical_literals_and_context():
    text = '头发与开发，内存 64 bit，CPU cache。`变量 = "简体"` https://example.com/简体'
    converted = traditional(text)
    assert converted == '頭髮與開發，內存 64 bit，CPU cache。`变量 = "简体"` https://example.com/简体'
    assert traditional(converted) == converted


def test_normalization_is_audited_without_changing_time_or_original():
    tx = [{'text': '这个设备传输数据', 'start': 1, 'end': 3, 'review_note': '数字有疑问'}]
    changes = []
    normalize_transcript(tx, changes)
    assert tx == [{'text': '這個設備傳輸數據', 'start': 1, 'end': 3, 'review_note': '數字有疑問'}]
    assert changes[0]['original'] == '这个设备传输数据'
    assert changes[0]['audio_verified'] is False
    normalize_transcript(tx, changes)
    assert len(changes) == 1


def test_script_only_conversion_is_not_rejected_as_semantic_rewrite():
    tx = [{'text': '这个设备传输数据'}]
    response = {'title': '設備', 'problem': '傳輸', 'lesson': [
        {'heading': '設備傳輸', 'text': '設備傳輸數據', 'source_ids': [0]}],
        'corrections': [{'segment_id': 0, 'text': '這個設備傳輸數據', 'reason': '簡轉繁'}], 'flags': []}
    result = screen_corrections(response, [0], tx, [])
    assert result['corrections'] and not result['flags']
