"""Local visual differences within a matched page; never interprets handwriting.

Source observations remain intact. Every nonzero detected difference is recorded;
small components are uncertainty, not evidence that a lecturer changed nothing.
"""
import argparse
from pathlib import Path
import cv2
import numpy as np
from pipeline_common import read_json,atomic_json,digest


def regions(before,after,valid=None):
    # Tolerate one-pixel alignment noise without median-filtering thin new strokes.
    kernel=np.ones((3,3),np.uint8)
    def outside(image,reference):
        lo=cv2.erode(reference,kernel).astype(np.int16)
        hi=cv2.dilate(reference,kernel).astype(np.int16)
        value=image.astype(np.int16)
        return np.any((value<lo-28)|(value>hi+28),axis=2)
    mask=(outside(after,before)|outside(before,after)).astype(np.uint8)
    if valid is not None:mask[~valid]=0
    count=int(mask.sum())
    merged=cv2.dilate(mask,np.ones((7,7),np.uint8))
    n,labels,stats,centroids=cv2.connectedComponentsWithStats(merged,8)
    boxes=[list(map(int,r[:4])) for r in stats[1:]]
    return count,boxes


def plane_source(row,other):
    # Use the shared-decode lossless frames only when both sides have one: a lossy 5 s
    # JPEG compared with a differently scaled seek frame produces codec/scaler noise.
    if other is None or ('comparison_image' in row and 'comparison_image' in other):
        return row.get('comparison_image',row['image'])
    return row['image']


def video_plane(path):
    # Compare consecutive video frames directly. Independently fitting a homography
    # to the deck on every frame introduced artificial movement of printed text.
    # Zoom/pan remains a visible change and must be reviewed, not mistaken for ink.
    image=cv2.imread(path)
    size=(960,2*round(image.shape[0]*960/image.shape[1]/2))
    if (image.shape[1],image.shape[0])!=size:image=cv2.resize(image,size)
    return image,np.ones(image.shape[:2],bool)


def analyze(alignment_path,out,decisions=None):
    cv2.setNumThreads(1)
    alignment=read_json(alignment_path);events=[];previous=None;planes=(None,None)
    overrides=read_json(decisions).get('intervals',[]) if decisions else []
    for original in alignment['observations']:
        row=dict(original)
        for override in overrides:
            if override['start']<=row['time']<override['end']:row['page_id']=override['page_id']
        if previous and row['page_id']==previous['page_id']:
            before,after=plane_source(previous,row),plane_source(row,previous)
            if before!=planes[0]:planes=(before,video_plane(before))
            current=video_plane(after)
            count,boxes=regions(planes[1][0],current[0],planes[1][1]&current[1])
            planes=(after,current)
            if count:
                events.append(dict(page_id=row['page_id'],before_time=previous['time'],after_time=row['time'],
                    before_image=previous['image'],after_image=row['image'],before_compared=before,after_compared=after,
                    changed_pixels=count,boxes_in_video_coordinates=boxes,canvas_size=[current[0].shape[1],current[0].shape[0]],
                    action='Review local changes with page and speech context; no OCR text inferred'))
        previous=row
    result=dict(schema=4,alignment_sha256=digest(alignment_path),observations=len(alignment['observations']),
        events=events,model_calls=0,limitations=['Zoom, pan, overlays and compression can cause differences unrelated to handwriting','One-pixel tolerance can hide changes adjacent to existing strokes; all original observations retained','Coordinates are in960px-wide video plane; not original-image crop coordinates','Pairs compare shared-decode lossless frames when both observations have them; otherwise the matching images (which may mix JPEG and seek frames)','Detected changes are not automatically classified as handwriting or cursor'])
    atomic_json(out,result);print('difference review events',len(events),'/',result['observations'],flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('alignment',type=Path);p.add_argument('out',type=Path);p.add_argument('--decisions',type=Path);a=p.parse_args();analyze(a.alignment,a.out,a.decisions)
