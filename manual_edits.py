"""Versioned manual transcript corrections. Original and AI transcripts are read-only."""
import hashlib
import json
import os
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'lecturethread.manual-transcript-edits.v1'


class EditError(Exception):
    def __init__(self, status, message, snapshot=None):
        super().__init__(message)
        self.status, self.snapshot = status, snapshot


@contextmanager
def file_lock(path):
    # Coordinate separate preview processes as well as threads, without services.
    with path.open('a+b') as lock:
        if not path.stat().st_size:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


class ManualEditsStore:
    def __init__(self, course, youtube_id):
        self.course = Path(course).resolve()
        self.youtube_id = youtube_id
        self.path = self.course / 'transcript.manual-edits.json'
        self.lock = threading.Lock()

    def _read(self):
        base = (self.course / 'transcript.corrected.json').read_bytes()
        transcript = json.loads(base)
        base_revision = hashlib.sha256(base).hexdigest()
        edits, revision = {}, 'missing'
        if self.path.exists():
            raw = self.path.read_bytes()
            try:
                doc = json.loads(raw)
            except (ValueError, UnicodeError) as error:
                raise EditError(409, '本地修訂 JSON 已損壞，請先核對檔案；未覆寫任何資料。') from error
            revision = hashlib.sha256(raw).hexdigest()
            if not isinstance(doc, dict) or doc.get('schema') != SCHEMA or doc.get('youtube_id') != self.youtube_id:
                raise EditError(409, '本地修訂檔的課程或格式不符，未寫入任何變更。')
            if doc.get('transcript_revision') != base_revision:
                raise EditError(409, 'AI 校正版已更新，請先核對本地修訂檔再繼續；原修訂未覆寫。')
            if not isinstance(doc.get('edits'), list):
                raise EditError(409, '本地修訂清單格式損壞；未覆寫任何資料。')
            for edit in doc['edits']:
                if not isinstance(edit, dict) or not {'segment_id', 'original', 'corrected'} <= edit.keys():
                    raise EditError(409, '本地修訂欄位不完整；未覆寫任何資料。')
                index = edit['segment_id']
                if (type(index) is not int or not 0 <= index < len(transcript)
                        or edit['original'] != transcript[index]['text']
                        or not isinstance(edit['corrected'], str) or not edit['corrected'].strip()
                        or str(index) in edits):
                    raise EditError(409, '本地修訂內容與逐字稿不符，請先核對檔案。')
                edits[str(index)] = {k: v for k, v in edit.items() if k != 'segment_id'}
        return {'schema': SCHEMA, 'youtube_id': self.youtube_id,
                'transcript_revision': base_revision, 'revision': revision, 'edits': edits}, transcript

    def snapshot(self):
        with self.lock, file_lock(self.course / '.transcript-manual-edits.lock'):
            return self._read()[0]

    def save(self, request):
        with self.lock, file_lock(self.course / '.transcript-manual-edits.lock'):
            snapshot, transcript = self._read()
            if request.get('transcript_revision') != snapshot['transcript_revision']:
                raise EditError(409, '此閱讀頁使用舊版 AI 校正版，請重建並重新開啟閱讀頁。')
            if request.get('revision') != snapshot['revision']:
                raise EditError(409, '其他分頁或程式已更新本地修訂；請比較最新文字後再儲存。', snapshot)
            index, text = request.get('segment_id'), request.get('corrected')
            if type(index) is not int or not 0 <= index < len(transcript):
                raise EditError(400, '逐字稿片段不存在。')
            if not isinstance(text, str) or not text.strip() or len(text) > 20000:
                raise EditError(400, '逐字稿必須有文字，且每句不得超過 20000 字。')
            text = text.strip()
            base = transcript[index]
            if text == base['text']:
                snapshot['edits'].pop(str(index), None)
            else:
                snapshot['edits'][str(index)] = {'original': base['text'], 'corrected': text,
                    'start': base['start'], 'end': base['end'],
                    'updated_at': datetime.now(timezone.utc).isoformat()}
            doc = {k: snapshot[k] for k in ('schema', 'youtube_id', 'transcript_revision')}
            doc['save_id'] = uuid.uuid4().hex  # A revert also invalidates older tabs (ABA).
            doc['edits'] = [dict(segment_id=int(i), **edit)
                            for i, edit in sorted(snapshot['edits'].items(), key=lambda pair: int(pair[0]))]
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.course,
                        prefix='.manual-edits-', suffix='.tmp', delete=False) as file:
                    temporary = Path(file.name)
                    json.dump(doc, file, ensure_ascii=False, indent=2)
                    file.write('\n')
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
            return self._read()[0]
