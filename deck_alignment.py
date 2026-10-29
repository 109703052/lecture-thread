"""Deck-assisted visual candidates. No OCR, inference, or production evidence writes.

Each video observation remains separate. Cached identical pixels share only analysis.
Ambiguous pages are never resolved by a monotonic slide-order assumption.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import zipfile

from pipeline_common import atomic_json, digest, read_json, replace_with_retry
from frame_cache import frame_manifest, validate_frame_cache

VERSION = 2


def decide(candidates):
    if not candidates or candidates[0]['inliers'] < 40:
        return 'unmatched', None
    best = candidates[0]['inliers']
    second = candidates[1]['inliers'] if len(candidates) > 1 else 0
    if best - second < max(20, best * .15):
        return 'ambiguous', None
    return 'candidate', candidates[0]['page_id']


def intervals(observations, duration):
    """Candidate intervals preserve returns and unknowns, not exact cut times."""
    runs = []
    for row in observations:
        key = (row['status'], row['page_id'])
        if runs and (runs[-1]['status'], runs[-1]['page_id']) == key:
            runs[-1]['observations'] += 1
            runs[-1]['last_observed'] = row['time']
        else:
            if runs:
                runs[-1]['end'] = row['time']
            runs.append(dict(start=row['time'], end=duration,
                             last_observed=row['time'], status=key[0],
                             page_id=key[1], observations=1))
    return runs


FEATURE_VERSION = 1
ORB_FEATURES = 1200
RENDER_WIDTH = 960


def feature_signature(ref):
    """Everything that can change page features; any difference rebuilds them."""
    import cv2
    import pymupdf
    return dict(schema=FEATURE_VERSION, algorithm='ORB', nfeatures=ORB_FEATURES,
                render_width=RENDER_WIDTH, colorspace='gray', deck_id=ref['deck_id'],
                source_sha256=ref['source_sha256'], render_sha256=ref['render_sha256'],
                slide_count=ref['slide_count'], opencv=cv2.__version__,
                pymupdf=[pymupdf.VersionBind, pymupdf.VersionFitz])


def _payload_sha256(arrays):
    h = hashlib.sha256()
    for name in sorted(arrays):
        h.update(name.encode()+str(arrays[name].shape).encode()+arrays[name].tobytes())
    return h.hexdigest()


def load_features(folder, signature):
    """Return (key, [(keypoint rows, descriptors)] or None); damaged/foreign files rebuild."""
    import numpy as np
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    path = Path(folder)/(key+'.npz')
    if not path.exists():
        return key, None
    try:
        with np.load(path, allow_pickle=False) as saved:
            arrays = {name: saved[name] for name in saved.files if name != 'meta'}
            meta = json.loads(str(saved['meta']))
        if meta['signature'] != signature or meta['payload_sha256'] != _payload_sha256(arrays):
            return key, None
        return key, [(arrays[f'k{i}'], arrays[f'd{i}'] if meta['descriptors'][i] else None)
                     for i in range(signature['slide_count'])]
    except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile):
        return key, None


def save_features(folder, key, signature, pages):
    import numpy as np
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    arrays = {}
    for i, (rows, d) in enumerate(pages):
        arrays[f'k{i}'] = rows
        arrays[f'd{i}'] = d if d is not None else np.zeros((0, 32), np.uint8)
    meta = dict(signature=signature, payload_sha256=_payload_sha256(arrays),
                descriptors=[d is not None for _, d in pages])
    fd, name = tempfile.mkstemp(prefix=key+'.', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as stream:
            np.savez(stream, meta=np.array(json.dumps(meta)), **arrays)
        replace_with_retry(name, folder/(key+'.npz'))
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Matcher:
    def __init__(self, references, feature_cache=None):
        import cv2
        import numpy as np
        import pymupdf
        self.cv2, self.np = cv2, np
        cv2.setNumThreads(1)
        cv2.setRNGSeed(7)
        self.orb = cv2.ORB_create(nfeatures=ORB_FEATURES)
        self.bf = cv2.BFMatcher(cv2.NORM_HAMMING)
        self.pages = []
        self.pages_computed = self.pages_loaded = 0
        for ref in references:
            signature = feature_signature(ref)
            key, saved = load_features(feature_cache, signature) if feature_cache else (None, None)
            if saved is None:
                saved = []
                with pymupdf.open(ref['render_pdf']) as doc:
                    if len(doc) != ref['slide_count']:
                        raise ValueError('Rendered page count differs from source')
                    for page in doc:
                        pix = page.get_pixmap(matrix=pymupdf.Matrix(RENDER_WIDTH/page.rect.width,RENDER_WIDTH/page.rect.width), colorspace=pymupdf.csGRAY)
                        array = np.frombuffer(pix.samples, np.uint8).reshape(pix.height,pix.width)
                        k, d = self.orb.detectAndCompute(array, None)
                        # KeyPoint fields are float32/int; float64 rows round-trip them exactly.
                        rows = np.array([(p.pt[0],p.pt[1],p.size,p.angle,p.response,p.octave,p.class_id) for p in k],np.float64).reshape(-1,7)
                        saved.append((rows, d))
                self.pages_computed += len(saved)
                if feature_cache:
                    save_features(feature_cache, key, signature, saved)
            else:
                self.pages_loaded += len(saved)
            for i, (rows, d) in enumerate(saved):
                k = tuple(cv2.KeyPoint(float(x),float(y),float(size),float(angle),float(response),int(octave),int(class_id))
                          for x,y,size,angle,response,octave,class_id in rows)
                self.pages.append((ref['deck_id']+':'+str(i+1), k, d))
        self.search = cv2.FlannBasedMatcher(dict(algorithm=6,table_number=6,key_size=12,multi_probe_level=1),dict(checks=32))
        self.index_pages = [i for i,(_,_,d) in enumerate(self.pages) if d is not None and len(d)>=2]
        self.search.add([self.pages[i][2] for i in self.index_pages]);self.search.train()

    def analyze(self, path, exhaustive=False):
        cv2, np = self.cv2, self.np
        a = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if a is None:
            raise ValueError('Cannot read image: '+str(path))
        a = cv2.resize(a, (960, round(a.shape[0]*960/a.shape[1])))
        k, d = self.orb.detectAndCompute(a, None)
        scores = []
        if d is None:
            return []
        votes = {}
        for matches in self.search.knnMatch(d,k=5):
            for m in matches:
                if m.distance<65:
                    idx=self.index_pages[m.imgIdx]
                    votes[idx]=votes.get(idx,0)+1/(m.distance+8)
        shortlist=sorted(votes,key=votes.get,reverse=True)[:10]
        selected=range(len(self.pages)) if exhaustive else shortlist
        for idx in selected:
            page_id,k2,d2=self.pages[idx]
            if d2 is None or len(d2)<2:
                continue
            pairs = self.bf.knnMatch(d, d2, k=2)
            good = [m for pair in pairs if len(pair)==2 for m,n in [pair] if m.distance < .75*n.distance]
            count, transform = 0, None
            if len(good) >= 8:
                src = np.float32([k[m.queryIdx].pt for m in good])
                dst = np.float32([k2[m.trainIdx].pt for m in good])
                h, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
                if mask is not None and h is not None and np.isfinite(h).all():
                    count = int(mask.sum())
                    transform = h.tolist()
            scores.append(dict(page_id=page_id,inliers=count,transform=transform))
        return sorted(scores,key=lambda x:(-x['inliers'],x['page_id']))[:4]


class SharedMatcher:
    """One deck index per run, built only when an uncached frame needs analysis."""
    def __init__(self, references, feature_cache=None):
        self.references, self.feature_cache = references, feature_cache
        self.matcher, self.builds = None, 0

    def __call__(self):
        if self.matcher is None:
            self.matcher = Matcher(self.references, self.feature_cache)
            self.builds += 1
        return self.matcher

    def stats(self):
        m = self.matcher
        return dict(matcher_builds=self.builds, pages_computed=m.pages_computed if m else 0,
                    pages_loaded=m.pages_loaded if m else 0)


def run(course, reference_file, out, interval=5, existing=False, frame_cache=None,
        matcher=None, feature_cache=None, references_verified=False):
    course, out = Path(course), Path(out)
    out.mkdir(parents=True,exist_ok=True)
    refs = read_json(reference_file)
    for ref in () if references_verified else refs:
        if digest(ref['source']) != ref['source_sha256'] or digest(ref['render_pdf']) != ref['render_sha256']:
            raise ValueError('Reference changed; rebuild registry first')
    media = read_json(course/'media.json')
    fingerprint = dict(version=VERSION,reference_sha256=digest(reference_file),
                       media_sha256=media['sha256'],interval=interval,existing=existing)
    stamp = out/'input.json'
    if stamp.exists() and read_json(stamp) != fingerprint:
        raise ValueError('Output belongs to different inputs; select a new output directory')
    atomic_json(stamp,fingerprint)
    if existing:
        inputs = [(r['first_ts'],course/'course/slides'/r['filename']) for r in read_json(course/'course/slides/timestamps.json')]
    else:
        frame_dir=out/'frames'
        if frame_cache:
            prior=read_json(Path(frame_cache)/'extraction.json')
            if prior['media_sha256']!=media['sha256'] or prior['interval']!=interval or prior.get('width',960)!=960:
                raise ValueError('Frame cache belongs to different video or interval')
            frame_dir=Path(frame_cache)/'frames'
        else:
            frame_dir.mkdir(exist_ok=True)
        if not frame_cache and not (out/'extraction.json').exists():
            subprocess.run(['ffmpeg','-v','error','-y','-i',str(course/'media/lecture.mp4'),'-vf',f'fps=1/{interval}:round=up,scale=960:-2','-q:v','2',str(frame_dir/'frame-%06d.jpg')],check=True)
            atomic_json(out/'extraction.json',dict(fingerprint, **frame_manifest(frame_dir)))
        receipt = read_json((Path(frame_cache) if frame_cache else out)/'extraction.json')
        paths = validate_frame_cache(frame_dir, receipt)
        inputs=[((int(p.stem.split('-')[1])-1)*interval,p) for p in paths
                if (int(p.stem.split('-')[1])-1)*interval<media['duration']]
    if not inputs:
        raise ValueError('No observations')
    checkpoint=out/'analysis.jsonl';cache={}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            try:r=json.loads(line)
            except json.JSONDecodeError:continue  # interrupted final append is recomputed
            cache[r['image_sha256']]=r['candidates']
    # A fully cached resume never rasterizes the deck or builds the index.
    matcher=matcher or SharedMatcher(refs,feature_cache);observations=[];start=time.monotonic()
    with checkpoint.open('a',encoding='utf-8') as stream:
        for i,(at,path) in enumerate(inputs):
            key=digest(path)
            if key not in cache:
                cache[key]=matcher().analyze(path)
                stream.write(json.dumps(dict(image_sha256=key,candidates=cache[key]))+'\n');stream.flush()
            status,page=decide(cache[key])
            observations.append(dict(time=at,image=str(path.resolve()),image_sha256=key,status=status,page_id=page,candidates=cache[key]))
            if (i+1)%50==0 or i+1==len(inputs):
                progress=dict(completed=i+1,total=len(inputs),seconds=round(time.monotonic()-start,1))
                atomic_json(out/'progress.json',progress);print(progress,flush=True)
    result=dict(schema=VERSION,inputs=fingerprint,duration=media['duration'],observations=observations,
                intervals=intervals(observations,media['duration']),
                limitations=['Candidate page IDs require validation','Boundaries are observation times, not exact cuts','Animations and handwriting are not replaced by final deck render'])
    atomic_json(out/'alignment.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--course',type=Path,required=True);p.add_argument('--references',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--interval',type=int,default=5)
    p.add_argument('--frame-cache',type=Path);p.add_argument('--feature-cache',type=Path)
    p.add_argument('--existing',action='store_true');a=p.parse_args()
    if a.interval<1:p.error('interval must be positive')
    run(a.course,a.references,a.out,a.interval,a.existing,a.frame_cache,feature_cache=a.feature_cache)
