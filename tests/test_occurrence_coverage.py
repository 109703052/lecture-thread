import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('deliverable',ROOT/'build_cs_deliverable.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_cross_page_segments_assigned_once():
    segments=[{'start':0,'end':4},{'start':8,'end':14},{'start':19,'end':21},{'start':25,'end':30}]
    owners=m.assign_segments(segments,[(0,10),(10,20),(20,30)])
    assert owners==[[0],[1,2],[3]]
    assert sorted(i for ids in owners for i in ids)==list(range(4))

def test_short_revisit_does_not_drop_sentence():
    segments=[{'start':9,'end':14}]
    owners=m.assign_segments(segments,[(0,10),(10,12),(12,20)])
    assert sum(map(len,owners))==1
    assert owners[1]==[0]
