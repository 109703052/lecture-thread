"""Export the reading-first view with explicit paragraph-to-transcript mappings."""
import argparse, hashlib, html as html_module, json, shutil
from pathlib import Path
from manual_edits import ManualEditsStore
from reading_layer import load_reading_paragraphs
from bilingual_layer import load_translations
from course_config import load_course
from editorial_content import load_editorial, editorial_segments
ROOT=Path(__file__).resolve().parent

def align(start,end,transcript):
    # Time alignment is transparent, not a claim of semantic/word-level matching.
    return [i for i,t in enumerate(transcript) if t['start']<end and t['end']>start]

def load_reading_transcript(path, transcript, revision):
    """Optional editorial display layer; never changes the timed source or edit base."""
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding='utf-8'))
    if doc.get('schema') == 2:
        return {}
    if doc.get('schema') != 1 or doc.get('base_sha256') != revision:
        raise ValueError('Reading transcript base changed; review transcript.reading.json before rebuilding')
    rows = doc.get('segments', [])
    if len(rows) != len(transcript):
        raise ValueError('Reading transcript must preserve every source segment')
    result = {}
    for i, row in enumerate(rows):
        if (row.get('segment_id') != i or row.get('original') != transcript[i]['text']
                or not isinstance(row.get('text'), str) or not row['text'].strip()
                or type(row.get('paragraph_end')) is not bool):
            raise ValueError(f'Invalid reading transcript source mapping at {i}')
        result[str(i)] = row
    return result


