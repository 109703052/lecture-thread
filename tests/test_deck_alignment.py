from deck_alignment import decide, intervals


def test_similar_animation_pages_are_not_forced():
    assert decide([{'page_id':'ch2:30','inliers':205},{'page_id':'ch2:31','inliers':205}])==('ambiguous',None)


def test_blank_or_weak_match_stays_unknown():
    assert decide([])==('unmatched',None)
    assert decide([{'page_id':'ch1:1','inliers':12}])==('unmatched',None)


def test_page_revisit_is_separate_and_unknown_retained():
    rows=[dict(time=t,status='candidate' if page else 'unmatched',page_id=page) for t,page in [(0,'a'),(5,'a'),(10,'b'),(15,None),(20,'a')]]
    result=intervals(rows,23)
    assert [(r['start'],r['end'],r['page_id']) for r in result]==[(0,10,'a'),(10,15,'b'),(15,20,None),(20,23,'a')]
    assert sum(r['observations'] for r in result)==5


def test_clear_page_match_is_only_a_candidate():
    assert decide([{'page_id':'ch1:13','inliers':674},{'page_id':'ch2:18','inliers':32}])==('candidate','ch1:13')


def test_legacy_worker_cannot_overwrite_deck_evidence(tmp_path):
    import pytest
    from lecture_pipeline import Worker
    worker=object.__new__(Worker);worker.course=tmp_path
    (tmp_path/'visual_provenance.json').write_text('{}')
    with pytest.raises(ValueError,match='獨立視覺證據'):
        worker.run()
    with pytest.raises(ValueError,match='獨立視覺證據'):
        worker.stage('ocr',lambda:pytest.fail('must not invoke OCR'))
