"""Start/resume an overnight lecture task. No cloud API or system service required."""
import argparse
import html
from datetime import datetime, timezone, timedelta
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse, parse_qs
import urllib.request

from pipeline_common import atomic_json, digest, exclusive_lock, publish_immutable, read_json

ROOT = Path(__file__).resolve().parent
JOBS = ROOT / 'output/jobs'
PIPELINE_LOCK = ROOT / 'data/pipeline.lock'
PYTHON = ROOT / '.venv/Scripts/python.exe'
STAGES = ['source', 'transcribe', 'slides', 'ocr', 'dedup', 'vlm', 'ground',
          'evidence', 'author', 'export', 'review']
PIPELINE_VERSION = 2


def now():
    return datetime.now(timezone.utc).isoformat()


def youtube_id(source):
    parsed = urlparse(source)
    if parsed.scheme not in ('http', 'https'):
        return ''
    if parsed.hostname in ('youtu.be', 'www.youtu.be'):
        value = parsed.path.strip('/').split('/')[0]
    elif parsed.hostname in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
        value = parse_qs(parsed.query).get('v', [''])[0]
        if not value and parsed.path.startswith(('/shorts/', '/live/', '/embed/')):
            value = parsed.path.split('/')[2]
    else:
        raise ValueError('目前網址輸入只接受 YouTube；其他來源請提供本機影片。')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', value):
        raise ValueError('無法取得 YouTube 影片 ID')
    return value


def job_path(job_id):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', job_id):
        raise ValueError('任務 ID 只接受英數字、底線和連字號，最多 80 字元。')
    path = (JOBS / job_id).resolve()
    path.relative_to(JOBS.resolve())
    return path


def create_job(source, job_id=None, title=None, model='qwen2.5:7b', interval=2, retries=2,
               vlm_model='minicpm-v:8b'):
    yt = youtube_id(source)
    if not yt:
        local = Path(source).resolve()
        if not local.is_file():
            raise FileNotFoundError(local)
        source = str(local)
        fingerprint = dict(size=local.stat().st_size, sha256=digest(local))
    else:
        source = f'https://www.youtube.com/watch?v={yt}'
        fingerprint = None
    job_id = job_id or datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S') + '-' + os.urandom(3).hex()
    folder = job_path(job_id)
    folder.mkdir(parents=True, exist_ok=False)
    config = dict(schema=1, pipeline_version=PIPELINE_VERSION, id=job_id, source=source,
                  source_fingerprint=fingerprint, youtube_id=yt,
                  title=title or (Path(source).stem if not yt else yt),
                  model=model, vlm_model=vlm_model, interval=interval, retries=retries)
    config['profile_hashes'] = {file.name: digest(file)
                                for file in (ROOT / 'profiles/computer-science').iterdir() if file.is_file()}
    atomic_json(folder / 'job.json', config)
    atomic_json(folder / 'status.json', dict(schema=1, state='queued', created_at=now(),
                                           job_sha256=digest(folder / 'job.json'), stages={}))
    return folder


