"""Build per-occurrence evidence + upstream reading view from authored CS notes.
No synthesis API is called: --notes is an explicitly authored JSON artifact.
"""
import argparse, hashlib, json, math, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def assign_segments(segments, intervals):
    result=[[] for _ in intervals]
    for idx,s in enumerate(segments):
        start,end=float(s['start']),float(s['end'])
        overlaps=[max(0,min(end,b)-max(start,a)) for a,b in intervals]
        if max(overlaps)>0:
            owner=max(range(len(intervals)),key=lambda n:overlaps[n])
        else:
            owner=min(range(len(intervals)),key=lambda n:abs(start-intervals[n][0]))
        result[owner].append(idx)
    return result

def stamp(sec):
    sec=int(sec);return f'{sec//60:02}:{sec%60:02}'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('course',type=Path);ap.add_argument('--video',required=True,type=Path);ap.add_argument('--notes',required=True,type=Path);ap.add_argument('--name',required=True);args=ap.parse_args()
    out=args.course.resolve();video=args.video.resolve()
    duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(video)],text=True))
    transcript_path=out/'transcript.json';before=hashlib.sha256(transcript_path.read_bytes()).hexdigest()
    tx=json.loads(transcript_path.read_text(encoding='utf-8-sig'))
    frames=json.loads((out/'slides/timestamps.json').read_text(encoding='utf-8-sig'))
    ground=json.loads((out/'slides_grounded.json').read_text(encoding='utf-8-sig'))
    notes=json.loads(args.notes.read_text(encoding='utf-8-sig'))
    corrected_path=out/'transcript.corrected.json'
    reading=json.loads(corrected_path.read_text(encoding='utf-8-sig')) if corrected_path.exists() else tx
    assert len(reading)==len(tx)
    for original,reviewed in zip(tx,reading):
        assert original['start']==reviewed['start'] and original['end']==reviewed['end'], 'Correction must retain source timestamps'
    assert len(frames)==len(notes),'Each occurrence needs authored notes'
    intervals=[(float(f['first_ts']),float(frames[i+1]['first_ts']) if i+1<len(frames) else duration) for i,f in enumerate(frames)]
    owners=assign_segments(tx,intervals)
    plan=[];evidence=[]
    for i,(frame,note,(start,end)) in enumerate(zip(frames,notes,intervals)):
        raw=next(s for s in ground if s['filename']==frame['filename'])
        inherited=raw.get('dedup',{}).get('superseded_by')
        model=next((s for s in ground if s['filename']==inherited),raw)
        overlaps=[j for j,s in enumerate(tx) if float(s['end'])>start and float(s['start'])<end]
        context=[j for j,s in enumerate(tx) if float(s['end'])>max(0,start-20) and float(s['start'])<min(duration,end+20) and j not in overlaps]
        plan.append(dict(seg=i+1,start=int(start),end=math.ceil(end),slug=f'slide{i+1:02}',title_zh=note['title'],region=note['region'],type='lecture'))
        evidence.append(dict(occurrence_id=i+1,start=start,end=end,image=frame['filename'],title=note['title'],ocr=raw.get('ocr'),vlm_signals=model.get('vlm_signals'),model_shared_from=inherited,primary_transcript_ids=owners[i],overlapping_transcript_ids=overlaps,context_only_ids=context,transcript=[dict(id=j,**tx[j]) for j in overlaps],timing_precision='2-second sampling; boundaries are estimates, not frame-accurate'))
    (out/'seg_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'slide_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copy2(video,out/'full.mp4')
    subprocess.run([sys.executable,str(ROOT/'run.py'),'scripts/build_single_talk_web.py',str(out),'--plan',str(out/'seg_plan.json'),'--name',args.name,'--force'],check=True)
    docs=[]
    for i,(frame,note,row) in enumerate(zip(frames,notes,plan)):
        shutil.copy2(out/'slides'/frame['filename'],out/'figures'/frame['filename'])
        start,end=intervals[i]
        lines=[f"# {i+1:02}｜{note['title']}",'',f"> 畫面區間 {stamp(start)}–{stamp(end)}；依兩秒抽樣估計。講義依投影片與講稿重述；銜接解釋為整理，非逐句引言。",'',f"![[{frame['filename']}|1000]]",'']
        if note.get('lesson'):
            for section in note['lesson']:
                sec=section['time']
                assert 0<=sec<=duration
                lines += [f"## {section['heading']}",'',f"- `(V1 {stamp(sec)})` {section['text']}",'']
        else:
            lines += ['## 本頁重點','',f"`(V1 {stamp(start)})` {note['points']}",'','## 講解','']
            for sec,text in note['explanation']:
                assert 0<=sec<=duration
                lines.append(f"- `(V1 {stamp(sec)})` {text}")
        if note['caution']:
            lines+=['','## 補充與待核對','',f"- `(V1 {stamp(start)})` {note['caution']}"]
        text='\n'.join(lines)+'\n'
        (out/'L3'/f'L3_seg{i+1:02}_slide{i+1:02}.md').write_text(text,encoding='utf-8')
        docs.append(text.replace(f'![[{frame["filename"]}|1000]]',f'![投影片](slides/{frame["filename"]})'))
        # Preserve every original ASR segment exactly once in the transcript layer.
        l2=[f"# {note['title']}｜校正逐字稿" if corrected_path.exists() else f"# {note['title']}｜原始逐字稿",'',
            '> 已依投影片與上下文校正可確認的辨識錯誤；未逐句聽音覆核。保留原句順序、數值與時間，不確定處就地標記。原始辨識檔及修訂對照另存。' if corrected_path.exists() else '> 自動辨識原稿，尚未校正。','']
        for j in owners[i]:
            item=reading[j]
            text=item['text']
            if item.get('review_note'): text+=f" **〔待核對：{item['review_note']}〕**"
            l2.append(f"- `(V1 {stamp(item['start'])})` {text}")
        if not owners[i]:l2.append('此短暫畫面沒有獨立歸屬的完整語句，請對照前後頁。')
        (out/'L2'/f'L2_seg{i+1:02}_slide{i+1:02}.md').write_text('\n'.join(l2)+'\n',encoding='utf-8')
    overview='''# 全課教學脈絡與閱讀導覽

> 完整處理 16 分 33 秒課程，保留 21 個畫面版本／出現區間（含回頁與手寫增量）。各頁總整理已改為可獨立閱讀的講義，依概念、因果與例子展開；段落銜接是依講稿整理，不是老師逐句引言。閱讀頁提供校正逐字稿，原始辨識檔另存。

## 這堂課在回答什麼

- `(V1 00:00)` **資料如何在 CPU、I/O 裝置、記憶體與磁碟之間交換，又如何有效利用有限的速度與容量？** 老師沿著系統路徑，從 I/O 機制走到記憶體階層、DRAM 組織，最後介紹磁碟區塊。

## 老師的推進順序

- `(V1 00:18)` **先辨認裝置及其位置**：南北橋提供連接背景，block／character／clock 說明不同資料交換形式。
- `(V1 02:00)` **再分清三個問題**：interrupt／polling 回答「怎麼知道完成」；port-mapped／MMIO 回答「如何定址存取裝置」；CPU／DMA 回答「資料由誰搬」。
- `(V1 07:20)` **提出層級設計的動機**：快、容量大、持續保存難以同時滿足，所以組合不同裝置。較快空間有限，接著問應該放什麼資料。
- `(V1 09:02)` **用例子建立 locality**：熱門影片說明近期重複存取；相鄰貼文的假設布局說明連續存取。老師再回到層級圖，把兩者連回 cache 與效能。
- `(V1 10:36)` **下探 DRAM 的實作限制**：cell 的電荷會流失 → refresh；主機位址要轉成 row／column／bank／chip → controller；啟動成本與平行性 → burst 與模組頻寬。
- `(V1 15:24)` **落到儲存的組織單位**：sector、block、LBA／PBA，呼應開頭的 block device，並在 16:16 左右結束主要內容。

## 容易混淆的地方

- `(V1 04:27)` I/O 通知、定址與搬移是三個面向。MMIO 並不等於 DMA；本頁印刷的 ARM／Intel 例子與講稿不一致，逐頁筆記已標示。
- `(V1 09:02)` Temporal locality 是近期會再用同一資料；spatial locality 是可能用到鄰近資料。社群貼文例子帶有資料連續配置的假設。
- `(V1 11:00)` 電荷與 0／1 的對應、64 ms refresh 是本段敘述，不宜直接外推成所有 DRAM 的統一規格。
- `(V1 14:38)` DRAM 數字例子混有 bit／byte、IC／bank 與 cache line，不能直接抄成精確公式；相關頁面保留疑點並附核對來源。
- `(V1 16:01)` 512-byte sector 與 4 KB sector 是不同條件；4 KB 等於八個 512-byte sectors，不能把它與八個 4 KB sectors 混為一談。

## 怎麼閱讀

- `(V1 00:00)` 左側依原始出現順序選頁。每頁從問題一路說明到機制、例子、取捨與下一步。先讀講義；有不懂或想確認的段落，再點該段時間戳回看影片。逐字稿頁顯示術語校正版，疑點就地標示。

## 方法與限制

- `(V1 00:00)` 畫面邊界依兩秒抽樣估計；老師可能先講下一頁或延後收尾。21 個區段包含重複投影片與畫面增量，不代表 21 張互不相同的原始 PPT。
- `(V1 00:00)` 這份完整筆記由本次 AI 助手依全段講稿、OCR 和投影片整理並檢閱，並非已新增獨立的一鍵摘要 API。文字仍不是老師逐句審定版本。
'''
    (out/'L3'/f'L3_seg{len(plan)+1:02}_overview.md').write_text(overview,encoding='utf-8')
    (out/'完整課程筆記.md').write_text(overview+'\n\n'+'\n\n'.join(docs),encoding='utf-8')
    assigned=[j for ids in owners for j in ids]
    report=dict(duration_seconds=duration,occurrences=len(frames),canonical_slides=sum(s.get('dedup',{}).get('is_canonical',False) for s in ground),transcript_segments=len(tx),assigned_segments=len(assigned),unassigned_segments=sorted(set(range(len(tx)))-set(assigned)),duplicate_assignments=len(assigned)-len(set(assigned)),raw_transcript_sha256=before,raw_transcript_unchanged=before==hashlib.sha256(transcript_path.read_bytes()).hexdigest(),outside_media_segments=[i for i,s in enumerate(tx) if s['end']>duration+.5 or s['start']<0],notes_generation='AI assistant authored and reviewed; no standalone synthesis API',profile='computer-science')
    assert not report['unassigned_segments'] and not report['duplicate_assignments'] and report['raw_transcript_unchanged']
    (out/'coverage_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
