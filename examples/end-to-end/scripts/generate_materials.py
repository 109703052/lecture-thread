"""Generate the original circular-queue materials: deck PDF, synthetic narration and video.

Usage (project root):
  .venv/Scripts/python.exe examples/end-to-end/scripts/generate_materials.py [--out DIR]

Inputs are the tracked, editable sources in examples/end-to-end/course/. Every
output goes to an ignored folder (default output/e2e-circular-queue/materials).
Narration uses the Windows built-in SAPI voice "Microsoft Hanhan Desktop"
(zh-TW); it is synthetic speech, not a recorded lecturer.

expected_events.json is derived from the storyboard and the measured narration
durations. It is ground truth for evaluation only; no pipeline stage reads it.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import wave

EXAMPLE = Path(__file__).resolve().parents[1]
ROOT = EXAMPLE.parents[1]
sys.path.insert(0, str(ROOT))
from pipeline_common import atomic_json, digest  # noqa: E402

COURSE = EXAMPLE/'course'
DEFAULT_OUT = ROOT/'output/e2e-circular-queue/materials'
VOICE = 'Microsoft Hanhan Desktop'
SAMPLE_RATE = 22050
SPEAKING_RATE = 2  # SAPI -10..10; 0 is the voice default
FPS = 25
INK = (0.82, 0.08, 0.08)
TEXT = (0.12, 0.12, 0.12)
MUTED = (0.45, 0.45, 0.45)
ACCENT = (0.40, 0.26, 0.13)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validate_sources(deck, story):
    pages = {page['id']: page for page in deck['pages']}
    if len(pages) != len(deck['pages']):
        raise ValueError('Deck page ids must be unique')
    segments = story['segments']
    if not segments or 'page' not in segments[0]:
        raise ValueError('The first narration segment must choose a page')
    seen, current = set(), None
    for seg in segments:
        if seg['id'] in seen or not seg.get('text', '').strip():
            raise ValueError(f'Segment ids must be unique and texts non-empty: {seg["id"]}')
        seen.add(seg['id'])
        current = seg.get('page', current)
        if current not in pages:
            raise ValueError(f'Unknown page {current} in {seg["id"]}')
        page = pages[current]
        reveal_items = [b for b in page['blocks'] if b.get('reveal')]
        if 'reveal' in seg and (not reveal_items or not 1 <= seg['reveal'] <= len(reveal_items[0]['items'])):
            raise ValueError(f'Invalid reveal step in {seg["id"]}')
        for mark in seg.get('add_marks', []) + seg.get('erase_marks', []):
            if mark not in page.get('marks', {}):
                raise ValueError(f'Mark {mark} does not belong to page {current}')
        for insert in seg.get('inserts', []):
            if insert['page'] not in pages or insert['at'] < 0 or insert['duration'] <= 0:
                raise ValueError(f'Invalid insert in {seg["id"]}')


def plan_timeline(story, durations):
    """Pure function: narration timing -> visual states and the expected-event list.

    Every visual change happens at a segment start, or at an explicit insert offset.
    The state between segments (gaps) is the previous state.
    """
    t = story['lead_in_seconds']
    timed, states, events = [], [], []
    marks = defaultdict(set)
    current, seen_pages = None, []

    def push(at, state):
        if states and states[-1]['state'] == state:
            return
        states.append(dict(start=round(at, 3), state=state))

    def event(at, kind, seg, before, after, **extra):
        events.append(dict(id=f'E{len(events)+1:02}', time=round(at, 3), kind=kind, segment=seg['id'],
                           page_before=before['page'] if before else None, page_after=after['page'],
                           **extra))

    for seg in story['segments']:
        start, duration = t, durations[seg['id']]
        before = current
        page = seg.get('page', current['page'] if current else None)
        reveal = seg.get('reveal') if 'page' in seg else seg.get('reveal', current['reveal'])
        for name in seg.get('add_marks', []):
            marks[page].add(name)
        for name in seg.get('erase_marks', []):
            marks[page].discard(name)
        state = dict(page=page, reveal=reveal, marks=sorted(marks[page]))
        label = seg.get('label', '')
        if before is None:
            event(0.0, 'start', seg, None, state, label=label)
            push(0.0, state)
        else:
            if page != before['page']:
                # Storyboard tags name the intent (a short detour and its return);
                # otherwise any page seen before is a revisit that must stay separate.
                kind = {'brief-page': 'brief_page', 'return': 'return'}.get(
                    seg.get('tag'), 'revisit' if page in seen_pages else 'page_change')
                event(start, kind, seg, before, state, label=label)
            elif reveal != before['reveal']:
                event(start, 'reveal', seg, before, state, label=label, reveal=reveal)
            for name in seg.get('add_marks', []):
                event(start, 'annotation_add', seg, before, state, label=label, mark=name)
            for name in seg.get('erase_marks', []):
                event(start, 'annotation_erase', seg, before, state, label=label, mark=name)
            push(start, state)
        if page not in seen_pages:
            seen_pages.append(page)
        for insert in seg.get('inserts', []):
            if insert['at'] + insert['duration'] >= duration:
                raise ValueError(f'Insert in {seg["id"]} extends beyond its narration')
            a = start + insert['at']
            flash = dict(page=insert['page'], reveal=None, marks=sorted(marks[insert['page']]))
            event(a, 'challenge_flash' if insert.get('challenge') else 'brief_page', seg, state, flash,
                  label=insert.get('label', ''), duration=insert['duration'], challenge=bool(insert.get('challenge')))
            push(a, flash)
            push(a + insert['duration'], state)
            events.append(dict(id=f'E{len(events)+1:02}', time=round(a+insert['duration'], 3),
                               kind='return_after_flash', segment=seg['id'], page_before=flash['page'],
                               page_after=state['page'], challenge=bool(insert.get('challenge')),
                               label='返回 '+state['page']))
        timed.append(dict(id=seg['id'], start=round(start, 3), end=round(start+duration, 3), text=seg['text']))
        current = state
        t = start + duration + story['gap_seconds']
    total = round(t - story['gap_seconds'] + story['tail_seconds'], 3)
    for i, row in enumerate(states):
        row['end'] = states[i+1]['start'] if i+1 < len(states) else total
    for row in events:
        nxt = [s['start'] for s in states if s['start'] > row['time'] + 1e-6]
        row['state_seconds'] = round((nxt[0] if nxt else total) - row['time'], 3)
    return dict(duration=total, segments=timed, states=states, events=events)


# ---------- drawing (PyMuPDF, bundled Droid Sans Fallback: no system fonts) ----------

def _font(page):
    import pymupdf
    page.insert_font(fontname='cjk', fontbuffer=pymupdf.Font('china-t').buffer)


def _text(page, xy, text, size, color=TEXT):
    page.insert_text(xy, text, fontname='cjk', fontsize=size, color=color)


def _width(text, size):
    import pymupdf
    return pymupdf.Font('china-t').text_length(text, fontsize=size)


def _array_geometry(block):
    cell = block.get('cell', 100)
    return block['x'], block['y'], cell, 80


def draw_page(page, spec, number, total, reveal=None, marks=()):
    import pymupdf
    _font(page)
    _text(page, (70, 82), spec['title'], 44)
    page.draw_line((70, 104), (1210, 104), color=ACCENT, width=2)
    _text(page, (70, 696), '原創範例｜合成旁白', 16, MUTED)
    _text(page, (1130, 696), f'{number} / {total}', 16, MUTED)
    arrays = []
    for block in spec['blocks']:
        kind = block['type']
        if kind == 'subtitle':
            _text(page, (70, 200), block['text'], 28, MUTED)
        elif kind == 'bullets':
            size = block.get('size', 30)
            items = block['items'][:reveal] if block.get('reveal') and reveal else block['items']
            for i, item in enumerate(items):
                prefix = '' if item[0] in '①②③④⑤' else '• '
                _text(page, (90, block['y'] + i*size*2.1), prefix+item, size)
        elif kind == 'formula':
            w = _width(block['text'], 40)
            rect = pymupdf.Rect(640-w/2-30, block['y']-48, 640+w/2+30, block['y']+18)
            page.draw_rect(rect, color=ACCENT, fill=(0.97, 0.94, 0.90), width=1.5)
            _text(page, (640-w/2, block['y']), block['text'], 40)
        elif kind == 'array':
            x, y, cell, h = _array_geometry(block)
            arrays.append(block)
            _text(page, (x, y-16), block['caption'], 22, MUTED)
            for i, value in enumerate(block['cells']):
                page.draw_rect(pymupdf.Rect(x+i*cell, y, x+(i+1)*cell, y+h), color=TEXT, width=2)
                if value:
                    _text(page, (x+i*cell+cell/2-_width(value, 36)/2, y+h/2+13), value, 36)
                _text(page, (x+i*cell+cell/2-6, y+h+28), str(i), 22, MUTED)
            for pointer in block['pointers']:
                cx = x+pointer['index']*cell+cell/2
                if pointer['index'] >= len(block['cells']):
                    page.draw_rect(pymupdf.Rect(x+pointer['index']*cell, y, x+(pointer['index']+1)*cell, y+h),
                                   color=MUTED, width=1.5, dashes='[6 4] 0')
                page.draw_line((cx, y+h+62), (cx, y+h+38), color=ACCENT, width=2)
                page.draw_line((cx, y+h+38), (cx-7, y+h+48), color=ACCENT, width=2)
                page.draw_line((cx, y+h+38), (cx+7, y+h+48), color=ACCENT, width=2)
                _text(page, (cx-_width(pointer['label'], 22)/2, y+h+88), pointer['label'], 22, ACCENT)
        elif kind == 'table':
            x, y, row_h = block['x'], block['y'], block.get('row_height', 52)
            edges = [x]
            for w in block['widths']:
                edges.append(edges[-1]+w)
            rows = [block['header'], *block['rows']]
            page.draw_rect(pymupdf.Rect(x, y, edges[-1], y+row_h), color=None, fill=(0.95, 0.92, 0.88))
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    _text(page, (edges[c]+10, y+r*row_h+row_h*.65), value, 22, TEXT if r else ACCENT)
                page.draw_line((x, y+(r+1)*row_h), (edges[-1], y+(r+1)*row_h), color=MUTED, width=0.8)
            page.draw_line((x, y), (edges[-1], y), color=MUTED, width=0.8)
    for name in marks:
        mark = spec['marks'][name]
        x, y, cell, h = _array_geometry(arrays[mark['array']-1])  # 1-based among the page's arrays
        if mark['type'] == 'curve_arrow':
            a = pymupdf.Point(x+mark['from']*cell+cell/2, y+h+40)
            b = pymupdf.Point(x+mark['to']*cell+cell/2, y+h+40)
            page.draw_bezier(a, a+(0, 55), b+(0, 55), b, color=INK, width=4)
            page.draw_line(b, b+(-9, 16), color=INK, width=4)
            page.draw_line(b, b+(10, 14), color=INK, width=4)
            _text(page, (max(a.x, b.x)+cell/2+10, y+h+70), mark['label'], 28, INK)
        elif mark['type'] == 'pointer':
            cx = x+mark['index']*cell+cell/2
            page.draw_line((cx, y-44), (cx, y-6), color=INK, width=4)
            page.draw_line((cx, y-6), (cx-8, y-18), color=INK, width=4)
            page.draw_line((cx, y-6), (cx+8, y-18), color=INK, width=4)
            _text(page, (cx+10, y-26), mark['label'], 26, INK)


def build_deck(deck, path):
    import pymupdf
    doc = pymupdf.open()
    width, height = deck['page_size']
    for n, spec in enumerate(deck['pages'], 1):
        draw_page(doc.new_page(width=width, height=height), spec, n, len(deck['pages']))
    doc.set_metadata(dict(title=deck['title'], author='LectureThread contributors', creator='generate_materials.py'))
    doc.save(path, deflate=True, no_new_id=True)
    doc.close()


def render_state(deck, state, path):
    import pymupdf
    pages = {p['id']: (i+1, p) for i, p in enumerate(deck['pages'])}
    number, spec = pages[state['page']]
    width, height = deck['page_size']
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
    draw_page(page, spec, number, len(deck['pages']), state['reveal'], state['marks'])
    page.get_pixmap(alpha=False).save(path)
    doc.close()


# ---------- narration (Windows SAPI via PowerShell; no extra Python package) ----------

TTS_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$jobs = Get-Content -Raw -Encoding UTF8 $env:LT_TTS_JOBS | ConvertFrom-Json
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice($env:LT_TTS_VOICE)
$s.Rate = [int]$env:LT_TTS_SPEED
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo([int]$env:LT_TTS_RATE, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($job in $jobs) { $s.SetOutputToWaveFile($job.path, $fmt); $s.Speak($job.text); $s.SetOutputToNull() }
$v = $s.Voice
$info = @{ name = $v.Name; id = $v.Id; culture = $v.Culture.Name; gender = "$($v.Gender)"; age = "$($v.Age)"; description = $v.Description; vendor = $v.AdditionalInfo['Vendor']; version = $v.AdditionalInfo['Version'] }
$s.Dispose()
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$info | ConvertTo-Json -Compress
'''


def wav_seconds(path):
    with wave.open(str(path), 'rb') as stream:
        return stream.getnframes()/stream.getframerate()


def synthesize(story, folder):
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder/'tts.json'
    saved = read(manifest_path) if manifest_path.exists() else dict(segments={})
    jobs = []
    for seg in story['segments']:
        path = folder/f'{seg["id"]}.wav'
        text_sha = hashlib.sha256(seg['text'].encode()).hexdigest()
        row = saved['segments'].get(seg['id'])
        if not (row and row['text_sha256'] == text_sha and row.get('voice') == VOICE and row.get('rate') == SPEAKING_RATE
                and path.exists() and digest(path) == row['wav_sha256']):
            jobs.append(dict(id=seg['id'], text=seg['text'], path=str(path.resolve()), text_sha256=text_sha))
    voice = saved.get('voice_info')
    if jobs:
        job_file = folder/'tts-jobs.json'
        job_file.write_text(json.dumps(jobs, ensure_ascii=False), encoding='utf-8')
        env = dict(os.environ, LT_TTS_JOBS=str(job_file.resolve()), LT_TTS_VOICE=VOICE, LT_TTS_RATE=str(SAMPLE_RATE),
                   LT_TTS_SPEED=str(SPEAKING_RATE))
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', TTS_SCRIPT],
                                env=env, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError('SAPI narration failed. The zh-TW voice "Microsoft Hanhan Desktop" must be installed '
                               '(Windows Settings > Time & language > Speech). Details: '
                               + result.stderr.decode('utf-8', 'replace')[-800:])
        voice = json.loads(result.stdout.decode('utf-8-sig').strip().splitlines()[-1])
        for job in jobs:
            path = Path(job['path'])
            saved['segments'][job['id']] = dict(text_sha256=job['text_sha256'], voice=VOICE, rate=SPEAKING_RATE,
                                                wav_sha256=digest(path), seconds=round(wav_seconds(path), 3))
        job_file.unlink()
    saved['voice_info'] = voice
    atomic_json(manifest_path, saved)
    return {seg['id']: saved['segments'][seg['id']]['seconds'] for seg in story['segments']}, voice, len(jobs)


def mix_narration(story, timeline, folder, out):
    frames = round(timeline['duration']*SAMPLE_RATE)
    pcm = bytearray(frames*2)
    for seg in timeline['segments']:
        with wave.open(str(folder/f'{seg["id"]}.wav'), 'rb') as stream:
            if (stream.getframerate(), stream.getsampwidth(), stream.getnchannels()) != (SAMPLE_RATE, 2, 1):
                raise ValueError('Unexpected narration format')
            data = stream.readframes(stream.getnframes())
        offset = round(seg['start']*SAMPLE_RATE)*2
        pcm[offset:offset+len(data)] = data
    with wave.open(str(out), 'wb') as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(SAMPLE_RATE)
        stream.writeframes(bytes(pcm[:frames*2]))


def tool_version(command):
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True).stdout.splitlines()[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        return None


def reuse_materials(out):
    """Reuse a complete, verified generation; never overwrite an existing source set."""
    receipt = out/'materials.json'
    if not receipt.exists():
        if out.exists() and any(out.iterdir()):
            raise ValueError('Incomplete materials directory; use a new --out to preserve existing artifacts')
        return False
    saved = read(receipt)
    sources = {name: digest(COURSE/name) for name in
               ('deck.json', 'storyboard.json', 'content-baseline.json')}
    if saved.get('sources') != sources or saved.get('generator_sha256') != digest(Path(__file__)):
        raise ValueError('Material sources or generator changed; use a new --out')
    required = ('deck.pdf', 'deck.json', 'narration.wav', 'lecture.mp4',
                'expected_events.json', 'narration_script.json')
    for name in required:
        path = out/name
        expected = saved.get('files', {}).get(name, {}).get('sha256')
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f'Material missing or changed: {name}; use a new --out')
    print(f'Reusing verified materials in {out}; no files rewritten')
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    import pymupdf
    out = args.out.resolve()
    if reuse_materials(out):
        return 0
    out.mkdir(parents=True, exist_ok=True)
    timings, started = {}, time.perf_counter()
    deck, story = read(COURSE/'deck.json'), read(COURSE/'storyboard.json')
    validate_sources(deck, story)
    build_deck(deck, out/'deck.pdf')
    (out/'deck.json').write_bytes((COURSE/'deck.json').read_bytes())  # immutable copy referenced by references.json
    timings['deck_pdf'] = round(time.perf_counter()-started, 2)
    mark = time.perf_counter()
    durations, voice, synthesized = synthesize(story, out/'tts')
    timings['tts'] = round(time.perf_counter()-mark, 2)
    timeline = plan_timeline(story, durations)
    mix_narration(story, timeline, out/'tts', out/'narration.wav')
    mark = time.perf_counter()
    frames = out/'frames'
    frames.mkdir(exist_ok=True)
    names = {}
    for row in timeline['states']:
        key = json.dumps(row['state'], sort_keys=True)
        if key not in names:
            names[key] = f'state-{len(names)+1:02}.png'
            render_state(deck, row['state'], frames/names[key])
        row['image'] = names[key]
    concat = out/'frames.ffconcat'
    lines = ['ffconcat version 1.0']
    for row in timeline['states']:
        lines += [f"file 'frames/{row['image']}'", f'duration {row["end"]-row["start"]:.3f}']
    lines.append(f"file 'frames/{timeline['states'][-1]['image']}'")
    concat.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    video = out/'lecture.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat),
                    '-i', str(out/'narration.wav'), '-map', '0:v:0', '-map', '1:a:0',
                    '-vf', f'fps={FPS},format=yuv420p', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
                    '-tune', 'stillimage', '-c:a', 'aac', '-b:a', '128k', '-t', f'{timeline["duration"]:.3f}',
                    '-movflags', '+faststart', str(video)], check=True, cwd=out)
    timings['frames_and_video'] = round(time.perf_counter()-mark, 2)
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                                '-of', 'json', str(video)]))
    atomic_json(out/'expected_events.json', dict(
        schema=1, purpose='Ground truth for evaluation only. Never pass this file to a detector.',
        video_sha256=digest(video), duration=timeline['duration'], states=timeline['states'],
        events=timeline['events'], sampling_note='visual pipeline: 1 fps 320x224 change probes (area >= 2.5%), '
        '5 s base samples, full-resolution boundary frames; events shorter than 1 s are challenge cases'))
    atomic_json(out/'narration_script.json', dict(
        schema=1, purpose='Ground-truth narration script with synthesized timing. Evaluation and correction basis only; never an ASR output.',
        segments=timeline['segments']))
    files = {name: dict(bytes=(out/name).stat().st_size, sha256=digest(out/name))
             for name in ('deck.pdf', 'deck.json', 'narration.wav', 'lecture.mp4', 'expected_events.json', 'narration_script.json')}
    atomic_json(out/'materials.json', dict(
        schema=1, created_at=datetime.now(timezone.utc).isoformat(), sources={
            name: digest(COURSE/name) for name in ('deck.json', 'storyboard.json', 'content-baseline.json')},
        generator_sha256=digest(Path(__file__)), files=files, video_duration_probe=float(probe['format']['duration']),
        narration=dict(engine='Windows SAPI 5 (System.Speech.Synthesis) via powershell.exe', voice=voice,
                       sample_rate=SAMPLE_RATE, sapi_rate=SPEAKING_RATE, segments_synthesized_this_run=synthesized,
                       nature='synthetic speech of an original script; not a human lecture and not a cloned voice',
                       distribution='Generated audio/video stay local; regenerate on each machine. '
                                    'Redistribution of Windows built-in voice output is not asserted here.'),
        tools=dict(python=platform.python_version(), pymupdf=[pymupdf.VersionBind, pymupdf.VersionFitz],
                   font='PyMuPDF bundled CJK font china-t (Droid Sans Fallback)',
                   ffmpeg=tool_version(['ffmpeg', '-version']), os=platform.platform()),
        seconds=dict(timings, total=round(time.perf_counter()-started, 2))))
    print(f'Materials in {out}\n  video {timeline["duration"]:.1f} s, {len(timeline["segments"])} narration segments, '
          f'{len(timeline["states"])} visual states, {len(timeline["events"])} expected events')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
