"""Publish directly authored (Codex / Claude Code) chapters without invoking local or remote models.

Usage: .venv/Scripts/python.exe editorial_publish.py --course <manifest.json>
The authored input is course_dir/editorial_chapters.json. All changed previous
deliverables are backed up; raw transcripts, visual evidence and manual edits
are retained. Job/model recipes are intentionally not rewritten by this tool.
"""
import argparse
import copy
from datetime import datetime, timezone
import html
import os
from pathlib import Path
import re
import shutil
import uuid

from build_reader import build
from course_config import load_course
from editorial_content import load_editorial, editorial_segments
from manual_edits import ManualEditsStore
from pipeline_common import atomic_json, digest, exclusive_lock, read_json
from traditional_chinese import normalize_transcript

ROOT = Path(__file__).resolve().parent


def stamp(value):
    seconds = int(value)
    return f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}'


def artifact_dir(course):
    return course.course_dir.parent if course.course_dir.name == 'course' else course.course_dir


def publish(manifest):
    course = load_course(manifest)
    out, target = course.course_dir, artifact_dir(course)
    with exclusive_lock(ROOT/'data/pipeline.lock'), exclusive_lock(out/'editorial-publication.lock'):
        raw_hash = digest(out/'transcript.json')
        raw = read_json(out/'transcript.json')
        evidence = read_json(out/'slide_evidence.json')
        doc = load_editorial(out, evidence)
        if doc is None:
            raise ValueError('No editorial_chapters.json: content must be authored before publication')
        editorial_hash = digest(out/'editorial_chapters.json')
        author = doc['author']
        visual_path = out/'visual_provenance.json'
        visual = read_json(visual_path) if visual_path.exists() else None
        if visual is not None and (not isinstance(visual, dict) or not isinstance(visual.get('method'), str) or not visual['method'].strip()):
            raise ValueError('Visual provenance must declare its actual method')
        if not course.media.is_file():
            raise FileNotFoundError(course.media)
        for occurrence in evidence:
            image = out/'slides'/occurrence['image']
            if not image.is_file():
                raise FileNotFoundError(image)
            course.url_for(image)
        # Existing display correction is a separate layer, not this author's
        # transcript verification. Preserve it and its manual-edit revision.
        corrected_path = out/'transcript.corrected.json'
        created_display = not corrected_path.exists()
        changes = []
        corrected = copy.deepcopy(raw) if created_display else read_json(corrected_path)
        if len(raw) != len(corrected) or any(a['start'] != b['start'] or a['end'] != b['end'] for a, b in zip(raw, corrected)):
            raise ValueError('Display transcript must retain all original timestamps and order')
        if created_display:
            if (out/'transcript.manual-edits.json').exists() or (out/'transcript.reading.json').exists():
                raise ValueError('Missing display base with existing reading/manual layer; resolve it before publication')
            normalize_transcript(corrected, changes)
        else:
            ManualEditsStore(out, course.id).snapshot()  # Refuse stale manual base before writes.
        outputs = [course.output_html, out/'reading_alignment.json', out/'coverage_report.json',
                   out/'authoring_provenance.json', out/'occurrence_notes.json',
                   target/'完整課程講義.md', target/'待核對清單.md', target/'review.json',
                   target/'review.html', target/'畫面來源對照.md']
        if created_display:
            outputs += [corrected_path, out/'transcript.corrections.json']
        backup = out/'backups'/('before-codex-editorial-'+uuid.uuid4().hex[:12])
        backup.mkdir(parents=True)
        previous = []
        for index, path in enumerate(outputs):
            if path.exists():
                name = f'{index:02}-{path.name}'
                shutil.copy2(path, backup/name)
                previous.append(dict(path=str(path), backup=name, sha256=digest(path)))
        atomic_json(backup/'manifest.json', dict(created_at=datetime.now(timezone.utc).isoformat(), files=previous))
        if created_display:
            atomic_json(corrected_path, corrected)
            atomic_json(out/'transcript.corrections.json', changes)
        flags = [dict(check, chapter=chapter['title'], kind='codex-source-review')
                 for chapter in doc['chapters'] for check in chapter.get('checks', [])]
        source_segments = editorial_segments(doc, evidence, corrected, lambda image: course.url_for(out/'slides'/image))
        appendix = [segment for segment in source_segments if segment.get('occurrence_id')]
        atomic_json(out/'occurrence_notes.json', appendix)
        atomic_json(target/'review.json', flags)
        lines = ['# '+doc['title'], '',
                 f'> {author} 依逐字稿與投影片證據整理，未逐句聽音覆核。', '',
                 '## 全課總覽', '', doc['overview'], '',
                 '[全部畫面與逐字稿來源對照](畫面來源對照.md)', '']
        for chapter in doc['chapters']:
            lines += [f'## {stamp(chapter["start"])}–{stamp(chapter["end"])}｜{chapter["title"]}', '', chapter['summary'], '']
            representative = next((e for e in evidence if e['start'] <= chapter['start'] < e['end']), evidence[0])
            image = os.path.relpath(out/'slides'/representative['image'], target).replace('\\', '/')
            lines += [f'![本章起始畫面]({image})', '']
            for paragraph in chapter['paragraphs']:
                ids = paragraph['source_ids']
                times = f'{stamp(raw[ids[0]]["start"])}–{stamp(raw[ids[-1]]["end"])}'
                lines += ['### '+paragraph['heading'], '', paragraph['text'], '',
                          f'> 來源：{times}；逐字稿片段 {ids[0]}–{ids[-1]}（原始編號由 0 起）。', '']
            if chapter.get('checks'):
                lines += ['### 本章待核對', '']
                lines += [f'- {stamp(check["time"])}｜{check["message"]}' for check in chapter['checks']]
                lines.append('')
        (target/'完整課程講義.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
        source_lines = ['# 全部畫面來源對照', '',
                        '> 保留每次出現、回頁與註記變化。以下文字為時間重疊逐字稿的機械對照，不是獨立撰寫的講義。', '']
        for segment, occurrence in zip(appendix, evidence):
            image = os.path.relpath(out/'slides'/occurrence['image'], target).replace('\\', '/')
            source_lines += [f'## {stamp(segment["start"])}–{stamp(segment["end"])}｜{segment["title"]}', '',
                             f'![來源畫面]({image})', '', segment['sections'][0]['text'], '']
        (target/'畫面來源對照.md').write_text('\n'.join(source_lines)+'\n', encoding='utf-8')
        disclosure = (f'本清單由 {author} 依逐字稿與投影片證據整理，未逐句聽音覆核；'
                      '來源覆蓋驗證不等於語意或數值全部正確。畫面區間沿用既有抽樣邊界，短暫切頁仍可能漏取。')
        review = ['# 待核對清單', '', disclosure, '']
        review += [f'- {stamp(flag["time"])}｜{flag["chapter"]}｜{flag["message"]}' for flag in flags]
        if not flags:
            review.append('- 未列出特定疑點；仍需抽查術語、數值及公式，不能視為人工聽音確認。')
        (target/'待核對清單.md').write_text('\n'.join(review)+'\n', encoding='utf-8')
        href = os.path.relpath(course.output_html, target).replace('\\', '/')
        (target/'review.html').write_text(
            '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>'+html.escape(author)+' 講義待核對清單</title><style>body{max-width:60rem;margin:3rem auto;padding:0 1rem;font:18px/1.8 system-ui}li{margin:1rem 0}</style>'
            f'<a href="{html.escape(href, quote=True)}">開啟課程講義</a><h1>待核對清單</h1><p>{html.escape(disclosure)}</p><ul>'
            + ''.join('<li>'+html.escape(line[2:])+'</li>' for line in review if line.startswith('- '))+'</ul></html>', encoding='utf-8')
        build(course)
        if digest(out/'transcript.json') != raw_hash or digest(out/'editorial_chapters.json') != editorial_hash:
            raise RuntimeError('Authored input or original transcript changed during publication')
        report = dict(occurrences=len(evidence), preserved_occurrences=len(appendix),
                      transcript_segments=len(raw), assigned_segments=len(raw), unassigned_segments=[], duplicate_assignments=0,
                      chapters=len(doc['chapters']), editorial_paragraphs=sum(len(c['paragraphs']) for c in doc['chapters']),
                      duration_seconds=evidence[-1]['end'], raw_transcript_sha256=raw_hash, raw_transcript_unchanged=True,
                      notes_generation=f'{author} direct authoring from transcript and visual evidence',
                      quality_flags=len(flags), semantic_accuracy_verified=False, audio_verified=False)
        atomic_json(out/'coverage_report.json', report)
        provenance = dict(schema=1, author=author, authored_input='editorial_chapters.json',
                          editorial_sha256=editorial_hash, raw_transcript_sha256=raw_hash,
                          published_at=datetime.now(timezone.utc).isoformat(), backup=str(backup),
                          local_model_inference_used_for_this_authoring=False,
                          visual_analysis=visual['method'] if visual else 'Previously completed local VLM/OCR evidence retained',
                          transcript_display=('Only Traditional Chinese character normalization of raw ASR; no new semantic corrections'
                                              if created_display else 'Existing correction/reading/manual layers retained; not re-verified by this authoring run'),
                          source_appendix='Mechanically assembled timed excerpts and chapter references, not independently authored mini-lessons',
                          audio_verified=False, semantic_accuracy_verified=False)
        if visual is not None:
            provenance['visual_provenance_sha256'] = digest(visual_path)
        atomic_json(out/'authoring_provenance.json', provenance)
        print(f'Published {course.output_html}\nChapters: {report["chapters"]}; source occurrences: {len(appendix)}; backup: {backup}')
        return report


def audit_publication(manifest):
    """Read-only audit of the current authored input, reader and provenance."""
    course = load_course(manifest)
    out, target = course.course_dir, artifact_dir(course)
    evidence = read_json(out/'slide_evidence.json')
    doc = load_editorial(out, evidence)
    if doc is None:
        raise ValueError('No editorial chapters to audit')
    provenance = read_json(out/'authoring_provenance.json')
    visual_path = out/'visual_provenance.json'
    if visual_path.exists() and provenance.get('visual_provenance_sha256') != digest(visual_path):
        raise ValueError('Published visual provenance does not match current inputs')
    if not visual_path.exists() and provenance.get('visual_provenance_sha256'):
        raise ValueError('Published visual provenance is missing')
    if (provenance.get('author') != doc['author'] or
            provenance.get('editorial_sha256') != digest(out/'editorial_chapters.json') or
            provenance.get('raw_transcript_sha256') != digest(out/'transcript.json') or
            provenance.get('local_model_inference_used_for_this_authoring') is not False):
        raise ValueError('Published authoring provenance does not match current inputs')
    payload = course.output_html.read_text(encoding='utf-8')
    match = re.search(r'<script type="application/json" id="course-data">(.*?)</script>', payload, re.S)
    if match is None:
        raise ValueError('Reader is missing its published course data')
    import json
    data = json.loads(match.group(1))
    expected = editorial_segments(doc, evidence, read_json(out/'transcript.corrected.json'),
                                 lambda image:course.url_for(out/'slides'/image))
    if data['segments'] != expected or data != read_json(out/'reading_alignment.json'):
        raise ValueError('Reader content differs from the current authored chapters or source occurrences')
    for segment in expected:
        if segment['image'] and not (course.web_root/segment['image']).is_file():
            raise FileNotFoundError(segment['image'])
    for name in ['完整課程講義.md', '畫面來源對照.md', '待核對清單.md', 'review.json', 'review.html']:
        if not (target/name).is_file():
            raise FileNotFoundError(target/name)
    report = read_json(out/'coverage_report.json')
    if (report.get('raw_transcript_sha256') != provenance['raw_transcript_sha256'] or
            report.get('preserved_occurrences') != len(evidence) or
            report.get('assigned_segments') != len(data['transcript'])):
        raise ValueError('Published coverage report does not match current sources')
    if (ROOT/'reader.js').read_text(encoding='utf-8') not in payload:
        raise ValueError('Reader JavaScript has changed; rebuild the reader before delivery')
    return dict(course_id=course.id, chapters=len(doc['chapters']),
                occurrences=len(evidence), transcript_segments=len(data['transcript']),
                raw_transcript_unchanged=True, author=doc['author'], metadata_valid=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='Read-only validation of an already published course')
    args = parser.parse_args()
    if args.check:
        print(audit_publication(args.course))
    else:
        publish(args.course)
