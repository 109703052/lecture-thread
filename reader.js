let youtubePlayer=null, youtubePoll=null;
const DATA=JSON.parse(document.getElementById('course-data').textContent);
const $=s=>document.querySelector(s);
const state={segment:0,paragraph:-1,follow:true,frame:0};
let playbackRequest=0;
const audioSourceCache=new Map();
function seekableAudioSource(src){
 if(!audioSourceCache.has(src))audioSourceCache.set(src,fetch(src).then(async response=>{
  if(!response.ok)throw Error('Audio download failed');
  return URL.createObjectURL(await response.blob());
 }).catch(error=>{audioSourceCache.delete(src);throw error;}));
 return audioSourceCache.get(src);
}
let playbackRange=null, playbackTimer=null;
const PLAYBACK_TAIL=.3;
let slidesHidden=false, splitFraction=.45;
let transcriptFraction=null, navPinned=false, transcriptOpen=!!DATA.reading_paragraphs?.length;
const EDITS_KEY='lecturethread:transcript-edits:'+DATA.youtube_id+':'+DATA.transcript_revision;
const DRAFTS_KEY=EDITS_KEY+':drafts';
const LAYOUT_KEY='lecturethread:layout:v1:'+DATA.youtube_id;
function restoreLayoutPreferences(){
 try{
  const saved=JSON.parse(localStorage.getItem(LAYOUT_KEY)||'null');
  if(saved?.schema!==1)return;
  if(typeof saved.transcriptOpen==='boolean')transcriptOpen=saved.transcriptOpen;
  if(Number.isFinite(saved.slideFraction)&&saved.slideFraction>=.2&&saved.slideFraction<=.7)splitFraction=saved.slideFraction;
  if(Number.isFinite(saved.transcriptFraction)&&saved.transcriptFraction>=.18&&saved.transcriptFraction<=.7)transcriptFraction=saved.transcriptFraction;
 }catch{} // Missing, malformed or unavailable storage leaves usable defaults.
}
function persistLayoutPreferences(){
 try{localStorage.setItem(LAYOUT_KEY,JSON.stringify({schema:1,slideFraction:splitFraction,transcriptFraction,transcriptOpen}));}
 catch{
  const status=$('#layout-storage-status');
  if(status){status.hidden=false;status.textContent='版面設定無法儲存；目前調整僅在本頁有效。';}
 }
}

