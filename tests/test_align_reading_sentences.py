from align_reading_sentences import align, shift_lead_ins, split_sentences


def test_split_keeps_text_exactly():
    text = '第一句。第二句？「引號」結束。\n尾巴'
    parts = split_sentences(text)
    assert ''.join(parts) == text
    assert parts[:2] == ['第一句。', '第二句？']


def test_alignment_is_monotonic_and_moves_trailing_lead_in_forward():
    sentences = ['Erase 會讓 tunnel oxide 老化。', '負電荷會卡在裡面。']
    originals = ['那Erase會讓Tunnel Oxide老化', '那所以在這邊的話', '負電荷就會卡在裡面']
    rows = align(sentences, originals)
    ranges = shift_lead_ins(sentences, originals, [(a, b) for a, b, _ in rows])
    assert ranges[0][0] == 0 and ranges[-1][1] == 2
    assert ranges == [[0, 0], [1, 2]]
