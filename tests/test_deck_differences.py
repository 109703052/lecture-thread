import numpy as np
from deck_differences import regions


def test_added_and_erased_symbol_are_both_reviewed():
    a=np.full((120,160,3),255,np.uint8);b=a.copy();b[50:55,60:85]=0
    count,boxes=regions(a,b)
    assert count>0 and boxes
    assert regions(b,a)[0]==count
    assert regions(a,a)==(0,[])


def test_invalid_warp_border_is_excluded():
    a=np.full((120,160,3),255,np.uint8);b=a.copy();b[:20]=0
    valid=np.ones((120,160),bool);valid[:25]=False
    assert regions(a,b,valid)==(0,[])


def test_one_pixel_minus_is_not_filtered_out():
    a=np.full((120,160,3),255,np.uint8);b=a.copy();b[50,60:75]=0
    assert regions(a,b)[0]==15
    assert regions(b,a)[0]==15


def test_one_pixel_text_shift_is_tolerated():
    a=np.full((120,160,3),255,np.uint8);b=a.copy();a[40:60,50:55]=0;b[40:60,51:56]=0
    assert regions(a,b)==(0,[])


def test_ambiguous_animation_frames_still_get_difference_review(tmp_path):
    import cv2
    from pipeline_common import atomic_json
    from deck_differences import analyze
    a=np.full((120,160,3),255,np.uint8);b=a.copy();b[40:70,50:80]=0
    paths=[tmp_path/'before.png',tmp_path/'after.png']
    for path,array in zip(paths,[a,b]):cv2.imwrite(str(path),array)
    source=tmp_path/'alignment.json'
    atomic_json(source,{'observations':[{'time':i*5,'page_id':None,'image':str(path)} for i,path in enumerate(paths)]})
    result=analyze(source,tmp_path/'differences.json')
    assert len(result['events'])==1 and result['events'][0]['page_id'] is None
