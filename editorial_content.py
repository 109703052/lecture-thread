"""Validate directly authored chapters and build source-transparent reader data.

This module never invokes a model or rewrites the timed transcript.  Chapter
source IDs are an editorial provenance claim, not word-level audio alignment.
"""
import math
from pathlib import Path

from pipeline_common import digest, read_json


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Editorial {field} must be non-empty text')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_editorial(doc, transcript, duration, raw_sha256):
    if not isinstance(doc, dict) or doc.get('schema') != 1 or doc.get('author') != 'Codex':
        raise ValueError('Editorial schema must be 1 and author must be Codex')
    if doc.get('raw_transcript_sha256') != raw_sha256:
        raise ValueError('Editorial raw transcript hash changed')
    for field in ('course_date', 'title', 'overview'):
        _text(doc.get(field), field)
    chapters = doc.get('chapters')
    if not isinstance(chapters, list) or not chapters:
        raise ValueError('Editorial chapters must be a non-empty list')
    last = 0.0
    assigned = []
    for chapter in chapters:
        for field in ('title', 'summary'):
            _text(chapter.get(field), field)
        a, b = chapter.get('start'), chapter.get('end')
        if not (_number(a) and _number(b) and abs(a-last) < .001 and 0 <= a < b <= duration+.001):
            raise ValueError('Editorial chapter intervals must continuously cover the course')
        last = b
        paragraphs = chapter.get('paragraphs')
        if not isinstance(paragraphs, list) or not paragraphs:
            raise ValueError('Each editorial chapter needs paragraphs')
        previous = a
        for paragraph in paragraphs:
            for field in ('heading', 'text'):
                _text(paragraph.get(field), field)
            when = paragraph.get('time')
            if not (_number(when) and previous <= when < b):
                raise ValueError('Editorial paragraph time is outside its chapter or out of order')
            previous = when
            ids = paragraph.get('source_ids')
            if (not isinstance(ids, list) or not ids or
                    any(type(i) is not int or not 0 <= i < len(transcript) for i in ids)):
                raise ValueError('Editorial paragraph source IDs are invalid')
            if ids != sorted(set(ids)):
                raise ValueError('Editorial paragraph source IDs must be ordered and unique')
            # A paragraph may cite an ASR sentence crossing the chapter edge.
            if any(transcript[i]['end'] <= a or transcript[i]['start'] >= b for i in ids):
                raise ValueError('Editorial sources must overlap their chapter')
            assigned.extend(ids)
        checks = chapter.get('checks', [])
        if not isinstance(checks, list):
            raise ValueError('Editorial checks must be a list')
        for check in checks:
            _text(check.get('message'), 'check message')
            ids, when = check.get('source_ids'), check.get('time')
            if (not _number(when) or not 0 <= when <= duration or not isinstance(ids, list)
                    or any(type(i) is not int or not 0 <= i < len(transcript) for i in ids)):
                raise ValueError('Editorial check source mapping is invalid')
    if abs(last-duration) >= .001:
        raise ValueError('Editorial chapters must end at the course duration')
    if assigned != list(range(len(transcript))):
        raise ValueError('Editorial paragraphs must assign every transcript segment exactly once in order')
    return doc


def load_editorial(course_dir, evidence=None):
    course_dir = Path(course_dir)
    path = course_dir/'editorial_chapters.json'
    if not path.is_file():
        return None
    evidence = evidence or read_json(course_dir/'slide_evidence.json')
    raw = read_json(course_dir/'transcript.json')
    return validate_editorial(read_json(path), raw, evidence[-1]['end'], digest(course_dir/'transcript.json'))


def editorial_segments(doc, evidence, transcript, image_url):
    duration = evidence[-1]['end']
    segments = [dict(title='全課總覽', region='Codex 直接撰寫講義', start=0, end=duration,
                     image=None, caution='依逐字稿與投影片證據整理；未逐句聽音覆核。',
                     alignment='editorial-source-ids', sections=[dict(
                         heading=doc['title'], text=doc['overview'], time=0, end=duration,
                         source_ids=list(range(len(transcript))))])]
    for chapter in doc['chapters']:
        sections = []
        for i, paragraph in enumerate(chapter['paragraphs']):
            end = chapter['paragraphs'][i+1]['time'] if i+1 < len(chapter['paragraphs']) else chapter['end']
            sections.append(dict(paragraph, end=end))
        representative = next((e for e in evidence if e['start'] <= chapter['start'] < e['end']), evidence[0])
        segments.append(dict(title=chapter['title'], region='Codex 直接撰寫講義',
                             start=chapter['start'], end=chapter['end'], image=image_url(representative['image']),
                             sections=sections, caution='；'.join(c['message'] for c in chapter.get('checks', [])),
                             alignment='editorial-source-ids', summary=chapter['summary']))
    # Retain every occurrence, including repeated/annotated screens.  This is a
    # mechanical source appendix, not thousands of newly authored mini-lessons.
    for occurrence in evidence:
        a, b = occurrence['start'], occurrence['end']
        chapter = next((c for c in doc['chapters'] if c['start'] <= a < c['end']), doc['chapters'][-1])
        ids = [i for i, row in enumerate(transcript) if row['start'] < b and row['end'] > a]
        excerpt = '\n'.join(transcript[i]['text'] for i in ids)
        text = f'對應講義章節：{chapter["title"]}。\n'
        text += ('以下為此畫面時間重疊的逐字稿顯示文字，僅作來源對照，不是獨立撰寫的講義：\n'+excerpt
                 if ids else '此短暫畫面沒有時間重疊語句；保留畫面與章節引用，不據此判定講師跳過內容。')
        segments.append(dict(title=f'來源畫面 {occurrence["occurrence_id"]}｜{occurrence["title"]}',
                             region='來源對照（全部畫面）', start=a, end=b, image=image_url(occurrence['image']),
                             caution='', alignment='source-time-overlap', occurrence_id=occurrence['occurrence_id'],
                             sections=[dict(heading='投影片與逐字稿來源對照', text=text,
                                            time=a, end=b, source_ids=ids)]))
    return segments
