"""Deck-assisted candidate workflow; writes only a separate review workspace.

Never promotes candidate mappings or OCR guesses into published course evidence.
"""
import argparse
from collections import OrderedDict
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time as clock

from pipeline_common import atomic_json, digest, read_json, replace_with_retry

ROOT = Path(__file__).resolve().parent
CROP_VERSION = 1
CROP_PADDING = 12


def crop_receipt_checksum(saved):
    payload = {key: saved[key] for key in ('identity', 'image_sha256', 'pixel_sha256')}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class RunFacts:
    """Per-run memo of file hashes and a few decoded source frames; RAM stays bounded."""
    def __init__(self, max_images=2):
        self.digests, self.sizes, self.images = {}, {}, OrderedDict()
        self.max_images, self.image_decodes = max_images, 0

    def digest(self, path):
        path = Path(path)
        stat = path.stat()
        key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        if key not in self.digests:
            self.digests[key] = digest(path)
        return self.digests[key]

    def size(self, path):
        from PIL import Image
        key = (str(Path(path).resolve()), self.digest(path))
        if key not in self.sizes:
            with Image.open(path) as image:  # header only
                self.sizes[key] = image.size
        return self.sizes[key]

    def image(self, path):
        from PIL import Image
        key = (str(Path(path).resolve()), self.digest(path))
        if key in self.images:
            self.images.move_to_end(key)
            return self.images[key]
        with Image.open(path) as source:
            source.load()
            image = source.copy()
        self.image_decodes += 1
        self.images[key] = image
        while len(self.images) > self.max_images:
            self.images.popitem(last=False)
        return image


def bind_inputs(out, signature):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = out/'inputs.json'
    if stamp.exists() and read_json(stamp) != signature:
        raise ValueError('Visual inputs changed; select a new --out directory')
    if not stamp.exists() and any(out.iterdir()):
        raise ValueError('Visual output must be empty or belong to this workflow')
    atomic_json(stamp, signature)


def boundary_times(events, duration, last_probe=None):
    # The final probe covers changes after the last base sample (the video tail).
    tail = () if last_probe is None else (last_probe,)
    return sorted({t for event in events for t in
                   (event['before'], event['after'], event['after']+1)
                   if 0 <= t < duration} | {t for t in tail if 0 <= t < duration})


def attach_comparison(rows, decoded, changes, interval):
    """Give every observation its lossless frame from the shared decode (same scaler, PNG).

    Matching keeps its own image (5 s JPEG or full-resolution seek); differences use only
    these, so encoding/scaling paths never differ inside one comparison. Fail closed when a
    slot is missing instead of silently falling back to mixed sources."""
    from scan_slide_changes import comparison_name, comparison_slots
    manifest = read_json(decoded/'extraction.json')['comparison']['frame_sha256']
    slots = comparison_slots(changes['events'], changes['probes'], interval)
    for row in rows:
        slot = row['time']
        name = comparison_name(slot) if type(slot) is int else None
        if slot not in slots or name not in manifest:
            raise ValueError(f'No comparison frame for observation at {slot}s; use a new output directory')
        row.update(comparison_image=str((decoded/'compare'/name).resolve()),
                   comparison_sha256=manifest[name], comparison_slot=slot)


def source_frame(capture, time, out, facts=None, stats=None):
    import cv2
    facts = facts or RunFacts()
    stats = {} if stats is None else stats
    path = Path(out)/f'{time:.6f}.png'
    receipt = path.with_suffix('.json')
    if path.exists() and receipt.exists():
        saved = read_json(receipt)
        if saved['time'] == time and saved['sha256'] == facts.digest(path):
            stats['source_frames_reused'] = stats.get('source_frames_reused', 0)+1
            return path
    stats['source_frames_decoded'] = stats.get('source_frames_decoded', 0)+1
    capture.set(cv2.CAP_PROP_POS_MSEC, time*1000)
    ok, frame = capture.read()
    actual = capture.get(cv2.CAP_PROP_POS_MSEC)/1000
    if not ok or abs(actual-time) > .2:
        raise RuntimeError(f'Cannot decode frame near {time}; decoded {actual}')
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), frame):
        raise OSError(f'Cannot write {path}')
    atomic_json(receipt, dict(time=time, decoded_time=actual, sha256=facts.digest(path)))
    return path


def crop_box(box, canvas, size, padding=CROP_PADDING):
    """Map 960px review coordinates back to full-resolution source pixels."""
    x, y, w, h = box
    cw, ch = canvas
    width, height = size
    if min(cw, ch, w, h) <= 0:
        raise ValueError('Invalid region dimensions')
    return (max(0, math.floor((x-padding)*width/cw)),
            max(0, math.floor((y-padding)*height/ch)),
            min(width, math.ceil((x+w+padding)*width/cw)),
            min(height, math.ceil((y+h+padding)*height/ch)))


