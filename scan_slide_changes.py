"""Cheap low-resolution change probes; nominate frames, never discard evidence."""
import argparse
from pathlib import Path
import subprocess
import time
import numpy as np
from pipeline_common import atomic_json,digest,read_json
from frame_cache import frame_manifest, validate_frame_cache


def change_fraction(before,after,threshold=25):
    return float(np.mean(np.abs(after.astype(np.int16)-before.astype(np.int16))>threshold))


def scan(video,out,base_frames=None,interval=5,video_sha256=None):
    """One sequential decode. With base_frames, the same pass also writes the
    deck-alignment samples that `fps=1/interval:round=up,scale=960:-2` produced:
    both fps filters keep the last frame at or before each slot, so probe n*interval
    is the same decoded frame. Writes <base_frames>/../extraction.json on success."""
    video,out=Path(video),Path(out)
    if type(interval) is not int or interval < 1:
        raise ValueError('interval must be a positive integer')
    signature=dict(video_sha256=video_sha256 or digest(video),width=320,height=224,fps=1,threshold=25,area=.025)
    if base_frames:
        base_frames=Path(base_frames).resolve()
        signature['base_frames']=dict(folder=str(base_frames),interval=interval,width=960,quality=2)
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
        return prior
    cmd=['ffmpeg','-v','error','-y','-i',str(video)]
    if base_frames:
        base_frames.mkdir(parents=True,exist_ok=True)
        for stale in base_frames.glob('frame-*.jpg'):stale.unlink()  # interrupted decode
        cmd+=['-filter_complex',f"[0:v]fps=1:round=up,split=2[a][b];[a]scale=320:224[scan];[b]select='not(mod(n,{interval}))',scale=960:-2[base]",
              '-map','[base]','-fps_mode','vfr','-q:v','2',str(base_frames/'frame-%06d.jpg'),'-map','[scan]']
    else:cmd+=['-vf','fps=1:round=up,scale=320:224']
    cmd+=['-f','rawvideo','-pix_fmt','gray','pipe:1']
    start=time.monotonic();events=[];previous=None;i=0
    with subprocess.Popen(cmd,stdout=subprocess.PIPE) as p:
        while True:
            buf=p.stdout.read(320*224)
            if not buf:break
            if len(buf)!=320*224:raise ValueError('Truncated scan frame')
            current=np.frombuffer(buf,dtype=np.uint8).reshape(224,320)
            if previous is not None:
                fraction=change_fraction(previous,current)
                if fraction>=.025:events.append(dict(before=i-1,after=i,changed_fraction=fraction))
            previous=current;i+=1
        if p.wait():raise RuntimeError('Video scan failed')
    result=dict(inputs=signature,probes=i,events=events,seconds=time.monotonic()-start,
                limitations=['One-second probe grid is not frame-exact','Small annotations use a separate path; area threshold does not discard them','Zoom, pan and overlays may also trigger changes'])
    if base_frames:
        manifest=frame_manifest(base_frames)
        frames=manifest['frames']
        if frames!=-(-i//interval):raise RuntimeError(f'Expected {-(-i//interval)} base frames, decoded {frames}')
        atomic_json(receipt,dict(media_sha256=signature['video_sha256'],interval=interval,width=960,
                                 quality=2,**manifest,method='shared 1fps decode with change scan'))
    atomic_json(out,result)
    print('scan',i,'probes;',len(events),'change events;',round(result['seconds'],1),'seconds',flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('video',type=Path);p.add_argument('out',type=Path)
    p.add_argument('--base-frames',type=Path,help='also write deck-alignment samples from the same decode')
    p.add_argument('--interval',type=int,default=5);a=p.parse_args();scan(a.video,a.out,a.base_frames,a.interval)