def apply_transcript_review(path, transcript, revision):
    """Suppress resolved display warnings without changing the edit base."""
    if not path.is_file():
        return transcript
    doc = json.loads(path.read_text(encoding='utf-8'))
    if doc.get('schema') != 1 or doc.get('base_sha256') != revision:
        raise ValueError('Transcript review base changed; review transcript.reviewed.json')
    ids = doc.get('reviewed_segment_ids')
    if (not isinstance(ids, list) or any(type(i) is not int or not 0 <= i < len(transcript) for i in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('Invalid reviewed transcript segment IDs')
    reviewed = set(ids)
    return [{k: v for k, v in row.items() if k != 'review_note' or i not in reviewed}
            for i, row in enumerate(transcript)]


def build(course=None, *, publish_dir=None, audio_url=None):
    course=load_course(course) if not hasattr(course, 'course_dir') else course
    OUT=course.course_dir
    evidence=json.loads((OUT/'slide_evidence.json').read_text(encoding='utf-8'))
    tx=json.loads((OUT/'transcript.corrected.json').read_text(encoding='utf-8'))
    editorial=load_editorial(OUT,evidence)
    if editorial:
        segments=editorial_segments(editorial,evidence,tx,lambda image:course.url_for(OUT/'slides'/image))
    else:
        notes=json.loads((OUT/'authored_notes.json').read_text(encoding='utf-8'))
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
    display_title=editorial['title'] if editorial else course.title
    data=dict(segments=segments,transcript=tx,alignment='editorial-source-ids-with-occurrence-appendix' if editorial else 'source-time-overlap',youtube_id=course.id,
              course_id=course.id,course_title=display_title,course_description=course.description,
              youtube_source_id=course.youtube_id,video_src=video_src,media_kind=course.media_kind,media_duration=evidence[-1]['end'],
              transcript_revision=hashlib.sha256((OUT/'transcript.corrected.json').read_bytes()).hexdigest(),
              manual_edits=ManualEditsStore(OUT,course.id).snapshot())
    data['reading_transcript'] = load_reading_transcript(OUT/'transcript.reading.json', tx, data['transcript_revision'])
    data['reading_paragraphs'] = load_reading_paragraphs(OUT/'transcript.reading.json', tx, data['transcript_revision'])
    data['translations'] = load_translations(OUT/'transcript.translation.json', tx, data['transcript_revision'])
    data['transcript'] = apply_transcript_review(OUT/'transcript.reviewed.json', tx, data['transcript_revision'])
    for segment in segments:
        for section in segment['sections']:
            if not 0<=section['time']<=section['end']<=evidence[-1]['end']:
                raise ValueError('Reading section is outside the course timeline')
            if segment.get('alignment')!='editorial-source-ids' and section['source_ids']!=align(section['time'],section['end'],tx):
                raise ValueError('Reading section source mapping is invalid')
    output=course.output_html
    if publish_dir is not None:
        from urllib.parse import urlsplit
        if not course.youtube_id:
            raise ValueError('Web publication requires a YouTube video ID')
        if not audio_url or (urlsplit(audio_url).scheme != 'https' and audio_url != 'audio.m4a'):
            raise ValueError('Audio URL must use HTTPS, or audio.m4a for a portable preview')
        publish_dir=Path(publish_dir).resolve()
        publish_dir.mkdir(parents=True,exist_ok=True)
        for segment in segments:
            if segment['image']:
                source=course.web_root/segment['image']
                name=hashlib.sha256(source.read_bytes()).hexdigest()[:24]+source.suffix
                destination=publish_dir/'slides'/name
                destination.parent.mkdir(exist_ok=True)
                shutil.copyfile(source,destination)
                segment['image']='slides/'+name
        data.update(read_only=True,video_provider='youtube',video_src='',audio_src=audio_url)
        output=publish_dir/'index.html'
    output.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    html='''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>COURSE_TITLE｜LectureThread／課脈</title><style>/*READER_CSS*/</style></head>
<body data-pane="notes"><header><strong>LectureThread／課脈</strong><span class="course-title" title="COURSE_DESCRIPTION">COURSE_TITLE</span><div id="reading-head"></div><div class="toolbar"><details class="course-info"><summary>課程資訊</summary><div class="course-info-body"><strong>COURSE_TITLE</strong><p class="course-description">COURSE_DESCRIPTION</p><a class="upstream-credit" href="https://github.com/drpwchen/lecture-to-notes" target="_blank" rel="noopener noreferrer">基於 lecture-to-notes · drpwchen</a></div></details><span id="layout-storage-status" role="status" hidden></span><div class="reader-controls"><button id="toggle-nav" aria-expanded="false" aria-controls="chapter-nav">章節</button><button id="toggle-transcript" aria-expanded="false" aria-controls="sources">展開逐字稿</button></div></div></header>
<div class="layout"><div id="chapter-dock"><button id="chapter-tab" aria-label="展開章節導航" aria-controls="chapter-nav" aria-expanded="false">章節</button><nav id="chapter-nav" hidden inert aria-label="課程章節"><div class="nav-heading"><h2>章節</h2><button id="close-nav" aria-label="關閉章節選單">關閉</button></div><input id="search" type="search" aria-label="搜尋章節與講義" placeholder="搜尋章節與講義"><div id="segments"></div><details id="source-nav"><summary>查看原始畫面</summary><p>依影片時間查閱投影片與手寫變化。</p><input id="source-search" type="search" aria-label="搜尋原始畫面" placeholder="搜尋畫面或時間"><div id="source-segments"></div><p id="source-count" role="status"></p><button id="source-more" hidden>顯示更多畫面</button></details></nav></div>
<main id="main" aria-label="課程總整理" tabindex="-1"><article class="reading" id="reading"></article></main>
<div id="transcript-divider" hidden role="separator" tabindex="0" aria-label="調整逐字稿高度" aria-controls="sources" aria-orientation="horizontal" aria-valuemin="18" aria-valuemax="70" aria-valuenow="34" title="上下拖曳調整逐字稿高度；方向鍵微調，Home 恢復"><span></span></div>
<aside id="sources" hidden aria-label="校正逐字稿"><div class="transcript-header"><div class="transcript-heading"><h2>逐字稿</h2><span id="status" aria-live="polite"></span><span id="speaking-status" role="status"></span></div><div class="transcript-actions"><button class="follow" id="follow" aria-pressed="true">跟隨閱讀：開</button><details class="transcript-options"><summary>說明與修訂</summary><div class="transcript-options-body"><p>點文字返回講義；「聽這段」播放完整分組。段落淡底是講義來源，綠色底線跟隨目前播放的文字。</p><p>閱讀版補上標點、整理口語銜接，保留每句原始時間與待核對標記。未提供閱讀版的課程依時間分組。展開「逐句校訂」可查看原句、聽單句或修改文字；人工修訂優先顯示。</p><button id="export-edits">匯出手動修訂</button></div></details><div class="edit-connection"><button id="reload-edits">重新連線</button><span class="edit-storage-note" id="edit-storage-status" role="status">正在連線本地修訂服務…</span></div><button id="close-transcript">收起</button></div></div><div id="transcript"></div></aside></div>
<dialog id="slide-dialog" aria-label="放大投影片"><button id="close-slide">關閉放大</button><div class="slide-detail" id="detail-image"></div></dialog>
<script type="application/json" id="course-data">__COURSE_PAYLOAD__</script><script>/*READER_JS*/</script></body></html>'''
    if publish_dir is not None:
        html=html.replace('說明與修訂','閱讀說明').replace('或修改文字','').replace('逐句校訂','逐句來源')
        html=html.replace('<button id="export-edits">匯出手動修訂</button>','')
        html=html.replace('<div class="edit-connection"><button id="reload-edits">重新連線</button><span class="edit-storage-note" id="edit-storage-status" role="status">正在連線本地修訂服務…</span></div>','')
    if data['reading_paragraphs']:
        html=html.replace('<h2>逐字稿</h2>', '<h2>閱讀稿</h2>').replace('aria-label="校正逐字稿"','aria-label="閱讀稿與校訂原話"')
        if publish_dir is None:
            html=html.replace('閱讀版補上標點、整理口語銜接，保留每句原始時間與待核對標記。未提供閱讀版的課程依時間分組。展開「逐句校訂」可查看原句、聽單句或修改文字；人工修訂優先顯示。',
                              '預設閱讀稿整理口語與重複，每段保留來源時間。滑鼠移到句子上（觸控為點一下）可看對應的校訂原話；「查看校訂原話」可聽單句及校字；儲存只修改原話，閱讀稿另存。原話變動後，該段暫時顯示最新原話，待閱讀稿重新核對。')
    html=html.replace('COURSE_TITLE',html_module.escape(display_title)).replace('COURSE_DESCRIPTION',html_module.escape(course.description,quote=True))
    html=html.replace('/*READER_CSS*/',(ROOT/'reader.css').read_text(encoding='utf-8'),1).replace('/*READER_JS*/',(ROOT/'reader.js').read_text(encoding='utf-8'),1).replace('__COURSE_PAYLOAD__',payload,1)
    output.write_text(html,encoding='utf-8')
    if publish_dir is None:
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
