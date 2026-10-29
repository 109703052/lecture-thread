"""Cheap low-resolution change probes; nominate frames, never discard evidence."""
import argparse
from pathlib import Path
import subprocess
import time
import numpy as np
from pipeline_common import atomic_json,digest,read_json
from frame_cache import frame_manifest, validate_frame_cache

COMPARE_WIDTH=960
# Which probe slots keep a comparison frame; visual_pipeline observes exactly these times.
COMPARE_RULE='every interval-th probe, before/after/after+1 of each change event, final probe'


def change_fraction(before,after,threshold=25):
    return float(np.mean(np.abs(after.astype(np.int16)-before.astype(np.int16))>threshold))


def comparison_slots(events,probes,interval):
    """Probe slots whose lossless comparison frame is kept (base samples, event neighbours, tail)."""
    slots=set(range(0,probes,interval))|{probes-1}
    for e in events:slots|={e['before'],e['after'],e['after']+1}
    return {s for s in slots if 0<=s<probes}


def comparison_name(slot):
    return f'frame-{slot+1:06d}.png'


def validate_comparison(folder,saved,slots):
    """Fail closed: the kept comparison frames must be exactly the expected slots, unmodified."""
    hashes=(saved or {}).get('frame_sha256')
    names={comparison_name(s) for s in slots}
    if not isinstance(hashes,dict) or set(hashes)!=names:
        raise ValueError('Comparison frame cache has no matching manifest; use a new output directory')
    if {p.name for p in Path(folder).glob('frame-*.png')}!=names:
        raise ValueError('Comparison frame cache is incomplete; use a new output directory')
    for name in sorted(names):
        if digest(Path(folder)/name)!=hashes[name]:
            raise ValueError(f'Comparison frame content changed: {name}; use a new output directory')
    return hashes


def _discard(paths):
    """Delete unneeded comparison frames; return those not yet written or still open."""
    left=[]
    for path in paths:
        try:path.unlink()
        except (FileNotFoundError,PermissionError):left.append(path)  # final sweep removes them
    return left