def crop_artifact(source, source_sha256, bounds, box, canvas, folder, facts, stats):
    """Content-addressed crop: identical source pixels + region + mapping reuse one file."""
    from ocr_cache import pixel_identity
    identity = dict(version=CROP_VERSION, source_sha256=source_sha256, source_box=list(bounds),
                    video_box=list(box), canvas_size=list(canvas), padding=CROP_PADDING)
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    path = Path(folder)/f'{key}.png'
    receipt = path.with_suffix('.json')
    if path.exists() and receipt.exists():
        try:
            saved = read_json(receipt)
            if (saved['identity'] == identity and saved['image_sha256'] == facts.digest(path)
                    and saved['receipt_sha256'] == crop_receipt_checksum(saved)):
                stats['crops_reused'] = stats.get('crops_reused', 0)+1
                return path, saved
        except (ValueError, KeyError, TypeError):
            pass  # damaged receipt: rebuild from the source frame
    crop = facts.image(source).crop(bounds)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=key+'.', suffix='.png', dir=path.parent)
    os.close(fd)
    try:
        crop.save(name, format='PNG')
        replace_with_retry(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    # PNG is lossless, so in-memory pixels equal what OCRCache would decode from the file.
    saved = dict(identity=identity, image_sha256=facts.digest(path), pixel_sha256=pixel_identity(crop))
    saved['receipt_sha256'] = crop_receipt_checksum(saved)
    atomic_json(receipt, saved)
    stats['crops_written'] = stats.get('crops_written', 0)+1
    return path, saved


def recognize_regions(events, capture, out, cache, recognize, facts=None, stats=None):
    facts = facts or RunFacts()
    stats = {} if stats is None else stats
    rows = []
    for index, event in enumerate(events):
        sides = {}
        for side in ('before', 'after'):
            path = source_frame(capture, event[side+'_time'], out/'source-frames', facts=facts, stats=stats)
            source_sha256 = facts.digest(path)
            crops = []
            for box in event['boxes_in_video_coordinates']:
                bounds = crop_box(box, event['canvas_size'], facts.size(path))
                if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                    raise ValueError('Region lies outside source image')
                crop, saved = crop_artifact(path, source_sha256, bounds, box, event['canvas_size'],
                                            out/'crops', facts, stats)
                text, confidence, boxes, error = cache.recognize(crop, recognize, identity=saved['pixel_sha256'])
                crops.append(dict(image=str(crop.resolve()), image_sha256=saved['image_sha256'],
                    source_box=list(bounds), padding=CROP_PADDING, text=text, confidence=confidence, error=error))
            sides[side] = dict(time=event[side+'_time'], source=str(path.resolve()),
                               source_sha256=source_sha256, regions=crops)
        rows.append(dict(page_id=event['page_id'], **sides,
                         status='unverified OCR clues; compare both sides and speech'))
        atomic_json(out/'region-ocr.json', dict(schema=1, events=rows, complete=False))
    result = dict(schema=1, events=rows, complete=True, cache_hits=cache.hits,
                  cache_misses=cache.misses, limitations=[
                      'OCR may miss handwriting, formulas and tiny symbols',
                      'Empty OCR does not mean no meaningful change',
                      'Changes may be erasures, cursor motion or animation; human review required'])
    atomic_json(out/'region-ocr.json', result)
    return result


def run(job, references, out, *, ocr_regions=False, feature_cache=None):
    import cv2
    import pymupdf
    from deck_alignment import run as align, SharedMatcher, decide, intervals
    from deck_differences import analyze
    from scan_slide_changes import scan

    job, references, out = Path(job).resolve(), Path(references).resolve(), Path(out).resolve()
    video = job/'media/lecture.mp4'
    media = read_json(job/'media.json')
    if digest(video) != media['sha256']:
        raise ValueError('Video differs from media.json')
    refs = read_json(references)
    for ref in refs:
        if digest(ref['source']) != ref['source_sha256'] or digest(ref['render_pdf']) != ref['render_sha256']:
            raise ValueError('Reference changed; rebuild registry')
    signature = dict(schema=1, video_sha256=media['sha256'], references_sha256=digest(references),
                     code={p: digest(Path(__file__).parent/p) for p in
                           ('visual_pipeline.py', 'deck_alignment.py', 'deck_differences.py', 'scan_slide_changes.py',
                            'ocr_cache.py', 'frame_cache.py')})
    bind_inputs(out, signature)
    atomic_json(out/'status.json', dict(state='running', ocr_regions=ocr_regions))
    # Deck features are keyed by deck/render hashes and settings, so a shared cache is safe.
    feature_cache = Path(feature_cache or ROOT/'data/cache/deck-features')
    shared = SharedMatcher(refs, feature_cache)
    facts, stats, seconds = RunFacts(), {}, {}
    started = clock.perf_counter()
    # Text is a reusable baseline, not a claim that every word was shown/taught.
    pages = []
    for ref in refs:
        with pymupdf.open(ref['render_pdf']) as doc:
            for i, page in enumerate(doc):
                pages.append(dict(page_id=f'{ref["deck_id"]}:{i+1}', text=page.get_text(),
                    source_sha256=ref['source_sha256'], render_sha256=ref['render_sha256'],
                    origin='rendered PDF text layer; may include unrevealed animation content'))
    atomic_json(out/'page-baselines.json', pages)
    # One sequential decode yields both the 1 s change probes and the 5 s base samples.
    decoded = out/'shared-decode'
    already = (out/'change-scan.json').exists() and (decoded/'extraction.json').exists()
    changes = scan(video, out/'change-scan.json', decoded/'frames', 5, video_sha256=media['sha256'])
    stats['full_video_decodes'] = 0 if already else 1
    seconds['decode_and_scan'] = round(clock.perf_counter()-started, 2)
    base = align(job, references, out/'base', frame_cache=decoded, matcher=shared,
                 references_verified=True)
    seconds['base_alignment'] = round(clock.perf_counter()-started-sum(seconds.values()), 2)
    observations = {row['time']: row for row in base['observations']}
    capture = cv2.VideoCapture(str(video))
    try:
        for time in boundary_times(changes['events'], media['duration'], changes['probes']-1):
            path = source_frame(capture, time, out/'source-frames', facts=facts, stats=stats)
            record = path.with_suffix('.match.json')
            if record.exists() and read_json(record)['image_sha256'] == facts.digest(path):
                row = read_json(record)
                stats['boundary_matches_reused'] = stats.get('boundary_matches_reused', 0)+1
            else:
                candidates = shared().analyze(path)
                status, page = decide(candidates)
                row = dict(time=time, image=str(path), image_sha256=facts.digest(path),
                           candidates=candidates, status=status, page_id=page,
                           origin='change-triggered full-resolution frame')
                atomic_json(record, row)
                stats['boundary_matches_computed'] = stats.get('boundary_matches_computed', 0)+1
            observations[time] = row
        rows = sorted(observations.values(), key=lambda row: row['time'])
        attach_comparison(rows, decoded, changes, base['inputs']['interval'])
        augmented = dict(base, observations=rows, intervals=intervals(rows, media['duration']),
                         change_scan_sha256=digest(out/'change-scan.json'))
        atomic_json(out/'alignment.json', augmented)
        differences = analyze(out/'alignment.json', out/'differences.json')
        seconds['boundaries_and_differences'] = round(clock.perf_counter()-started-sum(seconds.values()), 2)
        ocr = None
        if ocr_regions:
            from ocr_cache import OCRCache, engine_signature
            engine = []
            def recognize(path):
                # Load the engine only on a cache miss; upstream keeps it as a singleton.
                if not engine:
                    from profile_stage import load_stage
                    module = load_stage(ROOT/'vendor/lecture-to-notes/scripts/quick_ocr.py')
                    created = module.rapidocr_engine()
                    if created is None:
                        raise RuntimeError('RapidOCR unavailable')
                    engine.append(created)
                    stats['ocr_engine_inits'] = stats.get('ocr_engine_inits', 0)+1
                # Use raw recognizer with one shared cache, rather than nested caches.
                from _common import rapidocr_text_ex
                return rapidocr_text_ex(path, engine[0])
            cache = OCRCache(out/'ocr-cache', engine_signature())
            ocr = recognize_regions(differences['events'], capture, out, cache, recognize, facts, stats)
            stats.update(ocr_calls=cache.misses, ocr_cache_hits=cache.hits)
            seconds['region_ocr'] = round(clock.perf_counter()-started-sum(seconds.values()), 2)
    finally:
        capture.release()
    seconds['total'] = round(clock.perf_counter()-started, 2)
    work = dict(sorted({**stats, **shared.stats(), 'source_image_decodes': facts.image_decodes}.items()),
                seconds=seconds)
    report = dict(state='review_required', observations=len(rows),
        uncertain_observations=sum(row['status'] != 'candidate' for row in rows),
        difference_events=len(differences['events']), ocr_regions=ocr_regions,
        ocr_errors=sum(bool(c['error']) for e in ocr['events'] for side in ('before','after')
                       for c in e[side]['regions']) if ocr else 0,
        published_evidence_modified=False, work=work,
        limitations=['Candidate page matches and region OCR require review',
                     'Sampling can miss sub-second pages and small transient annotations',
                     'Unmatched pages need manual mapping or separate full-frame OCR',
                     'Original occurrences are not replaced or deleted'])
    atomic_json(out/'status.json', report)
    print(report, flush=True)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--job', type=Path, required=True)
    p.add_argument('--references', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--ocr-regions', action='store_true')
    p.add_argument('--feature-cache', type=Path, help='deck feature cache (default data/cache/deck-features)')
    a = p.parse_args()
    try:
        run(a.job, a.references, a.out, ocr_regions=a.ocr_regions, feature_cache=a.feature_cache)
    except Exception as error:
        if (a.out/'inputs.json').exists():
            atomic_json(a.out/'failure.json', dict(error=str(error)))
        raise