let manualEdits=DATA.manual_edits?.edits||{}, editDrafts={}, draftBases={}, speakingSource=-1;
let storeRevision=DATA.manual_edits?.revision||null, storeToken=null, storeReady=false, draftsDurable=true;
const savingEdits=new Set();
function persistDrafts(){
 try{sessionStorage.setItem(DRAFTS_KEY,JSON.stringify({texts:editDrafts,bases:draftBases}));draftsDurable=true;}
 catch{draftsDurable=false;$('#edit-storage-status').textContent='草稿暫存失敗，請保持本頁開啟並儲存到本地，或匯出備份。';}
}
function restoreDrafts(){
 try{
  const saved=JSON.parse(sessionStorage.getItem(DRAFTS_KEY)||'{}');
  for(const [id,text] of Object.entries(saved.texts||{})){
   if(/^(0|[1-9]\d*)$/.test(id)&&DATA.transcript[id]&&typeof text==='string'&&saved.bases?.[id]?.original===DATA.transcript[id].text){
    editDrafts[id]=text;draftBases[id]=saved.bases[id];
   }
  }
 }catch{$('#edit-storage-status').textContent='無法恢復分頁草稿；正式修訂仍以本地檔案為準。';}
}
function refreshManualRows(){
 if(DATA.reading_paragraphs?.length)document.querySelectorAll('[data-reading-ids]').forEach(row=>{
  row.innerHTML=readingParagraphHTML(row.dataset.readingIds.split(',').map(Number));
 });
 document.querySelectorAll('.utterance').forEach(row=>{
  const id=Number(row.dataset.source),editing=Object.hasOwn(editDrafts,id);
  const text=row.querySelector('.source-text');text.textContent=displayedTranscriptText(id,row);text.hidden=editing;

  row.querySelector('.transcript-editor').hidden=!editing;
  if(editing&&draftBases[id]?.conflict&&!savingEdits.has(id)){
   row.querySelector('[data-edit="save"]').textContent='確認並儲存此草稿';
   row.querySelector('.transcript-editor [role="status"]').textContent=conflictMessage(id);
  }
 });
}
function conflictMessage(id){return '偵測到其他分頁修訂。本地最新文字：'+transcriptText(id)+'。請比較上方草稿，再確認儲存，或使用本地最新文字。';}
function editRequestError(error){return error instanceof TypeError?'無法連線到本地修訂服務，請啟動服務後重試。':error.message;}
function acceptSnapshot(snapshot){
 if(snapshot.youtube_id!==DATA.youtube_id||snapshot.transcript_revision!==DATA.transcript_revision)throw Error('此閱讀頁的逐字稿版本已變更，請重建閱讀頁；草稿未刪除。');
 manualEdits=snapshot.edits;storeRevision=snapshot.revision;storeToken=snapshot.csrf_token;storeReady=true;
 refreshManualRows();
}
async function loadManualEdits(){
 storeReady=false;
 $('#edit-storage-status').textContent='正在連線本地修訂服務…';
 try{
  if(location.protocol!=='http:'||!['127.0.0.1','localhost'].includes(location.hostname))throw Error('請以 serve_reader.py 的本機 HTTP 網址開啟才能寫入檔案；草稿仍可保留。');
  const response=await fetch('/api/transcript-edits',{cache:'no-store'}),snapshot=await response.json();
  if(!response.ok)throw Error(snapshot.error||'無法讀取本地修訂。');
  acceptSnapshot(snapshot);
  // Keep older browser-only corrections as drafts; never silently promote them.
  try{
   const legacy=JSON.parse(localStorage.getItem(EDITS_KEY)||'{}');
   if(!sessionStorage.getItem(DRAFTS_KEY+':legacy-imported')){
    for(const [id,edit] of Object.entries(legacy))if(/^(0|[1-9]\d*)$/.test(id)&&DATA.transcript[id]&&edit?.original===DATA.transcript[id].text&&typeof edit.corrected==='string'&&edit.corrected!==transcriptText(id)&&!Object.hasOwn(editDrafts,id)){
     editDrafts[id]=edit.corrected;draftBases[id]={original:DATA.transcript[id].text,text:transcriptText(id),revision:storeRevision};
    }
    persistDrafts();sessionStorage.setItem(DRAFTS_KEY+':legacy-imported','1');
   }
  }catch{}
  document.querySelectorAll('[data-source-edit]').forEach(input=>{if(Object.hasOwn(editDrafts,input.dataset.sourceEdit))input.value=editDrafts[input.dataset.sourceEdit];});
  refreshManualRows();
  $('#edit-storage-status').textContent='已連線本地修訂服務，可儲存。';
 }catch(error){$('#edit-storage-status').textContent='未連線：'+editRequestError(error);}
}
function transcriptText(id){return manualEdits[id]?.corrected??DATA.transcript[id].text;}
function readingText(id){
 const row=DATA.reading_transcript?.[id];
 return row?.original===transcriptText(id)?row.text:transcriptText(id);
}
function readingParagraph(ids){
 return DATA.reading_paragraphs?.find(p=>p.source_ids.length===ids.length&&p.source_ids.every((id,i)=>id===ids[i]));
}
function readingParagraphText(ids){
 const p=readingParagraph(ids);
 return p&&p.originals.every((text,i)=>text===transcriptText(ids[i]))?p.text:ids.map(transcriptText).join('，');
}
// Authored sentence maps let each polished sentence point back to the originals it condenses.
function readingParagraphHTML(ids){
 const p=readingParagraph(ids),text=readingParagraphText(ids);
 if(!p?.sentences?.length||text!==p.text)return esc(text);
 return p.sentences.map(s=>`<span class="reading-sentence" data-sentence-ids="${s.source_ids.join(',')}" data-return="${s.source_ids[0]}">${esc(s.text)}</span>`).join('');
}
function displayedTranscriptText(id,row){
 return row?.closest?.('.transcript-group')?.classList.contains('show-details')?transcriptText(id):readingText(id);
}
async function editTranscript(id,action){
 if(DATA.read_only)return;
 const row=$(`.utterance[data-source="${id}"]`);if(!row)return;
 if(savingEdits.has(id))return;
 const editor=row.querySelector('.transcript-editor'),input=editor.querySelector('textarea'),message=editor.querySelector('[role="status"]');
 if(action==='open'){
  editDrafts[id]=editDrafts[id]??transcriptText(id);input.value=editDrafts[id];
  draftBases[id]=draftBases[id]||{original:DATA.transcript[id].text,text:transcriptText(id),revision:storeRevision};persistDrafts();
  editor.hidden=false;row.querySelector('.source-text').hidden=true;input.focus({preventScroll:true});return;
 }
 if(action==='latest'){
  editDrafts[id]=transcriptText(id);draftBases[id]={original:DATA.transcript[id].text,text:transcriptText(id),revision:storeRevision};
  input.value=editDrafts[id];editor.querySelector('[data-edit="save"]').textContent='儲存';message.textContent='已載入本地最新文字，可繼續修改或取消。';persistDrafts();return;
 }
 if(action==='save'){
  const text=input.value.trim();
  if(!text){message.textContent='請保留逐字稿文字，不能儲存空白內容。';return;}
  editDrafts[id]=input.value;persistDrafts();
  if(!storeReady){message.textContent='尚未連線至本地修訂服務，請按逐字稿區「重新連線」後再儲存。草稿未刪除。';return;}
  savingEdits.add(id);input.readOnly=true;editor.querySelectorAll('button').forEach(button=>button.disabled=true);message.textContent='正在寫入本地檔案…';
  try{
   const response=await fetch('/api/transcript-edits',{method:'POST',headers:{'Content-Type':'application/json','X-LectureThread-Token':storeToken},
    body:JSON.stringify({segment_id:id,corrected:text,transcript_revision:DATA.transcript_revision,revision:draftBases[id]?.revision??storeRevision})});
   const result=await response.json();
   if(response.status===409&&result.snapshot){
    acceptSnapshot(result.snapshot);
    draftBases[id]={original:DATA.transcript[id].text,text:transcriptText(id),revision:storeRevision,conflict:true};persistDrafts();
    message.textContent=conflictMessage(id);
    editor.querySelector('[data-edit="save"]').textContent='確認並儲存此草稿';return;
   }
   if(!response.ok){if(response.status===403)storeReady=false;throw Error(result.error||'本地儲存失敗。');}
   acceptSnapshot(result);delete editDrafts[id];delete draftBases[id];persistDrafts();refreshManualRows();
   $('#edit-storage-status').textContent='已連線 · 修訂已儲存到本地。';
  }catch(error){message.textContent=editRequestError(error)+' 草稿未刪除，可重試或匯出備份。';return;}
  finally{savingEdits.delete(id);input.readOnly=false;editor.querySelectorAll('button').forEach(button=>button.disabled=false);}
 }
 delete editDrafts[id];delete draftBases[id];persistDrafts();message.textContent='';editor.hidden=true;
 const text=row.querySelector('.source-text');text.textContent=displayedTranscriptText(id,row);text.hidden=false;
 editor.querySelector('[data-edit="save"]').textContent='儲存';
 if(row.isConnected)row.querySelector('[data-edit="open"]').focus({preventScroll:true});
}
function exportManualEdits(){
 const payload={schema:'lecturethread.manual-transcript-edits.v1',youtube_id:DATA.youtube_id,transcript_revision:DATA.transcript_revision,
  exported_at:new Date().toISOString(),edits:Object.entries(manualEdits).map(([id,edit])=>({segment_id:Number(id),...edit})),
  drafts:Object.entries(editDrafts).map(([id,text])=>({segment_id:Number(id),text,basis:draftBases[id]}))};
 const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json;charset=utf-8'}));
 const link=document.createElement('a');link.href=url;link.download=DATA.youtube_id+'.transcript.manual-edits.json';link.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function updateSpeaking(time){
 if(time!==null&&Number.isFinite(time)&&DATA.alignment?.startsWith('editorial-')){
  const at=playbackRange&&!playbackRange.free?Math.min(time,playbackRange.end-.001):time;
  syncReadingSlide({time:at});
 }
 let id=-1;
 if(time!==null&&playbackRange){
  const at=playbackRange.free?time:Math.min(time,playbackRange.end-.001);
  DATA.transcript.forEach((t,i)=>{if(t.start<=at&&t.end>at&&(playbackRange.free||(t.start<playbackRange.end&&t.end>playbackRange.start)))id=i;});
 }
 if(speakingSource===id)return;
 speakingSource=id;
 document.querySelectorAll('.utterance').forEach(row=>{
  const active=Number(row.dataset.source)===id;row.classList.toggle('is-speaking',active);
  row.querySelector('.speaking-label').hidden=!active;
  if(active)row.setAttribute('aria-current','true');else row.removeAttribute('aria-current');
 });
 document.querySelectorAll('.reading-sentence').forEach(s=>{if(s.dataset?.sentenceIds)s.classList.toggle('is-speaking',s.dataset.sentenceIds.split(',').map(Number).includes(id));});
 const status=$('#speaking-status');if(status)status.textContent=id<0?'':`正在播放 ${stamp(DATA.transcript[id].start)} 的原句`;
 if(id>=0&&state.follow&&!$('#sources').contains(document.activeElement)&&!Object.keys(editDrafts).length){
  const source=$(`.utterance[data-source="${id}"]`),group=source?.closest?.('.has-reading-paragraph');
  const row=group&&!group.classList.contains('show-details')?group:source,pane=$('#sources');
  if(row&&pane.clientHeight){
   const r=row.getBoundingClientRect(),p=pane.getBoundingClientRect(),top=p.top+$('.transcript-header').offsetHeight;
   if(r.top<top||r.bottom>p.bottom)pane.scrollTo({top:Math.max(0,pane.scrollTop+r.top-top-12),behavior:typeof matchMedia==='function'&&matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
  }
 }
}
function setSplit(fraction,remember=false){
 splitFraction=Math.max(.2,Math.min(.7,fraction));
 if(remember)persistLayoutPreferences();
 const root=$('#reading');if(!root||!root.clientHeight)return;
 root.style.setProperty('--media-share',splitFraction);
 const bar=$('#media-divider');
 if(bar){bar.setAttribute('aria-valuenow',Math.round(splitFraction*100));bar.setAttribute('aria-orientation',window.innerWidth<=800?'horizontal':'vertical');}
}
function updateMediaVisibility(){
 const playing=!$('#video-view').hidden;
 const visible=playing||(!slidesHidden&&Boolean(DATA.segments[state.segment].image||DATA.segments[1]?.image));
 $('#media-area').hidden=!visible;$('#media-divider').hidden=!visible;
 $('#reading').classList.toggle('media-collapsed',!visible);
 const button=$('#toggle-slide');button.textContent=slidesHidden?'顯示投影片':'隱藏投影片';
 button.hidden=playing||!(DATA.segments[state.segment].image||DATA.segments[1]?.image);
 button.setAttribute('aria-expanded',String(!slidesHidden));
 if(visible)setSplit(splitFraction);
}

const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function inlineText(s){return esc(s).replace(/\[([^\]]+)\]\((https:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')}
function stamp(t){return String(Math.floor(t/60)).padStart(2,'0')+':'+String(Math.floor(t%60)).padStart(2,'0')}
function sourceIds(section){return section.source_ids}
let sourceNavLimit=60;
function isSourceSegment(segment){return segment.occurrence_id!==undefined;}
function adjacentSegment(index,direction){
 const source=isSourceSegment(DATA.segments[index]);
 for(let i=index+direction;i>=0&&i<DATA.segments.length;i+=direction){
  if(isSourceSegment(DATA.segments[i])===source)return i;
 }
 return -1;
}
function renderNav(filter=''){
 let group='';
 $('#segments').innerHTML=DATA.segments.map((s,i)=>{
  if(isSourceSegment(s))return '';
  if(filter&&!(`${s.title} ${s.region} ${s.sections.map(p=>p.text).join(' ')}`).toLowerCase().includes(filter.toLowerCase()))return '';
  let label=s.region!==group?`<div class="nav-group">${esc(s.region)}</div>`:'';group=s.region;
  return label+`<button class="segment" data-segment="${i}" aria-current="${i===state.segment}"><small>${i===0?'總覽':'章節 '+i} · ${stamp(s.start)}–${stamp(s.end)}</small>${esc(s.title)}</button>`;
 }).join('')||'<p class="nav-empty">沒有符合的章節。</p>';
 const appendix=$('#source-nav');
 if(appendix){appendix.hidden=!DATA.segments.some(isSourceSegment);if(appendix.open)renderSourceNav();}
}
function renderSourceNav(){
 const filter=$('#source-search').value.trim().toLowerCase();
 const matches=DATA.segments.map((s,i)=>({s,i})).filter(({s})=>isSourceSegment(s)&&(!filter||s.title.toLowerCase().includes(filter)||stamp(s.start).includes(filter)));
 $('#source-segments').innerHTML=matches.slice(0,sourceNavLimit).map(({s,i})=>`<button class="segment" data-segment="${i}" aria-current="${i===state.segment}"><small>${stamp(s.start)}–${stamp(s.end)}</small>${esc(s.title)}</button>`).join('')||'<p class="nav-empty">沒有符合的原始畫面。</p>';
 $('#source-more').hidden=matches.length<=sourceNavLimit;
 $('#source-count').textContent=`顯示 ${Math.min(matches.length,sourceNavLimit)}／${matches.length} 個畫面`;
}
function renderNotes(s,index){return ` ${s.sections.map((p,i)=>`<section class="lesson" data-paragraph="${i}" tabindex="0" aria-label="${esc(p.heading)}"><div class="lesson-head"><h2>${esc(p.heading)}</h2><div class="lesson-actions"><button class="time" data-paragraph="${i}" aria-label="對照 ${stamp(p.time)} 的逐字稿">${stamp(p.time)}–${stamp(p.end)}</button><button data-play-section="${i}" ${p.source_ids.length?'':'disabled'} aria-label="聽此段：${esc(p.heading)}">聽此段</button></div></div><p>${esc(p.text)}</p><div data-audio-section="${i}" class="audio-slot"></div></section>`).join('')}
 ${s.caution?`<div class="caution"><h2>補充與待核對</h2><p>${inlineText(s.caution)}</p></div>`:''}
 <div class="paging"><button id="previous" ${adjacentSegment(index,-1)<0?'disabled':''}>上一節</button><button id="next" ${adjacentSegment(index,1)<0?'disabled':''}>下一節</button></div>`;}
// Group only adjacent source IDs within the same authored topic/slide occurrence.
// Limits are reading heuristics, not a claim of semantic inference.
function transcriptGroups(s){
 const ids=[...new Set(s.sections.flatMap(sourceIds))].sort((a,b)=>a-b), groups=[];
 if(DATA.reading_paragraphs?.length){
  const included=new Set(ids);
  // Keep the complete authored paragraph when a chapter edge intersects it.
  return DATA.reading_paragraphs.filter(p=>p.source_ids.some(id=>included.has(id))).map(p=>p.source_ids);
 }
 const occurrence=id=>DATA.segments?.findIndex((p,i)=>i>0&&p.start<=DATA.transcript[id].start&&DATA.transcript[id].start<p.end);
 const owner=id=>{
  const t=DATA.transcript[id],mid=(t.start+t.end)/2;
  return s.sections.findIndex(p=>p.time<=mid&&mid<p.end);
 };
 for(const id of ids){
  const t=DATA.transcript[id],group=groups.at(-1),last=group?.at(-1),prev=DATA.transcript[last];
  const first=group&&DATA.transcript[group[0]];
  const length=group?.reduce((n,i)=>n+DATA.transcript[i].text.length,0)||0;
  const authored=DATA.reading_transcript?.[id]&&DATA.reading_transcript?.[last];
  const boundary=!group||id!==last+1||(authored?(DATA.reading_transcript[last].paragraph_end||occurrence(id)!==occurrence(last)):(owner(id)!==owner(last)||t.start-prev.end>1.5||
   t.end-first.start>28||length+t.text.length>180||
   (prev.end-first.start>=10&&/[。！？.!?][”」']?$/.test(prev.text.trim()))));
  if(boundary)groups.push([id]);else group.push(id);
 }
 return groups;
}
function renderTranscript(s){
 const groups=transcriptGroups(s);
 return groups.length?groups.map(ids=>{
  const first=DATA.transcript[ids[0]],last=DATA.transcript[ids.at(-1)];
  const authored=!!readingParagraph(ids);
  return `<section class="transcript-group${authored?' has-reading-paragraph':''}" aria-label="逐字稿 ${stamp(first.start)} 至 ${stamp(last.end)}">
   <div class="group-tools"><time>${stamp(first.start)}–${stamp(last.end)}</time><button data-play-group="${ids.join(',')}">聽這段</button><button data-video-group="${ids.join(',')}" ${DATA.media_kind==='audio'?'disabled':''}>觀看影片</button><button data-group-details aria-expanded="false">${authored?'查看校訂原話':'逐句校訂'}</button></div>
   ${authored?`<p class="reading-paragraph group-text" data-reading-ids="${ids.join(',')}" data-return="${ids[0]}" role="button" tabindex="0" aria-label="返回對應講義">${readingParagraphHTML(ids)}</p>`:''}<div class="group-text original-utterances">${ids.map(id=>{
    const t=DATA.transcript[id],editing=Object.hasOwn(editDrafts,id);
  return `<div class="utterance" data-source="${id}"><div class="source-tools"><time>${stamp(t.start)}</time><button data-play="${id}" aria-label="聽 ${stamp(t.start)} 此句">聽此句</button><button data-video="${id}" ${DATA.media_kind==='audio'?'disabled title="此課程僅提供音訊"':''} aria-label="觀看 ${stamp(t.start)} 此句的影片">觀看影片</button>${DATA.read_only?'':`<button data-edit="open" data-edit-id="${id}" aria-label="編輯 ${stamp(t.start)} 的校訂原話">校訂原話</button>`}<a href="${youtubeAt(t.start)}" target="_blank" rel="noopener noreferrer" data-youtube ${DATA.youtube_source_id===''?'hidden':''}> YouTube </a></div><span class="speaking-label" hidden>正在播放</span><span role="button" tabindex="0" class="source-text" data-return="${id}" aria-label="返回 ${stamp(t.start)} 對應講義" ${editing?'hidden':''}>${esc(readingText(id))}</span><div class="transcript-editor" ${editing?'':'hidden'}><textarea data-source-edit="${id}" aria-label="修改 ${stamp(t.start)} 的校訂原話" rows="3">${esc(editing?editDrafts[id]:transcriptText(id))}</textarea><div class="edit-actions"><button data-edit="save" data-edit-id="${id}">${draftBases[id]?.conflict?'確認並儲存此草稿':'儲存'}</button><button data-edit="cancel" data-edit-id="${id}">取消</button><button data-edit="latest" data-edit-id="${id}">使用本地最新文字</button><span>Ctrl+Enter 儲存 · Esc 取消</span></div><p role="status">${draftBases[id]?.conflict?esc(conflictMessage(id)):''}</p></div><div data-audio-source="${id}" class="audio-slot"></div></div>`;
   }).join('')}</div><div class="audio-slot" data-audio-group="${ids[0]}"></div></section>`;
 }).join(''):'<p class="empty">這是短暫轉場，沒有獨立講解語句。請對照前後節。</p>';
}
// Keep the player's ancestors connected: replacing/reparenting a playing media
// node can pause it. Retain just its branch and refresh the other content.
function replaceContentKeepingAudio(pane,html){
 const player=$('#inline-player');
 if(player&&!player.hidden&&pane.contains(player)){
  let branch=player;
  while(branch.parentElement!==pane){
   const parent=branch.parentElement;
   for(const child of [...parent.children])if(child!==branch)child.remove();
   for(const attr of ['data-paragraph','data-source','data-audio-source','data-audio-section','aria-label','tabindex'])parent.removeAttribute(attr);
   parent.className='continuous-player';branch=parent;
  }
  for(const child of [...pane.children])if(child!==branch)child.remove();
  pane.insertAdjacentHTML('beforeend',html);
 }else pane.innerHTML=html;
}
function showPlaybackSegment(index){
 const s=DATA.segments[index];state.segment=index;state.paragraph=-1;speakingSource=-1;
 renderNav($('#search').value);
 const heading=$('#reading-head h1');heading.textContent=heading.title=s.title;
 $('#reading-head .meta-time').textContent=`${stamp(s.start)}–${stamp(s.end)} · ${s.sections.length} 個閱讀段落`;
 replaceContentKeepingAudio($('#notes-scroll'),renderNotes(s,index));
 replaceContentKeepingAudio($('#transcript'),renderTranscript(s));
 $('#notes-scroll').scrollTop=0;$('#sources').scrollTop=0;
 updateMediaVisibility();
 try{history.replaceState(null,'','#seg-'+(index+1))}catch{}
}
function syncPlaybackPosition(time){
 if(!playbackRange?.free||!Number.isFinite(time)||savingEdits.size||document.activeElement?.closest?.('.transcript-editor'))return;
 // The overview overlaps every occurrence; only actual slide occurrences count.
 const index=DATA.segments.findIndex((s,i)=>i>0&&s.start<=time&&time<s.end);
 if(index<0)return;
 if(index!==state.segment)showPlaybackSegment(index);
 const sections=DATA.segments[index].sections;
 let paragraph=sections.findIndex(p=>p.time<=time&&time<p.end);
 if(paragraph<0){paragraph=0;sections.forEach((p,i)=>{if(p.time<=time)paragraph=i;});}
 if(paragraph!==state.paragraph){
  setParagraph(paragraph);
  const el=$(`.lesson[data-paragraph="${paragraph}"]`),pane=$('#notes-scroll');
  if(el&&pane.clientHeight){const inset=pane.querySelector(':scope > .continuous-player')?.offsetHeight||0;pane.scrollTop+=el.getBoundingClientRect().top-pane.getBoundingClientRect().top-inset-16;}
 }
}
function showSegment(index){
 if(savingEdits.size){$('#edit-storage-status').textContent='正在儲存，請稍候再切換章節。';return;}
 stopVideo();
 state.segment=index;state.paragraph=-1;
 const s=DATA.segments[index];
 renderNav($('#search').value);
 $('#reading-head').innerHTML=`<h1 title="${esc(s.title)}">${esc(s.title)}</h1><div class="meta"><small class="meta-time">${stamp(s.start)}–${stamp(s.end)} · ${s.sections.length} 個閱讀段落</small><div class="slide-tools"><button id="toggle-slide" aria-expanded="true">隱藏投影片</button><button id="restore-ratio">適應區域</button><button id="enlarge-slide">放大投影片</button></div></div>`;
 $('#reading').innerHTML=`<div id="reading-status"><div id="inline-player" hidden><div class="playback-summary"><span id="playback-label"></span><button id="stop-playback">停止聲音</button></div><audio id="lesson-audio" controls preload="none" aria-label="所選文字的聲音播放器"></audio><p id="audio-message" role="status"></p></div>
 <p id="video-message" role="status"></p></div>
 <div class="figure" id="media-area" ${s.image?'':'hidden'}>
 <span id="slide-caption" class="visually-hidden">投影片 · 隨閱讀段落切換</span>
 <div class="video-tools" id="video-tools" hidden><strong>影片對照</strong><button id="hide-video">隱藏影片</button><a id="video-youtube" ${DATA.youtube_source_id===''?'hidden':''} target="_blank" rel="noopener noreferrer">在 YouTube 開啟</a></div>
 <div id="media-frame">
 <div id="slide-view">${s.image?`<img draggable="false" src="${esc(s.image)}" alt="${esc(s.title)}的投影片">`:''}</div>
 <div id="video-view" hidden><video id="lesson-video" controls playsinline preload="none"></video></div>

 </div></div>
 <div id="media-divider" role="separator" tabindex="0" aria-label="調整投影片與總整理的區域比例" aria-orientation="vertical" aria-valuemin="20" aria-valuemax="70" aria-valuenow="45" title="拖曳調整區域比例；方向鍵微調，Home 恢復"><span></span></div>
 <div id="notes-scroll">
 ${renderNotes(s,index)}</div>`;
 updateMediaVisibility();
 $('#notes-scroll').addEventListener('scroll',()=>{if(!state.frame)state.frame=requestAnimationFrame(trackReading)},{passive:true});

 $('#transcript').innerHTML=renderTranscript(s);
 $('#notes-scroll').scrollTop=0;$('#sources').scrollTop=0;
 setParagraph(0);
 try{history.replaceState(null,'','#seg-'+(index+1))}catch{}
}
function setParagraph(i){
 const s=DATA.segments[state.segment];if(!s.sections[i]||state.paragraph===i)return;
 state.paragraph=i;
 syncReadingSlide(s.sections[i]);
 document.querySelectorAll('.lesson').forEach(el=>el.classList.toggle('is-active',Number(el.dataset.paragraph)===i));
 const ids=new Set(sourceIds(s.sections[i]));
 document.querySelectorAll('.utterance').forEach(el=>{const active=ids.has(Number(el.dataset.source));el.classList.toggle('is-linked',active);el.querySelector('.source-text')?.setAttribute('aria-pressed',String(active))});
 $('#status').textContent=ids.size?`${stamp(s.sections[i].time)}–${stamp(s.sections[i].end)} · 對應 ${ids.size} 句`:'此段沒有獨立講解語句';
 if(state.follow)scrollTranscript();
}
function scrollTranscript(){
 const active=$('.utterance.is-speaking')||$('.utterance.is-linked');if(!active)return;
 const first=active.closest?.('.transcript-group')||active;
 const pane=$('#sources'),head=$('.transcript-header');
 pane.scrollTo({top:Math.max(0,pane.scrollTop+first.getBoundingClientRect().top-pane.getBoundingClientRect().top-head.offsetHeight-16),behavior:typeof matchMedia==='function'&&matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
}
function trackReading(){
 state.frame=0;
 const pane=$('#notes-scroll');
 // Mobile tabs hide this pane; zero-size lesson bounds cannot locate the reader.
 if(!pane||pane.clientHeight===0)return;
 const rect=pane.getBoundingClientRect(),anchor=rect.top+Math.min(180,pane.clientHeight*.25);
 let best=null,dist=Infinity;
 document.querySelectorAll('.lesson').forEach(el=>{
  const r=el.getBoundingClientRect();if(r.bottom<rect.top||r.top>rect.bottom)return;
  const d=r.top<=anchor&&r.bottom>=anchor?0:Math.min(Math.abs(r.top-anchor),Math.abs(r.bottom-anchor));
  if(d<dist){dist=d;best=el}
 });
 if(best)setParagraph(Number(best.dataset.paragraph));
}
function youtubeAt(t){const id=DATA.youtube_source_id??DATA.youtube_id;return id?'https://www.youtube.com/watch?v='+encodeURIComponent(id)+'&t='+Math.max(0,Math.floor(t))+'s':''}

function stopVideo(){
 playbackRequest++;
 if(DATA.video_provider==='youtube'){
 clearInterval(youtubePoll);youtubePoll=null;
 if(youtubePlayer){youtubePlayer.destroy();youtubePlayer=null;}
 const yt=$('#youtube-player');if(yt)yt.remove();
 const localVideo=$('#lesson-video');if(localVideo)localVideo.hidden=false;
 }
 clearTimeout(playbackTimer);playbackTimer=null;playbackRange=null;
 updateSpeaking(null);
 for(const selector of ['#lesson-video','#lesson-audio']){
  const v=$(selector);if(!v)continue;
  for(const event of ['loadedmetadata','error','timeupdate','play','playing','pause','seeking','seeked','ratechange','ended'])v['on'+event]=null;
  v.pause();if(v.getAttribute('src')){v.removeAttribute('src');v.load();}
 }
 const player=$('#inline-player');if(player)player.hidden=true;
}
function playSource(id,video=false){
 const t=DATA.transcript[id];if(!t)return;
 const slot=video?null:$(`[data-audio-source="${id}"]`);if(!video&&!slot)return;
 playRange(t.start,t.end,'此句',slot);
}
function playSection(index){
 const section=DATA.segments[state.segment].sections[index];
 if(!section||!section.source_ids.length)return;
 const slot=$(`[data-audio-section="${index}"]`);if(!slot)return;
 playRange(section.time,section.end,'此段',slot);
}
function playRange(start,end,label,audioSlot=null){
 if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start)return;
 if(!audioSlot&&DATA.media_kind==='audio')return;
 if(!audioSlot&&DATA.video_provider==='youtube'){playYouTubeRange(start,end,label);return;}
 // Listening stays beside the requested text and never navigates or selects notes.
 const positions=['#notes-scroll','#sources'].map(selector=>$(selector)).filter(pane=>pane.clientHeight>0).map(pane=>({pane,top:pane.scrollTop}));
 const wasVideo=!$('#video-view').hidden;
 stopVideo();
 const audio=Boolean(audioSlot),area=$('#media-area'),v=$(audio?'#lesson-audio':'#lesson-video');
 const request=++playbackRequest;
 const isCurrent=()=>request===playbackRequest&&$(audio?'#lesson-audio':'#lesson-video')===v;
 playbackRange={start,end,label,audio,free:false};
 let pendingSeek=null,rangeFinished=false;
 area.classList.toggle('playing',!audio);$('#slide-view').hidden=!audio;$('#video-view').hidden=audio;$('#video-tools').hidden=audio;
 if(audio){
  audioSlot.append($('#inline-player'));$('#inline-player').hidden=false;v.hidden=false;
  $('#playback-label').textContent=`${label} ${stamp(start)}–${stamp(end)} · 尾端緩衝 0.3 秒；拖曳進度可自由播放`;
 }else{document.body.dataset.pane='notes';}
 const message=$(audio?'#audio-message':'#video-message');message.textContent='';
 $('#video-youtube').href=youtubeAt(start);$('#video-message').textContent='';
 const stopAt=()=>Number.isFinite(v.duration)?Math.min(end+PLAYBACK_TAIL,v.duration):end+PLAYBACK_TAIL;
 const freePlayback=()=>{
  playbackRange.free=true;rangeFinished=false;
  clearTimeout(playbackTimer);playbackTimer=null;
  if(audio)$('#playback-label').textContent='自由播放 · 可拖曳到任意時間';
  else message.textContent='自由播放 · 可拖曳到任意時間';
 };
 const boundary=()=>{
  if(!isCurrent())return;
  clearTimeout(playbackTimer);playbackTimer=null;
  const finish=stopAt();
  if(playbackRange.free&&!v.seeking)syncPlaybackPosition(v.currentTime);
  updateSpeaking(!v.paused&&!v.seeking?v.currentTime:null);
  if(playbackRange.free||v.seeking)return;
  if(v.currentTime>=finish){
   rangeFinished=true;v.pause();
   const text=`${label}已播完 · 再按播放可繼續，或拖曳到任意時間`;
   if(audio)$('#playback-label').textContent=text;else message.textContent=text;
   return;
  }
  if(!v.paused&&!v.seeking&&v.playbackRate>0){
   playbackTimer=setTimeout(boundary,Math.max(10,(finish-v.currentTime)/v.playbackRate*1000));
  }
 };
 v.ontimeupdate=v.onplaying=v.onratechange=boundary;
 v.onpause=v.onended=()=>{if(isCurrent()){clearTimeout(playbackTimer);playbackTimer=null;updateSpeaking(null);}};
 v.onseeking=()=>{
  if(!isCurrent())return;
  clearTimeout(playbackTimer);playbackTimer=null;updateSpeaking(null);
  // Only metadata positioning is programmatic; native seeking releases the range.
  if(pendingSeek===null||Math.abs(v.currentTime-pendingSeek)>.05){pendingSeek=null;freePlayback();}
 };
 v.onplay=()=>{if(isCurrent()){if(rangeFinished)freePlayback();boundary();}};
 v.onseeked=()=>{if(isCurrent()){
  if(pendingSeek===null||Math.abs(v.currentTime-pendingSeek)>.05)freePlayback();
  pendingSeek=null;boundary();
 }};
 const seek=()=>{
  if(!isCurrent())return;
  v.onloadedmetadata=null;const target=Math.min(start,stopAt());
  pendingSeek=Math.abs(v.currentTime-target)>.001?target:null;v.currentTime=target;
  v.play().catch(()=>{if(isCurrent())message.textContent='請按此處播放器的播放鍵。';});
 };
 v.onerror=()=>{if(isCurrent()){clearTimeout(playbackTimer);playbackTimer=null;updateSpeaking(null);message.textContent=(DATA.read_only?'媒體':'本機媒體')+'無法載入，可重按播放或使用該句的 YouTube 連結。';}};
 const source=audio?(DATA.audio_src||DATA.video_src):DATA.video_src;
 const loadSource=src=>{if(!isCurrent())return;message.textContent='';v.onloadedmetadata=seek;v.src=src;v.load();};
 // Hosted assets may ignore HTTP Range. A complete local Blob is seekable even
 // in that case, and its promise is shared by subsequent clicks in this course.
 if(audio&&DATA.read_only&&DATA.audio_src){
  message.textContent='正在載入課程音訊，完成後會從所選段落播放…';
  seekableAudioSource(source).then(loadSource).catch(()=>{if(isCurrent())message.textContent='音訊載入失敗，請重按聽這段重試。';});
 }else loadSource(source);
 if(!audio||wasVideo)updateMediaVisibility();
 if(audio)positions.forEach(({pane,top})=>{pane.scrollTop=top;});
}
function hideVideo(){
 stopVideo();$('#video-message').textContent='';
 $('#video-view').hidden=true;$('#video-tools').hidden=true;$('#slide-view').hidden=false;$('#media-area').classList.remove('playing');
 updateMediaVisibility();
}
document.addEventListener('pointerdown',e=>{
 const transcriptBar=e.target.closest('#transcript-divider');
 if(transcriptBar&&e.button===0){
  e.preventDefault();const start=e.clientY,height=$('#sources').getBoundingClientRect().height,available=document.querySelector('.layout').clientHeight-14;
  transcriptBar.setPointerCapture(e.pointerId);
  const move=ev=>setTranscriptHeight((height+start-ev.clientY)/available,true);
  const end=()=>{for(const event of ['pointerup','pointercancel','lostpointercapture'])transcriptBar.removeEventListener(event,end);transcriptBar.removeEventListener('pointermove',move);};
  transcriptBar.addEventListener('pointermove',move);for(const event of ['pointerup','pointercancel','lostpointercapture'])transcriptBar.addEventListener(event,end);return;
 }
 const divider=e.target.closest('#media-divider');
 if(divider&&e.button===0){
  e.preventDefault();const vertical=window.innerWidth>800,start=vertical?e.clientX:e.clientY,initial=splitFraction;
  const available=Math.max(1,vertical?$('#reading').clientWidth-14:$('#reading').clientHeight-$('#reading-status').offsetHeight-14);
  divider.setPointerCapture(e.pointerId);
  const move=ev=>setSplit(initial+((vertical?ev.clientX:ev.clientY)-start)/available,true);
  const end=()=>{divider.removeEventListener('pointermove',move);divider.removeEventListener('pointerup',end);divider.removeEventListener('pointercancel',end);divider.removeEventListener('lostpointercapture',end)};
  divider.addEventListener('pointermove',move);divider.addEventListener('pointerup',end);divider.addEventListener('pointercancel',end);divider.addEventListener('lostpointercapture',end);return;
 }

});
document.addEventListener('keydown',e=>{
 if(e.target.id==='transcript-divider'&&['ArrowUp','ArrowDown','Home','End'].includes(e.key)){e.preventDefault();setTranscriptHeight(e.key==='Home'?(window.innerWidth<=800?.44:.34):e.key==='End'?.7:(transcriptFraction??.34)+(e.key==='ArrowUp'?.03:-.03),true);return}
 if(e.target.id==='media-divider'&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home'].includes(e.key)){e.preventDefault();setSplit(e.key==='Home'?.45:splitFraction+(['ArrowDown','ArrowRight'].includes(e.key)?.03:-.03),true);return}
});
$('#main').addEventListener('scroll',()=>{if(!state.frame)state.frame=requestAnimationFrame(trackReading)},{passive:true});
$('#search').addEventListener('input',e=>renderNav(e.target.value));
$('#source-nav').addEventListener('toggle',e=>{if(e.target.open)renderSourceNav();});
$('#source-search').addEventListener('input',()=>{sourceNavLimit=60;renderSourceNav();});
$('#source-more').addEventListener('click',()=>{sourceNavLimit+=60;renderSourceNav();});
function setNav(open,focus=true){
 navPinned=open&&focus;
 $('#chapter-nav').hidden=!open;$('#chapter-nav').inert=!open;$('#chapter-dock').classList.toggle('is-open',open);
 for(const selector of ['#toggle-nav','#chapter-tab'])$(selector).setAttribute('aria-expanded',String(open));
 if(open&&focus)$('#search').focus();
}
function setTranscriptHeight(fraction,remember=false){
 const layout=document.querySelector('.layout'),available=Math.max(0,layout.clientHeight-14);
 if(!available)return;
 const min=Math.min(140,available*.3),max=Math.max(min,Math.min(available*.7,available-180));
 transcriptFraction=Math.max(.18,Math.min(.7,fraction));
 const height=Math.max(min,Math.min(max,available*transcriptFraction));
 if(remember)persistLayoutPreferences();
 const actualFraction=height/available;layout.style.setProperty('--transcript-height',height+'px');
 const bar=$('#transcript-divider');bar.setAttribute('aria-valuemin',Math.round(min/available*100));bar.setAttribute('aria-valuemax',Math.round(max/available*100));bar.setAttribute('aria-valuenow',Math.round(actualFraction*100));bar.setAttribute('aria-valuetext',Math.round(height)+' 像素');
}
function setTranscript(open,remember=true,focus=true){
 transcriptOpen=open;if(remember)persistLayoutPreferences();
 $('#sources').hidden=!open;$('#transcript-divider').hidden=!open;document.querySelector('.layout').classList.toggle('transcript-open',open);
 if(open)setTranscriptHeight(transcriptFraction??(window.innerWidth<=800?.44:.34));
 const button=$('#toggle-transcript');button.setAttribute('aria-expanded',String(open));button.textContent=(open?'收起':'展開')+(DATA.reading_paragraphs?.length?'閱讀稿':'逐字稿');
 if(open){scrollTranscript();if(focus)$('#close-transcript').focus({preventScroll:true});}else if(focus)button.focus({preventScroll:true});
}
function syncReadingSlide(section){
 const current=DATA.segments[state.segment];
 const occurrence=DATA.alignment?.startsWith('editorial-')?DATA.segments.find(s=>s.occurrence_id&&s.image&&s.start<=section.time&&s.end>section.time):null;
 const slide=occurrence||(current.image?current:DATA.segments.find(s=>s.image&&s.start<=section.time&&s.end>section.time));
 if(!slide?.image)return;
 const view=$('#slide-view');
 if(view.dataset.image!==slide.image){view.dataset.image=slide.image;view.innerHTML=`<img draggable="false" src="${esc(slide.image)}" alt="${esc(slide.title)}的投影片">`;}
 $('#slide-caption').textContent=slide.title;
}
document.addEventListener('click',e=>{
 if(e.target.id==='toggle-nav')setNav($('#chapter-nav').hidden);
 if(e.target.id==='chapter-tab')setNav($('#chapter-nav').hidden);
 if(e.target.id==='close-nav')setNav(false);
 if(!$('#chapter-nav').hidden&&!e.target.closest('#chapter-dock,#toggle-nav'))setNav(false,false);
 if(e.target.id==='toggle-transcript')setTranscript($('#sources').hidden);
 if(e.target.id==='close-transcript')setTranscript(false);
 if(e.target.id==='enlarge-slide'){
  const img=$('#slide-view img');if(!img)return;
  $('#detail-image').innerHTML=`<img src="${esc(img.src)}" alt="${esc(img.alt)}">`;$('#slide-dialog').showModal();
 }
 if(e.target.id==='close-slide')$('#slide-dialog').close();
});
document.addEventListener('keydown',e=>{
 if(e.key==='Escape'&&!$('#slide-dialog').open){
  if(!$('#chapter-nav').hidden){setNav(false);$('#toggle-nav').focus();}
  else if(!$('#sources').hidden&&!e.target.closest('.transcript-editor')&&!playbackRange)setTranscript(false);
 }
});
// Hovering (or tapping, on touch screens) a reading sentence shows its corrected originals.
let peekSentence=null,lastPointer='mouse';
function showSourcePeek(sentence,touch){
 const ids=sentence.dataset.sentenceIds.split(',').map(Number);
 let peek=$('#source-peek');
 if(!peek){peek=document.createElement('div');peek.id='source-peek';peek.setAttribute('role','tooltip');document.body.append(peek);}
 peek.innerHTML=`<p class="peek-label">校訂原話</p>${ids.map(id=>`<p><time>${stamp(DATA.transcript[id].start)}</time>${esc(transcriptText(id))}</p>`).join('')}${touch?`<button data-return="${ids[0]}">回到講義</button>`:''}`;
 peek.classList.toggle('is-touch',touch);peek.hidden=false;
 peekSentence?.classList.remove('is-peeked');peekSentence=sentence;sentence.classList.add('is-peeked');sentence.setAttribute('aria-describedby','source-peek');
 const rects=sentence.getClientRects(),first=rects[0],last=rects[rects.length-1],gap=8;
 const width=Math.min(440,window.innerWidth-24);peek.style.width=width+'px';
 const height=peek.offsetHeight,above=last.bottom+gap+height>window.innerHeight-12&&first.top-gap-height>=12;
 // Anchor to the line the popup touches: the sentence's first line above, its last line below.
 const anchor=above?first:last;
 peek.style.left=Math.max(12,Math.min(anchor.left,window.innerWidth-width-12))+'px';
 peek.style.top=(above?first.top-gap-height:last.bottom+gap)+'px';
}
function hideSourcePeek(){
 if(!peekSentence)return;
 peekSentence.classList.remove('is-peeked');peekSentence.removeAttribute('aria-describedby');peekSentence=null;
 const peek=$('#source-peek');if(peek)peek.hidden=true;
}
document.addEventListener('click',e=>{
 const sentence=e.target.closest('.reading-sentence');
 if(sentence&&lastPointer!=='mouse'){if(sentence===peekSentence)hideSourcePeek();else showSourcePeek(sentence,true);return;}
 if(!e.target.closest('.reading-sentence'))hideSourcePeek();
 const details=e.target.closest('[data-group-details]');
 if(details){const group=details.closest('.transcript-group'),open=!group.classList.contains('show-details');group.classList.toggle('show-details',open);details.setAttribute('aria-expanded',String(open));details.textContent=group.classList.contains('has-reading-paragraph')?(open?'返回閱讀稿':'查看校訂原話'):(open?'收起校訂':'逐句校訂');refreshManualRows();return;}
 const groupPlay=e.target.closest('[data-play-group],[data-video-group]');
 if(groupPlay){const video=groupPlay.hasAttribute('data-video-group'),ids=(video?groupPlay.dataset.videoGroup:groupPlay.dataset.playGroup).split(',').map(Number);playRange(DATA.transcript[ids[0]].start,DATA.transcript[ids.at(-1)].end,'這段',video?null:$(`[data-audio-group="${ids[0]}"]`));return;}
 const edit=e.target.closest('[data-edit]');if(edit){editTranscript(Number(edit.dataset.editId),edit.dataset.edit);return}
 if(e.target.id==='export-edits'){exportManualEdits();return}
 if(e.target.id==='reload-edits'){loadManualEdits();return}
 if(e.target.closest('.transcript-editor'))return;
 if(e.target.id==='toggle-slide'){slidesHidden=!slidesHidden;updateMediaVisibility();return}
 if(e.target.id==='restore-ratio'){setSplit(.45,true);return}
 const play=e.target.closest('[data-play]');if(play){playSource(Number(play.dataset.play));return}
 const video=e.target.closest('[data-video]');if(video){playSource(Number(video.dataset.video),true);return}
 const playSectionButton=e.target.closest('[data-play-section]');if(playSectionButton){playSection(Number(playSectionButton.dataset.playSection));return}
 if(e.target.closest('[data-youtube],#video-youtube'))return;
 if(e.target.id==='hide-video'||e.target.id==='stop-playback'){hideVideo();return}
 if(e.target.closest('#inline-player'))return;
 const nav=e.target.closest('[data-segment]');
 if(nav){showSegment(Number(nav.dataset.segment));document.body.dataset.pane='notes';setNav(false);$('#toggle-nav').focus();return}
 const panel=e.target.closest('[data-pane-choice]');
 if(panel){document.body.dataset.pane=panel.dataset.paneChoice;if(panel.dataset.paneChoice==='transcript')scrollTranscript();return}
 const paragraph=e.target.closest('[data-paragraph]');
 if(paragraph){setParagraph(Number(paragraph.dataset.paragraph));return}
 const source=e.target.closest('[data-return]');
 if(source){
  const id=Number(source.dataset.return),s=DATA.segments[state.segment];
  const matches=s.sections.map((p,i)=>p.source_ids.includes(id)?i:-1).filter(i=>i>=0);
  const i=matches.includes(state.paragraph)?state.paragraph:matches[0];
  if(i!==undefined){document.body.dataset.pane='notes';setParagraph(i);$(`.lesson[data-paragraph="${i}"]`).scrollIntoView({block:'start',behavior:'auto'})}
  return;
 }
 if(e.target.id==='previous')showSegment(adjacentSegment(state.segment,-1));
 if(e.target.id==='next')showSegment(adjacentSegment(state.segment,1));
 if(e.target.id==='follow'){state.follow=!state.follow;e.target.setAttribute('aria-pressed',String(state.follow));e.target.textContent=state.follow?'跟隨閱讀：開':'跟隨閱讀：關';if(state.follow)scrollTranscript()}
});
document.addEventListener('keydown',e=>{
 if(e.target.matches('[data-return]')&&['Enter',' '].includes(e.key)){e.preventDefault();e.target.click();return;}
 if(e.target.matches('[data-source-edit]')){
  if(e.key==='Escape'){e.preventDefault();editTranscript(Number(e.target.dataset.sourceEdit),'cancel');return;}
  if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();editTranscript(Number(e.target.dataset.sourceEdit),'save');return;}
 }
 if(e.key==='Escape'&&playbackRange){hideVideo();return}
 if((e.key==='Enter'||e.key===' ')&&e.target.matches('.lesson')){e.preventDefault();e.target.click()}
});
document.addEventListener('focusin',e=>{if(e.target.matches('.lesson'))setParagraph(Number(e.target.dataset.paragraph))});
function refreshReadingLayout(){
 if(!$('#main').clientWidth||!$('#main').clientHeight)return;
 setSplit(splitFraction);trackReading();
}
window.addEventListener('resize',()=>{if(!$('#sources').hidden)setTranscriptHeight(transcriptFraction??.34);refreshReadingLayout();});
// A mobile tab becoming visible does not fire window.resize.
document.addEventListener('pointerdown',e=>{lastPointer=e.pointerType||'mouse'},true);
document.addEventListener('pointerover',e=>{
 if(e.pointerType!=='mouse')return;
 const sentence=e.target.closest?.('.reading-sentence');
 if(sentence){if(sentence!==peekSentence)showSourcePeek(sentence,false);}
 else hideSourcePeek();
});
document.addEventListener('scroll',hideSourcePeek,true);
window.addEventListener('resize',hideSourcePeek);
document.addEventListener('keydown',e=>{if(e.key==='Escape')hideSourcePeek();});
new ResizeObserver(refreshReadingLayout).observe($('#main'));
document.addEventListener('input',e=>{if(e.target.matches('[data-source-edit]')){editDrafts[e.target.dataset.sourceEdit]=e.target.value;persistDrafts();}});
window.addEventListener('beforeunload',e=>{if(savingEdits.size||Object.entries(editDrafts).some(([id,text])=>text!==transcriptText(id))){e.preventDefault();e.returnValue='';}});
restoreLayoutPreferences();
if(!DATA.read_only)restoreDrafts();
const initial=Number(location.hash.match(/^#seg-(\d+)$/)?.[1]||1)-1;
showSegment(Math.max(0,Math.min(initial,DATA.segments.length-1)));
setTranscript(transcriptOpen,false,false);
if(!DATA.read_only)loadManualEdits();

let youtubeAPI=null;
function loadYouTubeAPI(){
 if(window.YT?.Player)return Promise.resolve(window.YT);
 if(youtubeAPI)return youtubeAPI;
 youtubeAPI=new Promise((resolve,reject)=>{
  const timeout=setTimeout(()=>{youtubeAPI=null;reject(Error('YouTube 載入逾時，請重試或開啟原影片。'));},15000);
  window.onYouTubeIframeAPIReady=()=>{clearTimeout(timeout);resolve(window.YT);};
  const script=document.createElement('script');script.src='https://www.youtube.com/iframe_api';
  script.onerror=()=>{clearTimeout(timeout);youtubeAPI=null;reject(Error('無法連線 YouTube，請重試或開啟原影片。'));};
  document.head.append(script);
 });
 return youtubeAPI;
}
async function playYouTubeRange(start,end,label){
 stopVideo();
 const request=playbackRequest;
 playbackRange={start,end,label,audio:false,free:false};
 $('#media-area').classList.add('playing');$('#slide-view').hidden=true;
 $('#video-view').hidden=false;$('#video-tools').hidden=false;$('#lesson-video').hidden=true;
 $('#video-youtube').href=youtubeAt(start);
 const message=$('#video-message');message.textContent='正在載入 YouTube…';
 const mount=document.createElement('div');mount.id='youtube-player';$('#video-view').append(mount);
 updateMediaVisibility();
 try{
  const YT=await loadYouTubeAPI();if(request!==playbackRequest)return;
  let finished=false,lastTime=start,lastWall=performance.now();
  youtubePlayer=new YT.Player(mount,{width:'100%',height:'100%',videoId:DATA.youtube_source_id,
   playerVars:{playsinline:1,origin:location.origin},events:{
    onReady:event=>{
     if(request!==playbackRequest)return;
     message.textContent='若未自動播放，請按 YouTube 播放鍵。';
     event.target.loadVideoById({videoId:DATA.youtube_source_id,startSeconds:start});
     youtubePoll=setInterval(()=>{
      if(request!==playbackRequest||!youtubePlayer)return;
      const t=youtubePlayer.getCurrentTime(),now=performance.now();
      if(youtubePlayer.getPlayerState()!==1){lastTime=t;lastWall=now;return;}
      const expected=(now-lastWall)/1000*(youtubePlayer.getPlaybackRate()||1);
      if(t<lastTime-1||t-lastTime>expected+2)playbackRange.free=true;
      lastTime=t;lastWall=now;
      updateSpeaking(t);if(playbackRange.free)syncPlaybackPosition(t);
      if(!playbackRange.free&&t>=end+PLAYBACK_TAIL){finished=true;youtubePlayer.pauseVideo();message.textContent=label+'已播完；按播放可繼續。';}
     },100);
    },
    onStateChange:event=>{
     if(request!==playbackRequest)return;
     if(event.data===1){if(finished){playbackRange.free=true;finished=false;}message.textContent='';}
     else updateSpeaking(null);
    },
    onError:()=>{if(request===playbackRequest)message.textContent='此影片無法嵌入播放，請使用「在 YouTube 開啟」。';}
   }});
 }catch(error){if(request===playbackRequest)message.textContent=error.message;}
}