class Worker:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.config = read_json(self.folder / 'job.json')
        self.status = read_json(self.folder / 'status.json')
        self.course = self.folder / 'course'
        self.course.mkdir(exist_ok=True)
        self.logs = self.folder / 'logs'
        self.logs.mkdir(exist_ok=True)
        self.media = self.folder / 'media/lecture.mp4'
        self.manifest = self.folder / 'course.local.json'
        self.current = None

    def save(self):
        self.status['updated_at'] = now()
        self.status['completed_stages'] = sum(row.get('state') == 'completed'
                                               for row in self.status['stages'].values())
        self.status['total_stages'] = len(STAGES)
        atomic_json(self.folder / 'status.json', self.status)

    def event(self, kind, **fields):
        with (self.folder / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(time=now(), event=kind, **fields), ensure_ascii=False)+'\n')

    def recover_child(self):
        """After a hard parent crash, retire only the precisely recorded project child."""
        pid = self.status.get('child_pid')
        if not pid:
            return
        import psutil
        try:
            process = psutil.Process(pid)
            created = self.status.get('child_created_at')
            if created is None:
                raise RuntimeError('舊子程序仍存在，但缺少建立時間；請核對日誌及程序後再續跑。')
            if process.create_time() == created:
                if str(ROOT / 'run.py').casefold() not in ' '.join(process.cmdline()).casefold():
                    raise RuntimeError('舊子程序身分不符，拒絕停止不明程序。')
                for child in reversed(process.children(recursive=True)):
                    try: child.kill()
                    except psutil.NoSuchProcess: pass
                process.kill()
                process.wait(timeout=15)
                self.event('orphan_child_stopped', pid=pid)
        except psutil.NoSuchProcess:
            pass
        self.status.pop('child_pid', None)
        self.status.pop('child_created_at', None)

    def command(self, args, timeout=21600):
        """All stage processes use run.py's project-scoped environment."""
        command = [str(PYTHON), str(ROOT / 'run.py'), *map(str, args)]
        log = self.logs / f'{self.current or "preflight"}.log'
        with log.open('ab') as stream:
            stream.write(('\n'+now()+' '+json.dumps(command, ensure_ascii=False)+'\n').encode())
            stream.flush()
            child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            import psutil
            try:
                self.status['child_created_at'] = psutil.Process(child.pid).create_time()
            except psutil.NoSuchProcess:
                self.status.pop('child_created_at', None)
            started = time.monotonic()
            try:
                while child.poll() is None:
                    if time.monotonic() - started > timeout:
                        raise TimeoutError(f'{self.current}: stage exceeded {timeout} seconds')
                    self.status['child_pid'] = child.pid
                    self.status['stage_elapsed_seconds'] = round(time.monotonic()-started, 1)
                    progress = self.course / 'author_progress.json'
                    if self.current == 'author' and progress.exists():
                        self.status['author_progress'] = read_json(progress)
                    if self.current == 'vlm' and (self.course / 'slides_vlm.json').exists():
                        rows = read_json(self.course / 'slides_vlm.json')
                        self.status['vlm_progress'] = dict(
                            completed=sum(bool(row.get('vlm_signals')) for row in rows
                                          if row.get('dedup', {}).get('is_canonical')),
                            total=sum(row.get('dedup', {}).get('is_canonical', False)
                                      for row in read_json(self.course / 'slides_dedup.json')))
                    self.save()
                    time.sleep(2)
                if child.returncode:
                    raise RuntimeError(f'{self.current}: exit {child.returncode}; see {log}')
            finally:
                if child.poll() is None:
                    import psutil
                    try:
                        process = psutil.Process(child.pid)
                        children = process.children(recursive=True)
                        for item in reversed(children):
                            try: item.kill()
                            except psutil.NoSuchProcess: pass
                        process.kill()
                        process.wait(timeout=15)
                    except psutil.NoSuchProcess:
                        pass
                self.status.pop('child_pid', None)
                self.status.pop('child_created_at', None)

    def ollama(self, stop=False):
        self.command([ROOT / 'ollama_service.py', *(['stop'] if stop else [])], timeout=90)

    def preflight(self):
        self.require_local_authoring()
        if digest(self.folder / 'job.json') != self.status.get('job_sha256'):
            raise ValueError('任務設定已變動；請建立新任務以免混用不同模型或抽樣設定。')
        if self.config['pipeline_version'] != PIPELINE_VERSION:
            raise ValueError('任務版本不相容，請建立新任務。')
        for name, expected in self.config.get('profile_hashes', {}).items():
            if digest(ROOT / 'profiles/computer-science' / name) != expected:
                raise ValueError(f'資工處理設定已變動：{name}；請建立新任務。')
        for name in ('ffmpeg', 'ffprobe'):
            if not shutil.which(name):
                raise RuntimeError(f'Missing prerequisite: {name}')
        for file in (PYTHON, ROOT / 'tools/ollama/ollama.exe',
                     ROOT / 'vendor/lecture-to-notes/scripts/transcribe_video.py'):
            if not file.is_file():
                raise FileNotFoundError(f'Missing prerequisite: {file}')
        self.command(['-c', 'import psutil, PIL, faster_whisper, rapidocr_onnxruntime, yaml, yt_dlp'])
        if not self.config['youtube_id']:
            source = Path(self.config['source'])
            expected = self.config['source_fingerprint']
            if source.stat().st_size != expected['size'] or digest(source) != expected['sha256']:
                raise ValueError('來源影片已變動；請以新的任務 ID 處理，保留原任務。')
        # Validate local endpoint and model BEFORE an hours-long transcription.
        # Tags do not load a model. Stop before Whisper to free any stale model residency.
        try:
            self.ollama()
            with urllib.request.urlopen('http://127.0.0.1:11435/api/tags', timeout=10) as response:
                models = {row['name']: row['digest'] for row in json.load(response)['models']}
            selected = {self.config['model'], self.config['vlm_model']}
            if missing := selected - models.keys():
                raise RuntimeError(f'Models not installed: {missing}; run lecture.cmd prepare')
            versions = {name: models[name] for name in selected}
            version_path = self.folder / 'model_versions.json'
            if version_path.exists() and read_json(version_path) != versions:
                raise ValueError('模型權重版本已變動；請建立新任務，不混用舊 checkpoint。')
            atomic_json(version_path, versions)
        finally:
            self.ollama(stop=True)

    def artifact_hashes(self, paths):
        result = {}
        for path in paths:
            path = Path(path)
            files = sorted(path.rglob('*')) if path.is_dir() else [path]
            for file in files:
                if file.is_file():
                    result[file.relative_to(self.folder).as_posix()] = digest(file)
        if not result:
            raise ValueError(f'No artifacts produced: {self.current}')
        return result

    def stage(self, name, operation):
        self.current = name
        entry = self.status['stages'].setdefault(name, {})
        if entry.get('state') == 'completed':
            for relative, expected in entry['artifacts'].items():
                file = self.folder / relative
                if not file.is_file() or digest(file) != expected:
                    raise ValueError(f'已完成產物遭變動，為保留修訂停止續跑：{file}')
            return
        self.status.update(state='running', current_stage=name)
        for attempt in range(self.config['retries']+1):
            started = time.monotonic()
            entry.update(state='running', attempts=entry.get('attempts', 0)+1, started_at=now())
            self.save()
            self.event('stage_started', stage=name, attempt=entry['attempts'])
            print(f'[{STAGES.index(name)+1}/{len(STAGES)}] {name}', flush=True)
            try:
                outputs = operation()
                if name == 'author' and (self.course / 'author_progress.json').exists():
                    self.status['author_progress'] = read_json(self.course / 'author_progress.json')
                if name == 'vlm' and self.status.get('vlm_progress'):
                    self.status['vlm_progress']['completed'] = self.status['vlm_progress']['total']
                hashes = self.artifact_hashes(outputs)
                entry.update(state='completed', finished_at=now(), artifacts=hashes,
                             elapsed_seconds=round(time.monotonic()-started, 2))
                entry.setdefault('history', []).append(dict(state='completed',
                    started_at=entry['started_at'], finished_at=entry['finished_at'],
                    elapsed_seconds=entry['elapsed_seconds']))
                entry.pop('error', None)
                self.save()
                self.event('stage_completed', stage=name)
                return
            except Exception as error:
                entry.update(state='failed', error=str(error), finished_at=now(),
                             elapsed_seconds=round(time.monotonic()-started, 2))
                entry.setdefault('history', []).append(dict(state='failed', error=str(error),
                    started_at=entry['started_at'], finished_at=entry['finished_at'],
                    elapsed_seconds=entry['elapsed_seconds']))
                self.save()
                self.event('stage_failed', stage=name, error=str(error))
                if attempt == self.config['retries']:
                    raise
                time.sleep(min(2 ** attempt, 8))

    def source(self):
        self.media.parent.mkdir(exist_ok=True)
        downloaded = self.folder / '_download/source.mp4'
        if self.config['youtube_id']:
            downloaded.parent.mkdir(exist_ok=True)
            self.command(['-m', 'yt_dlp', '--no-playlist', '--restrict-filenames',
                          '-f', 'bv*+ba/b', '--merge-output-format', 'mp4',
                          '--remux-video', 'mp4', '-o', downloaded, self.config['source']])
            source = downloaded
        else:
            source = Path(self.config['source'])
        # Export a browser-compatible copy without changing the original video.
        temporary = self.media.with_name('lecture.partial.mp4')
        self.command(['-c', 'import subprocess,sys; subprocess.run(sys.argv[1:],check=True)',
                      'ffmpeg', '-v', 'error', '-y', '-i', source, '-map', '0:v:0',
                      '-map', '0:a:0', '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                      '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', temporary])
        os.replace(temporary, self.media)
        probe = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                   'format=duration', '-of', 'json', str(self.media)], text=True)
        duration = float(json.loads(probe)['format']['duration'])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Invalid media duration')
        atomic_json(self.folder / 'media.json', dict(duration=duration, sha256=digest(self.media)))
        atomic_json(self.manifest, dict(schema=1, id=self.config['id'], title=self.config['title'],
                    description='本機模型生成講義；未逐句聽音覆核，請搭配待核對清單。',
                    course_dir='course', web_root='.', output_html='index.html',
                    media='media/lecture.mp4', media_kind='video', youtube_id=self.config['youtube_id']))
        return [self.media, self.folder / 'media.json', self.manifest]

    def transcribe(self):
        temporary = self.folder / '_transcribe'
        target = self.course / 'transcript.json'
        receipt_path = temporary / 'published-original.json'
        duration = read_json(self.folder / 'media.json')['duration']
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            if receipt['media_sha256'] != digest(self.media):
                raise ValueError('ASR receipt belongs to different media')
            for candidate in (target, temporary / 'transcript.json'):
                if candidate.exists() and digest(candidate) == receipt['transcript_sha256']:
                    validate_transcript(read_json(candidate), duration)
                    publish_immutable(target, candidate.read_bytes())
                    return [target]
        if target.exists():
            raise ValueError('原始逐字稿已存在但沒有吻合的產生紀錄，拒絕覆寫。')
        self.command(['scripts/transcribe_video.py', self.media, '--output-dir', temporary,
                      '--lang', 'zh', '--model', 'large-v3', '--device', 'cuda',
                      '--batch-size', '3', '--initial-prompt-file',
                      ROOT / 'profiles/computer-science/asr-glossary.txt'])
        tx = read_json(temporary / 'transcript.json')
        validate_transcript(tx, duration)
        atomic_json(receipt_path, dict(media_sha256=digest(self.media),
                                      transcript_sha256=digest(temporary / 'transcript.json')))
        publish_immutable(target, (temporary / 'transcript.json').read_bytes())
        return [target]

    def slides(self):
        self.command([ROOT / 'extract_occurrences.py', self.media, self.course,
                      '--interval', self.config['interval']])
        return [self.course / 'slides', self.course / '_samples']

    def upstream(self, script, output):
        args = [f'scripts/{script}.py', self.course]
        if script == 'vlm_signals':
            self.ollama()
            args += ['--model', self.config.get('vlm_model', self.config['model']),
                     '--resume', '--save-every', '1', '--no-skip-gate']
        self.command(args)
        value = read_json(self.course / output)
        if not isinstance(value, list) or not value:
            raise ValueError(f'Empty stage artifact: {output}')
        if script in ('quick_ocr', 'ground_slides', 'vlm_signals'):
            if len(value) != len(read_json(self.course / 'slides/timestamps.json')):
                raise ValueError(f'Occurrence count changed in {script}')
        if script == 'quick_ocr' and any(s.get('missing_frame') or (s.get('ocr') or {}).get('ocr_error') for s in value):
            raise ValueError('OCR failed on one or more frames; see stage log')
        if script == 'vlm_signals' and any(not s.get('vlm_signals') for s in value if s.get('dedup', {}).get('is_canonical')):
            raise ValueError('Incomplete VLM signals; resume retries failed slides')
        return [self.course / output]

    def dedup(self):
        # Share analysis only for pixel-identical samples; semantic similarity can hide annotations.
        rows = read_json(self.course / 'slides_raw.json')
        frames = read_json(self.course / 'slides/timestamps.json')
        seen = {}
        for row, frame in zip(rows, frames):
            previous = seen.get(frame['pixel_sha256'])
            row['dedup'] = dict(is_canonical=previous is None,
                                superseded_by=previous['filename'] if previous else None)
            seen.setdefault(frame['pixel_sha256'], row)
        if len(rows) != len(frames):
            raise ValueError('OCR did not retain every occurrence')
        atomic_json(self.course / 'slides_dedup.json', rows)
        return [self.course / 'slides_dedup.json']

    def evidence(self):
        from build_cs_deliverable import assign_segments
        tx = read_json(self.course / 'transcript.json')
        frames = read_json(self.course / 'slides/timestamps.json')
        grounded = read_json(self.course / 'slides_grounded.json')
        duration = read_json(self.folder / 'media.json')['duration']
        intervals = [(f['first_ts'], frames[i+1]['first_ts'] if i+1 < len(frames) else duration)
                     for i, f in enumerate(frames)]
        if any(not 0 <= a < b <= duration for a, b in intervals):
            raise ValueError('Invalid occurrence intervals')
        owners = assign_segments(tx, intervals)
        by_name = {s['filename']: s for s in grounded if s.get('vlm_signals')}
        evidence = []
        for i, (frame, row, (a, b)) in enumerate(zip(frames, grounded, intervals)):
            model = by_name.get(row.get('dedup', {}).get('superseded_by'), row)
            evidence.append(dict(occurrence_id=i+1, start=a, end=b, image=frame['filename'],
                title=(row.get('ocr') or {}).get('quick_title_guess') or f'畫面 {i+1}',
                ocr=row.get('ocr'), vlm_signals=model.get('vlm_signals'),
                primary_transcript_ids=owners[i],
                overlapping_transcript_ids=[j for j, s in enumerate(tx) if s['start'] < b and s['end'] > a],
                timing_precision=f'{self.config["interval"]}-second sampling; not frame-accurate'))
        atomic_json(self.course / 'slide_evidence.json', evidence)
        return [self.course / 'slide_evidence.json']

    def require_local_authoring(self):
        if (self.course / 'editorial_chapters.json').exists():
            raise ValueError('此課程已改由 Codex 直接撰寫，禁止舊 worker 回退本機模型；請使用 editorial_publish.py --course '+str(self.manifest))

    def author(self):
        self.require_local_authoring()
        self.ollama()
        self.command([ROOT / 'author_lecture.py', self.course, '--model', self.config['model']])
        return [self.course / name for name in ('authored_notes.json', 'transcript.corrected.json',
                'transcript.corrections.json', 'author_flags.json')]

    def export(self):
        self.command([ROOT / 'build_reader.py', '--course', self.manifest])
        return [self.folder / 'index.html', self.course / 'reading_alignment.json']

    def review(self):
        report, flags = validate_deliverable(self.folder)
        atomic_json(self.course / 'coverage_report.json', report)
        atomic_json(self.folder / 'review.json', flags)
        lines = ['# 待核對清單', '',
                 '本機模型生成，未逐句聽音覆核；清單為空也不表示內容已由人工確認。', '',
                 f'畫面邊界以 {self.config["interval"]} 秒抽樣估計，短暫切頁仍可能漏取。', '']
        for flag in flags:
            at = max(0, int(flag.get('time', 0)))
            lines.append(f'- {at//60:02}:{at%60:02}｜畫面 {flag.get("occurrence_id", "—")}｜{flag["message"]}')
        if not flags:
            lines.append('- 模型未提出特定疑點；請抽查專有名詞、數值、公式與程式碼。')
        (self.folder / '待核對清單.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
        items = ''.join('<li>'+html.escape(line[2:])+'</li>' for line in lines if line.startswith('- '))
        (self.folder / 'review.html').write_text(
            '<!doctype html><html lang="zh-Hant"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>待核對清單｜課脈</title><style>body{max-width:60rem;margin:3rem auto;'
            'padding:0 1rem;font:18px/1.8 system-ui}li{margin:1rem 0}</style>'
            '<a href="index.html">開啟課程講義</a><h1>待核對清單</h1>'
            '<p>本機模型生成，未逐句聽音覆核。清單為空也不代表人工確認正確；'
            f'畫面以 {self.config["interval"]} 秒抽樣，短暫切頁仍可能漏取。</p><ul>'
            + items + '</ul></html>', encoding='utf-8')
        notes = read_json(self.course / 'authored_notes.json')
        text = ['# '+self.config['title'], '', '> AI 生成初稿，請搭配待核對清單與原句。', '']
        for note in notes:
            text += ['## '+note['title'], '']
            for section in note['lesson']:
                text += ['### '+section['heading'], '', section['text'], '']
        (self.folder / '完整課程講義.md').write_text('\n'.join(text), encoding='utf-8')
        return [self.course / 'coverage_report.json', self.folder / 'review.json',
                self.folder / '待核對清單.md', self.folder / 'review.html', self.folder / '完整課程講義.md']

    def run(self):
        # One lock covers every job and cleanup, so jobs cannot share GPU/Ollama concurrently.
        with exclusive_lock(PIPELINE_LOCK):
            self.status.update(state='running', pid=os.getpid(), error=None)
            self.status.pop('cleanup_error', None)
            self.status['ollama_cleanup'] = 'pending'
            self.save()
            error = None
            try:
                self.recover_child()
                self.preflight()
                operations = dict(source=self.source, transcribe=self.transcribe, slides=self.slides,
                    ocr=lambda: self.upstream('quick_ocr', 'slides_raw.json'), dedup=self.dedup,
                    vlm=lambda: self.upstream('vlm_signals', 'slides_vlm.json'),
                    ground=lambda: self.upstream('ground_slides', 'slides_grounded.json'),
                    evidence=self.evidence, author=self.author, export=self.export, review=self.review)
                for name in STAGES:
                    self.stage(name, operations[name])
            except BaseException as caught:
                error = caught
                self.status.update(state='interrupted' if isinstance(caught, KeyboardInterrupt) else 'failed',
                                   error=str(caught))
                self.event('job_failed', stage=self.current, error=str(caught))
            finally:
                self.current = 'cleanup'
                try:
                    self.ollama(stop=True)
                    self.status['ollama_cleanup'] = 'completed'
                except BaseException as cleanup_error:
                    self.status['ollama_cleanup'] = 'failed'
                    self.status['cleanup_error'] = str(cleanup_error)
                    if error is None:
                        error = cleanup_error
                        self.status.update(state='failed', error='Ollama cleanup failed')
                if error is None:
                    self.status.update(state='completed', current_stage='completed', finished_at=now())
                    self.event('job_completed')
                self.status['pid'] = None
                self.save()
            if error:
                raise RuntimeError(str(error)) from error
            print(f'完成：{self.folder / "index.html"}\n待核對：{self.folder / "待核對清單.md"}', flush=True)


def validate_transcript(tx, duration):
    if not isinstance(tx, list) or not tx:
        raise ValueError('Empty transcript; speech recognition did not produce a lecture')
    last = -1
    for row in tx:
        a, b = row['start'], row['end']
        if (not isinstance(row['text'], str) or not math.isfinite(a) or not math.isfinite(b)
                or not 0 <= a < b <= duration+.5 or a < last):
            raise ValueError('Invalid transcript text/timeline')
        last = a


def validate_deliverable(folder):
    folder = Path(folder)
    course = folder / 'course'
    tx = read_json(course / 'transcript.json')
    corrected = read_json(course / 'transcript.corrected.json')
    evidence = read_json(course / 'slide_evidence.json')
    notes = read_json(course / 'authored_notes.json')
    duration = read_json(folder / 'media.json')['duration']
    validate_transcript(tx, duration)
    if len(tx) != len(corrected) or any(a['start'] != b['start'] or a['end'] != b['end'] for a, b in zip(tx, corrected)):
        raise ValueError('Correction changed segment count or timestamps')
    if len(notes) != len(evidence) or not evidence:
        raise ValueError('Missing occurrence notes')
    assigned = [i for row in evidence for i in row['primary_transcript_ids']]
    if sorted(assigned) != list(range(len(tx))):
        raise ValueError('Transcript ownership missing or duplicated')
    for note, row in zip(notes, evidence):
        image = (course / 'slides' / row['image']).resolve()
        image.relative_to((course / 'slides').resolve())
        if not image.is_file() or not note['lesson']:
            raise ValueError('Missing slide/lesson')
        cited = [i for section in note['lesson'] for i in section['source_ids']]
        if cited != row['primary_transcript_ids']:
            raise ValueError('Authored lesson does not cover source segments')
        if any(not row['start'] <= section['time'] <= row['end'] for section in note['lesson']):
            raise ValueError('Lesson time outside occurrence')
    original = read_json(folder / 'status.json')['stages']['transcribe']['artifacts']['course/transcript.json']
    if digest(course / 'transcript.json') != original:
        raise ValueError('Original transcript modified')
    flags = read_json(course / 'author_flags.json')
    for change in read_json(course / 'transcript.corrections.json'):
        flags.append(dict(kind='correction', time=tx[change['segment_id']]['start'],
                          source_ids=[change['segment_id']],
                          message=f'AI 校字待聽音：{change["original"]} → {change["corrected"]}；依據：{change["reason"]}'))
    for row in evidence:
        ocr = row.get('ocr') or {}
        if not ocr.get('quick_text', '').strip():
            flags.append(dict(occurrence_id=row['occurrence_id'], time=row['start'],
                              kind='ocr', message='畫面未辨識出文字，請核對圖表、公式或板書。'))
        elif ocr.get('model_confidence', 1) < .8:
            flags.append(dict(occurrence_id=row['occurrence_id'], time=row['start'], kind='ocr-confidence',
                              message='OCR 平均信心低於 0.8，請核對術語、符號、數字及程式碼。'))
    report = dict(occurrences=len(evidence), transcript_segments=len(tx), assigned_segments=len(assigned),
                  raw_transcript_sha256=original, raw_transcript_unchanged=True,
                  unassigned_segments=[], duplicate_assignments=0, duration_seconds=duration,
                  notes_generation='local Ollama; source coverage validated, semantic accuracy unverified',
                  quality_flags=len(flags), audio_verified=False)
    return report, flags


def launch(folder, background):
    if not background:
        Worker(folder).run()
        return
    with (folder / 'worker.log').open('ab') as log:
        child = subprocess.Popen([str(PYTHON), str(ROOT / 'lecture_pipeline.py'),
                                 '_worker', folder.name], cwd=ROOT, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, close_fds=True,
                                 creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
                                               if os.name == 'nt' else 0,
                                 start_new_session=os.name != 'nt')
    print(f'背景任務 PID {child.pid}：{folder.name}\n進度：{folder / "status.json"}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    start = sub.add_parser('start', help='Create a separate course task')
    start.add_argument('source', help='YouTube URL or local video path')
    start.add_argument('--id')
    start.add_argument('--title')
    start.add_argument('--model', default='qwen2.5:7b', help='Text authoring model')
    start.add_argument('--vlm-model', default='minicpm-v:8b', help='Visual analysis model')
    start.add_argument('--interval', type=int, default=2)
    start.add_argument('--retries', type=int, default=2)
    start.add_argument('--background', action='store_true')
    resume = sub.add_parser('resume')
    resume.add_argument('id')
    resume.add_argument('--background', action='store_true')
    status = sub.add_parser('status')
    status.add_argument('id', nargs='?')
    status.add_argument('--json', action='store_true', help='Include full artifact hashes and stage history')
    serve = sub.add_parser('serve', help='Open a completed course with local editing support')
    serve.add_argument('id')
    serve.add_argument('--port', type=int, default=8769)
    prepare = sub.add_parser('prepare', help='Download missing local Ollama models into this project')
    prepare.add_argument('--model', default='qwen2.5:7b')
    prepare.add_argument('--vlm-model', default='minicpm-v:8b')
    worker = sub.add_parser('_worker', help=argparse.SUPPRESS)
    worker.add_argument('id')
    args = parser.parse_args(argv)
    try:
        if args.action == 'prepare':
            with exclusive_lock(PIPELINE_LOCK):
                try:
                    subprocess.run([str(PYTHON), str(ROOT / 'run.py'),
                                    str(ROOT / 'ollama_service.py')], check=True)
                    for model in dict.fromkeys([args.vlm_model, args.model]):
                        subprocess.run([str(PYTHON), str(ROOT / 'run.py'), '-c',
                            'import subprocess,sys; subprocess.run(sys.argv[1:],check=True)',
                            str(ROOT / 'tools/ollama/ollama.exe'), 'pull', model], check=True)
                finally:
                    subprocess.run([str(PYTHON), str(ROOT / 'run.py'),
                                    str(ROOT / 'ollama_service.py'), 'stop'], check=True)
            return 0
        if args.action == 'serve':
            folder = job_path(args.id)
            if read_json(folder / 'status.json')['state'] != 'completed':
                raise ValueError('課程尚未完成；請先查看進度或續跑。')
            print(f'講義：http://127.0.0.1:{args.port}/index.html\n'
                  f'待核對：http://127.0.0.1:{args.port}/review.html', flush=True)
            return subprocess.call([str(PYTHON), str(ROOT / 'serve_reader.py'), '--course',
                                    str(folder / 'course.local.json'), '--port', str(args.port)])
        if args.action == 'status':
            folders = [job_path(args.id)] if args.id else sorted(JOBS.glob('*'))
            for folder in folders:
                if (folder / 'status.json').exists():
                    value = read_json(folder / 'status.json')
                    value['id'] = folder.name
                    # Dead workers never masquerade as running after a hard crash.
                    if value.get('state') == 'running' and value.get('pid'):
                        import psutil
                        age = (datetime.now(timezone.utc) - datetime.fromisoformat(value['updated_at'])).total_seconds()
                        if not psutil.pid_exists(value['pid']) and age > 30:
                            value['observed_state'] = '可能中斷（心跳逾時且看不到程序）；請核對日誌後續跑'
                    if args.json:
                        print(json.dumps(value, ensure_ascii=False, indent=2))
                    else:
                        done = sum(row.get('state') == 'completed' for row in value['stages'].values())
                        print(f'{folder.name}｜{value.get("observed_state", value["state"])}｜'
                              f'{done}/{len(STAGES)} 階段完成｜目前 {value.get("current_stage", "尚未開始")}')
                        updated = datetime.fromisoformat(value.get('updated_at', value['created_at']))
                        local_time = updated.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
                        print(f'最後更新（台灣時間）：{local_time}')
                        for name in ('vlm', 'author'):
                            progress = value.get(name+'_progress')
                            if progress:
                                print(f'{name}：{progress["completed"]}/{progress["total"]}')
                        for name, row in value['stages'].items():
                            print(f'  {name}: {row["state"]}，嘗試 {row.get("attempts", 0)} 次，'
                                  f'{row.get("elapsed_seconds", value.get("stage_elapsed_seconds", 0))} 秒')
                        if value.get('error'):
                            print('錯誤：'+value['error'])
                        if value.get('cleanup_error'):
                            print('清理錯誤：'+value['cleanup_error'])
                        print(f'Ollama 清理：{value.get("ollama_cleanup", "尚未執行")}\n日誌：{folder / "logs"}')
            return 0
        if args.action == 'start':
            if args.interval < 1 or not 0 <= args.retries <= 5:
                raise ValueError('interval >= 1; retries must be 0..5')
            folder = create_job(args.source, args.id, args.title, args.model, args.interval, args.retries,
                                args.vlm_model)
        else:
            folder = job_path(args.id)
        launch(folder, getattr(args, 'background', False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as error:
        # A new background task that cannot acquire the GPU lock must not remain queued forever.
        if args.action == '_worker' and 'folder' in locals() and (folder / 'status.json').exists():
            value = read_json(folder / 'status.json')
            if value.get('state') == 'queued':
                value.update(state='failed', error=str(error), updated_at=now())
                atomic_json(folder / 'status.json', value)
        print(f'任務未完成：{error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
