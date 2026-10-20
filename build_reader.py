"""Export the reading-first view with explicit paragraph-to-transcript mappings."""
import argparse, hashlib, html as html_module, json
from pathlib import Path
from manual_edits import ManualEditsStore
from course_config import load_course
ROOT=Path(__file__).resolve().parent

def align(start,end,transcript):
    # Time alignment is transparent, not a claim of semantic/word-level matching.
    return [i for i,t in enumerate(transcript) if t['start']<end and t['end']>start]

def build(course=None):
    course=load_course(course) if not hasattr(course, 'course_dir') else course
    OUT=course.course_dir
    notes=json.loads((OUT/'authored_notes.json').read_text(encoding='utf-8'))
    evidence=json.loads((OUT/'slide_evidence.json').read_text(encoding='utf-8'))
    tx=json.loads((OUT/'transcript.corrected.json').read_text(encoding='utf-8'))
    if len(notes)!=len(evidence) or not evidence:
        raise ValueError('Notes and evidence must contain the same non-zero number of occurrences')
    segments=[]
    overview=dict(title='全課總覽',region='總覽',start=0,end=evidence[-1]['end'],image=None,caution='',sections=[])
    for n,e in zip(notes,evidence):
        overview['sections'].append(dict(heading=n['title'],text=n['points'],time=e['start'],end=e['end'],source_ids=align(e['start'],e['end'],tx)))
    segments.append(overview)
    for n,e in zip(notes,evidence):
        sections=[]
        for i,p in enumerate(n['lesson']):
            end=n['lesson'][i+1]['time'] if i+1<len(n['lesson']) else e['end']
            sections.append(dict(p,end=end,source_ids=align(p['time'],end,tx)))
        segments.append(dict(title=n['title'],region=n['region'],start=e['start'],end=e['end'],
            image=course.url_for(OUT/'slides'/e['image']),sections=sections,caution=n['caution']))
    video_src=course.url_for(course.media)
    if not course.media.is_file():
        raise FileNotFoundError(f'Media missing: {course.media}. For the public demo, run examples/demo/create_demo.py first.')
    for segment in segments:
        if segment['image'] and not (course.web_root/segment['image']).is_file():
            raise FileNotFoundError(segment['image'])
    data=dict(segments=segments,transcript=tx,alignment='source-time-overlap',youtube_id=course.id,
              course_id=course.id,course_title=course.title,course_description=course.description,
              youtube_source_id=course.youtube_id,video_src=video_src,media_kind=course.media_kind,
              transcript_revision=hashlib.sha256((OUT/'transcript.corrected.json').read_bytes()).hexdigest(),
              manual_edits=ManualEditsStore(OUT,course.id).snapshot())
    for segment in segments:
        for section in segment['sections']:
            if not 0<=section['time']<=section['end']<=evidence[-1]['end']:
                raise ValueError('Reading section is outside the course timeline')
            if section['source_ids']!=align(section['time'],section['end'],tx):
                raise ValueError('Reading section source mapping is invalid')
    output=course.output_html
    output.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    html='''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>COURSE_TITLE｜LectureThread／課脈</title><style>/*READER_CSS*/</style></head>
<body data-pane="notes"><header><strong>LectureThread／課脈</strong><div class="toolbar"><span class="course-title" title="COURSE_DESCRIPTION">COURSE_TITLE</span><a class="upstream-credit" href="https://github.com/drpwchen/lecture-to-notes" target="_blank" rel="noopener noreferrer">基於 lecture-to-notes · drpwchen</a><span id="layout-storage-status" role="status" hidden></span><div class="reader-controls"><button id="toggle-nav" aria-expanded="false" aria-controls="chapter-nav">章節</button><button id="toggle-transcript" aria-expanded="false" aria-controls="sources">展開逐字稿</button></div></div></header>
<p class="course-description">COURSE_DESCRIPTION</p><div class="layout"><div id="chapter-dock"><button id="chapter-tab" aria-label="展開章節導航" aria-controls="chapter-nav" aria-expanded="false">章節</button><nav id="chapter-nav" hidden aria-label="課程章節"><h2>章節</h2><input id="search" type="search" aria-label="搜尋章節與講義" placeholder="搜尋章節與講義"><div id="segments"></div></nav></div>
<main id="main" aria-label="課程總整理" tabindex="-1"><article class="reading" id="reading"></article></main>
<div id="transcript-divider" hidden role="separator" tabindex="0" aria-label="調整逐字稿高度" aria-controls="sources" aria-orientation="horizontal" aria-valuemin="18" aria-valuemax="70" aria-valuenow="34" title="上下拖曳調整逐字稿高度；方向鍵微調，Home 恢復"><span></span></div>
<aside id="sources" hidden aria-label="校正逐字稿"><div class="transcript-header"><button id="close-transcript">收起逐字稿</button><h2>逐字稿對照</h2><p>捲動或點選講義，標亮對應原句。依講解時間區間對照，跨段語句可能重複出現。</p><span id="status" aria-live="polite"></span><span id="speaking-status" role="status"></span><button class="follow" id="follow" aria-pressed="true">跟隨閱讀：開</button><button id="export-edits">匯出手動修訂</button><button id="reload-edits">重新連線</button><p class="edit-storage-note" id="edit-storage-status" role="status">正式修訂以本地檔案為準，正在連線…</p></div><div id="transcript"></div></aside></div>
<dialog id="slide-dialog" aria-label="放大投影片"><button id="close-slide">關閉放大</button><div class="slide-detail" id="detail-image"></div></dialog>
<script type="application/json" id="course-data">__COURSE_PAYLOAD__</script><script>/*READER_JS*/</script></body></html>'''
    html=html.replace('COURSE_TITLE',html_module.escape(course.title)).replace('COURSE_DESCRIPTION',html_module.escape(course.description,quote=True))
    html=html.replace('/*READER_CSS*/',(ROOT/'reader.css').read_text(encoding='utf-8'),1).replace('/*READER_JS*/',(ROOT/'reader.js').read_text(encoding='utf-8'),1).replace('__COURSE_PAYLOAD__',payload,1)
    output.write_text(html,encoding='utf-8')
    (OUT/'reading_alignment.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    assert 'preload="none"' in html
    print(f"Built {output}: {len(segments)} sections, {sum(len(s['sections']) for s in segments[1:])} lesson paragraphs, {len(tx)} transcript lines.")
    return data
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course',type=Path,help='Course JSON manifest (default: course.local.json if present, otherwise courses/demo.json)')
    args=parser.parse_args()
    try:build(args.course)
    except (ValueError,OSError,KeyError) as error:parser.error(str(error))
