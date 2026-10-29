import numpy as np
from scan_slide_changes import change_fraction


def test_short_page_and_return_both_trigger():
    a=np.zeros((224,320),np.uint8);b=a.copy();b[30:180,30:290]=255
    assert change_fraction(a,b)>.025
    assert change_fraction(b,a)>.025
    assert change_fraction(a,a)==0


def test_small_symbol_does_not_imply_unchanged_content():
    a=np.zeros((224,320),np.uint8);b=a.copy();b[100:102,90:100]=255
    assert 0<change_fraction(a,b)<.025  # must be handled by annotation path