def scan(video,out,base_frames=None,interval=5,video_sha256=None):
    """One sequential decode. With base_frames, the same pass also writes the
    deck-alignment samples that `fps=1/interval:round=up,scale=960:-2` produced:
    both fps filters keep the last frame at or before each slot, so probe n*interval
    is the same decoded frame. It also writes lossless 960px comparison frames
    (one scaler, PNG) for every observed slot, so difference review never compares
    a JPEG sample with a differently scaled seek frame. Writes
    <base_frames>/../extraction.json on success."""
    video,out=Path(video),Path(out)
    if type(interval) is not int or interval < 1:
        raise ValueError('interval must be a positive integer')
    signature=dict(video_sha256=video_sha256 or digest(video),width=320,height=224,fps=1,threshold=25,area=.025)
    if base_frames:
        base_frames=Path(base_frames).resolve()
        compare=base_frames.parent/'compare'
        signature['base_frames']=dict(folder=str(base_frames),interval=interval,width=960,quality=2)
        signature['comparison_frames']=dict(folder=str(compare),width=COMPARE_WIDTH,format='png',rule=COMPARE_RULE)
        receipt=base_frames.parent/'extraction.json'
    if out.exists() and (not base_frames or receipt.exists()):
        prior=read_json(out)
        if prior['inputs']!=signature:raise ValueError('Change scan inputs changed')
        if base_frames:
            saved = read_json(receipt)
            if (saved.get('media_sha256') != signature['video_sha256'] or
                    saved.get('interval') != interval or saved.get('width') != 960 or
                    saved.get('quality') != 2):
                raise ValueError('Frame cache receipt differs from scan inputs')
            validate_frame_cache(base_frames, saved, expected_count=-(-prior['probes']//interval))
            validate_comparison(compare,saved.get('comparison'),comparison_slots(prior['events'],prior['probes'],interval))
        return prior
    cmd=['ffmpeg','-v','error','-y','-i',str(video)]
    if base_frames:
        base_frames.mkdir(parents=True,exist_ok=True);compare.mkdir(exist_ok=True)
        for stale in [*base_frames.glob('frame-*.jpg'),*compare.glob('frame-*.png')]:stale.unlink()  # interrupted decode
        # Base branch is unchanged (byte-identical samples); the comparison branch scales every
        # probe with the same scaler and stays lossless. Unneeded slots are deleted while scanning.
        cmd+=['-filter_complex',f"[0:v]fps=1:round=up,split=3[a][b][c];[a]scale=320:224[scan];[b]select='not(mod(n,{interval}))',scale=960:-2[base];[c]scale={COMPARE_WIDTH}:-2[cmp]",
              '-map','[base]','-fps_mode','vfr','-q:v','2',str(base_frames/'frame-%06d.jpg'),
              '-map','[cmp]','-fps_mode','vfr','-compression_level','1',str(compare/'frame-%06d.png'),'-map','[scan]']
    else:cmd+=['-vf','fps=1:round=up,scale=320:224']
    cmd+=['-f','rawvideo','-pix_fmt','gray','pipe:1']
    start=time.monotonic();events=[];previous=None;i=0;near=set();pending=[]
    with subprocess.Popen(cmd,stdout=subprocess.PIPE) as p:
        while True:
            buf=p.stdout.read(320*224)
            if not buf:break
            if len(buf)!=320*224:raise ValueError('Truncated scan frame')
            current=np.frombuffer(buf,dtype=np.uint8).reshape(224,320)
            if previous is not None:
                fraction=change_fraction(previous,current)
                if fraction>=.025:
                    events.append(dict(before=i-1,after=i,changed_fraction=fraction));near|={i-1,i,i+1}
            previous=current;i+=1
            # Slot i-3 can no longer neighbour a future event; bound disk use to a few frames.
            if base_frames and i>=3 and (i-3)%interval and i-3 not in near:
                pending.append(compare/comparison_name(i-3))
                if len(pending)>=8:pending=_discard(pending)
        if p.wait():raise RuntimeError('Video scan failed')
    result=dict(inputs=signature,probes=i,events=events,seconds=time.monotonic()-start,
                limitations=['One-second probe grid is not frame-exact','Small annotations use a separate path; area threshold does not discard them','Zoom, pan and overlays may also trigger changes'])
    if base_frames:
        manifest=frame_manifest(base_frames)
        frames=manifest['frames']
        if frames!=-(-i//interval):raise RuntimeError(f'Expected {-(-i//interval)} base frames, decoded {frames}')
        written=sorted(compare.glob('frame-*.png'))
        if not written or written[-1].name!=comparison_name(i-1):
            raise RuntimeError(f'Expected {i} comparison frames, last written {written[-1].name if written else None}')
        keep={comparison_name(s) for s in comparison_slots(events,i,interval)}
        for path in written:
            if path.name not in keep:path.unlink()
        if {p.name for p in compare.glob('frame-*.png')}!=keep:
            raise RuntimeError('Comparison frames missing after decode')
        comparison=dict(width=COMPARE_WIDTH,format='png',rule=COMPARE_RULE,
                        frame_sha256={name:digest(compare/name) for name in sorted(keep)})
        atomic_json(receipt,dict(media_sha256=signature['video_sha256'],interval=interval,width=960,
                                 quality=2,**manifest,comparison=comparison,method='shared 1fps decode with change scan'))
    atomic_json(out,result)
    print('scan',i,'probes;',len(events),'change events;',round(result['seconds'],1),'seconds',flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('video',type=Path);p.add_argument('out',type=Path)
    p.add_argument('--base-frames',type=Path,help='also write deck-alignment samples from the same decode')
    p.add_argument('--interval',type=int,default=5);a=p.parse_args();scan(a.video,a.out,a.base_frames,a.interval)
