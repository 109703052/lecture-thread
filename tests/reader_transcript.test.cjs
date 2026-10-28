const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const {join}=require('node:path');
const vm=require('node:vm');

function transcript(saved=new Map(),backend={revision:"v0",version:0,edits:{}}){
 const elements=new Map(),rows=[];let scrolls=0,download;
 function element(key){
  if(!elements.has(key))elements.set(key,{hidden:false,textContent:'',value:'',dataset:{},clientHeight:400,scrollTop:0,offsetHeight:80,
   focus(){},contains(){return false;},getBoundingClientRect(){return {top:0,bottom:400};},scrollTo(){scrolls++;},
   setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];},classList:{toggle(){}},
   querySelectorAll(){return [];},isConnected:true,querySelector(selector){return element(key+' '+selector);}});
  return elements.get(key);
 }
 for(let i=0;i<3;i++){
  const row=element(`.utterance[data-source="${i}"]`);row.dataset.source=String(i);
  const query=row.querySelector.bind(row);
  row.querySelector=selector=>selector==='[data-edit="save"]'?query('.transcript-editor [data-edit="save"]'):query(selector);
  row.classList={toggle(name,value){row[name]=value;}};
  row.getBoundingClientRect=()=>({top:450,bottom:550});rows.push(row);
 }
 const DATA={youtube_id:'fixture',transcript_revision:'rev-a',transcript:[
  {start:0,end:2,text:'原句一'},{start:2,end:4,text:'原句二'},{start:5,end:6,text:'原句三'}]};
 const context=vm.createContext({DATA,$:element,state:{follow:true},stamp:String,Date,
  document:{activeElement:null,querySelectorAll(){return rows;},createElement(){return {click(){download=this;}};}},
  sessionStorage:{getItem(k){return saved.get(k)||null;},setItem(k,v){saved.set(k,v);}},
  localStorage:{getItem(){return null;}},location:{protocol:'http:',hostname:'127.0.0.1'},
  async fetch(url,options={}){
   const snapshot=()=>({youtube_id:'fixture',transcript_revision:backend.base||'rev-a',revision:backend.revision,edits:JSON.parse(JSON.stringify(backend.edits)),csrf_token:'token'});
   if(options.method==='POST'){
    const request=JSON.parse(options.body);
    if(request.revision!==backend.revision)return {ok:false,status:409,json:async()=>({error:'其他分頁已更新',snapshot:snapshot()})};
    const id=request.segment_id,base=DATA.transcript[id];
    if(request.corrected===base.text)delete backend.edits[id];
    else backend.edits[id]={original:base.text,corrected:request.corrected,start:base.start,end:base.end};
    backend.revision='v'+(++backend.version);
   }
   return {ok:true,status:200,json:async()=>snapshot()};
  },
  Blob:class{constructor(parts){this.parts=parts;}},URL:{createObjectURL(blob){context.backup=JSON.parse(blob.parts[0]);return 'blob:fixture';},revokeObjectURL(){}},setTimeout(){}});
 const source=readFileSync(join(__dirname,'..','reader.js'),'utf8');
 vm.runInContext('let playbackRange=null;\n'+source.slice(source.indexOf('const EDITS_KEY='),source.indexOf('function setSplit(')),context);
 return {context,element,rows,saved,DATA,backend,scrolls:()=>scrolls,download:()=>download,
  draft(id,text){element(`.utterance[data-source="${id}"] .transcript-editor textarea`).value=text;},
  range(start,end,free=false){vm.runInContext(`playbackRange={start:${start},end:${end},free:${free}}`,context);}};
}

test('save uses local authority and reloads server data without changing the base transcript',async()=>{
 const t=transcript();await t.context.loadManualEdits();
 await t.context.editTranscript(0,'open');t.draft(0,'手動修正 <b>純文字</b>');await t.context.editTranscript(0,'save');
 assert.equal(t.DATA.transcript[0].text,'原句一');
 assert.equal(t.backend.edits[0].corrected,'手動修正 <b>純文字</b>');
 const reloaded=transcript(new Map(),t.backend);await reloaded.context.loadManualEdits();
 assert.equal(reloaded.context.transcriptText(0),'手動修正 <b>純文字</b>');
 reloaded.context.exportManualEdits();assert.equal(reloaded.context.backup.edits[0].original,'原句一');
 assert.equal(reloaded.download().download,'fixture.transcript.manual-edits.json');
});

test('cancel, empty validation and restoring base text preserve expected content',async()=>{
 const t=transcript();await t.context.loadManualEdits();await t.context.editTranscript(0,'open');
 t.draft(0,'取消');await t.context.editTranscript(0,'cancel');assert.equal(t.context.transcriptText(0),'原句一');
 await t.context.editTranscript(0,'open');t.draft(0,'   ');await t.context.editTranscript(0,'save');
 assert.equal(t.element('.utterance[data-source="0"] .transcript-editor').hidden,false);
 assert.equal(Object.keys(t.backend.edits).length,0);
 t.draft(0,'修正');await t.context.editTranscript(0,'save');
 await t.context.editTranscript(0,'open');t.draft(0,'原句一');await t.context.editTranscript(0,'save');
 assert.equal(t.context.transcriptText(0),'原句一');assert.equal(Object.keys(t.backend.edits).length,0);
});

test('network failure keeps a reloadable browser draft and never claims a successful file save',async()=>{
 const t=transcript();await t.context.loadManualEdits();
 t.context.fetch=async()=>{throw Error('offline');};
 await t.context.editTranscript(0,'open');t.draft(0,'尚未儲存');await t.context.editTranscript(0,'save');
 assert.equal(t.context.transcriptText(0),'原句一');assert.equal(Object.keys(t.backend.edits).length,0);
 const restored=transcript(t.saved,t.backend);restored.context.restoreDrafts();
 await restored.context.editTranscript(0,'open');
 assert.equal(restored.element('.utterance[data-source="0"] .transcript-editor textarea').value,'尚未儲存');
 assert.match(t.element('.utterance[data-source="0"] .transcript-editor [role="status"]').textContent,/草稿未刪除/);
});

test('two tabs cannot overwrite each other until a conflict is reviewed and explicitly retried',async()=>{
 const a=transcript(),b=transcript(new Map(),a.backend);
 await a.context.loadManualEdits();await b.context.loadManualEdits();
 await a.context.editTranscript(0,'open');await b.context.editTranscript(0,'open');
 a.draft(0,'分頁A');await a.context.editTranscript(0,'save');
 b.draft(0,'分頁B');await b.context.editTranscript(0,'save');
 assert.equal(a.backend.edits[0].corrected,'分頁A');
 assert.equal(b.element('.utterance[data-source="0"] .transcript-editor textarea').value,'分頁B');
 assert.match(b.element('.utterance[data-source="0"] .transcript-editor [role="status"]').textContent,/分頁A/);
 assert.equal(b.element('.utterance[data-source="0"] .transcript-editor [data-edit="save"]').textContent,'確認並儲存此草稿');
 const resumed=transcript(b.saved,a.backend);resumed.context.restoreDrafts();await resumed.context.loadManualEdits();await resumed.context.editTranscript(0,'open');
 assert.equal(resumed.element('.utterance[data-source="0"] .transcript-editor [data-edit="save"]').textContent,'確認並儲存此草稿');
 await resumed.context.editTranscript(0,'save');assert.equal(a.backend.edits[0].corrected,'分頁B');
});

test('reloaded stale drafts still conflict with edits saved by another tab',async()=>{
 const a=transcript();await a.context.loadManualEdits();await a.context.editTranscript(0,'open');
 a.draft(0,'舊草稿');a.context.fetch=async()=>{throw Error('offline');};await a.context.editTranscript(0,'save');
 const b=transcript(new Map(),a.backend);await b.context.loadManualEdits();await b.context.editTranscript(0,'open');b.draft(0,'最新');await b.context.editTranscript(0,'save');
 const restored=transcript(a.saved,a.backend);restored.context.restoreDrafts();await restored.context.loadManualEdits();
 await restored.context.editTranscript(0,'open');await restored.context.editTranscript(0,'save');
 assert.equal(a.backend.edits[0].corrected,'最新');
 assert.equal(restored.element('.utterance[data-source="0"] .transcript-editor textarea').value,'舊草稿');
});

test('playing sentence advances, handles gaps, constrains tail and clears on pause',()=>{
 const t=transcript();t.range(0,4);
 t.context.updateSpeaking(.5);assert.equal(t.rows[0]['is-speaking'],true);
 t.context.updateSpeaking(2.1);assert.equal(t.rows[0]['is-speaking'],false);assert.equal(t.rows[1]['is-speaking'],true);
 t.context.updateSpeaking(4.2);assert.equal(t.rows[1]['is-speaking'],true,'tail padding must not mark the next sentence');
 t.context.updateSpeaking(null);assert.equal(t.rows[1]['is-speaking'],false);
 assert.equal(t.element('#speaking-status').textContent,'');
 t.range(0,6);t.context.updateSpeaking(4.5);assert.equal(t.rows.some(r=>r['is-speaking']),false);
});

test('following scrolls only sources and respects an editor or disabled follow',()=>{
 const t=transcript();t.range(0,6);t.context.updateSpeaking(.5);assert.equal(t.scrolls(),1);
 t.context.editTranscript(0,'open');t.context.updateSpeaking(2.5);assert.equal(t.scrolls(),1);
 t.context.editTranscript(0,'cancel');t.context.state.follow=false;t.context.updateSpeaking(5.2);assert.equal(t.scrolls(),1);
 assert.equal(t.rows[2]['is-speaking'],true);
});

test('playback follows the visible sentence rather than snapping a tall reading group to its start',()=>{
 const t=transcript();t.range(0,6);
 let rect={top:170,bottom:240};
 let sentence={getBoundingClientRect:()=>rect};
 const group={classList:{contains:()=>false},querySelector:()=>sentence,getBoundingClientRect:()=>({top:-600,bottom:1600})};
 t.rows.forEach(row=>row.closest=()=>group);
 t.context.updateSpeaking(.5);assert.equal(t.scrolls(),0,'visible sentence in oversized group stays still');
 rect={top:20,bottom:250};t.context.updateSpeaking(2.5);assert.equal(t.scrolls(),0,'partially visible long sentence stays still');
 sentence={getBoundingClientRect:()=>({top:450,bottom:520})};t.context.updateSpeaking(5.2);assert.equal(t.scrolls(),1,'next fully offscreen sentence is followed');
});

test('one reading sentence spans original boundaries and pauses without repeated scrolls',()=>{
 const t=transcript();t.range(0,6);t.DATA.transcript[1].start=2.5;
 const sentence={dataset:{sentenceIds:'0,1'},getBoundingClientRect:()=>({top:450,bottom:550}),classList:{toggle(name,value){sentence[name]=value;}}};
 const group={classList:{contains:()=>false},querySelector:()=>sentence};
 sentence.closest=()=>group;t.rows.forEach(row=>row.closest=()=>group);
 t.context.document.querySelectorAll=selector=>selector==='.reading-sentence'?[sentence]:t.rows;
 t.context.updateSpeaking(.5);assert.equal(t.scrolls(),1);assert.equal(sentence['is-speaking'],true);
 t.context.updateSpeaking(2.2);assert.equal(sentence['is-speaking'],true,'reading interval includes gaps between originals');assert.equal(t.rows.some(row=>row['is-speaking']),false);
 t.context.updateSpeaking(2.6);assert.equal(t.rows[1]['is-speaking'],true);assert.equal(t.scrolls(),1,'new original inside same reading sentence does not scroll');
 t.context.updateSpeaking(4.5);assert.equal(sentence['is-speaking'],false,'reading highlight ends at its own end');
});

test('manual scrolling pauses follow without losing playback highlight and explicit resume targets the sentence',()=>{
 const t=transcript();t.range(0,6);
 t.context.pauseTranscriptFollow();const count=t.scrolls();
 assert.equal(t.context.state.follow,false);
 t.context.updateSpeaking(2.5);
 assert.equal(t.rows[1]['is-speaking'],true);
 assert.equal(t.scrolls(),count,'playback cannot override manual reading position');
 assert.equal(t.element('#follow').textContent,'回到播放位置');
 t.context.state.follow=true;t.context.updateFollowControl();t.context.scrollPlaybackSentence(true);
 assert.equal(t.scrolls(),count+1);
 assert.equal(t.element('#follow')['aria-pressed'],'true');
});

test('free playback highlights the actual sentence outside the initial range',()=>{
 const t=transcript();t.range(0,2,true);t.context.updateSpeaking(5.2);
 assert.equal(t.rows[2]['is-speaking'],true);assert.equal(t.rows[0]['is-speaking'],false);
 t.context.updateSpeaking(.5);assert.equal(t.rows[0]['is-speaking'],true);
});

test('authored reading uses all original snapshots and falls back after a saved correction',async()=>{
 const t=transcript();t.DATA.reading_paragraphs=[{source_ids:[0,1],originals:['原句一','原句二'],text:'修順的合段'}];
 await t.context.loadManualEdits();
 assert.equal(t.context.readingParagraphText([0,1]),'修順的合段');
 await t.context.editTranscript(0,'open');
 assert.equal(t.element('.utterance[data-source="0"] .transcript-editor textarea').value,'原句一');
 t.draft(0,'新校字');await t.context.editTranscript(0,'save');
 assert.equal(t.backend.edits[0].corrected,'新校字');
 assert.equal(t.context.readingParagraphText([0,1]),'新校字，原句二');
 assert.equal(t.DATA.reading_paragraphs[0].text,'修順的合段');
 assert.equal(t.DATA.transcript[0].text,'原句一');
});

test('reading can be authored from existing manual corrections without treating polish as original',async()=>{
 const t=transcript();t.backend.edits[0]={corrected:'已校字'};
 t.DATA.reading_paragraphs=[{source_ids:[0,1],originals:['已校字','原句二'],text:'另外修順'}];
 await t.context.loadManualEdits();
 assert.equal(t.context.readingParagraphText([0,1]),'另外修順');
 await t.context.editTranscript(0,'open');
 assert.equal(t.element('.utterance[data-source="0"] .transcript-editor textarea').value,'已校字');
});

test('reading sentences link to their originals and fall back to plain text after a correction',async()=>{
 const t=transcript();t.context.esc=s=>String(s).replace(/[&<>"]/g,c=>'&#'+c.charCodeAt(0)+';');
 t.DATA.reading_paragraphs=[{source_ids:[0,1],originals:['原句一','原句二'],text:'第一句。第二<句>。',
  sentences:[{text:'第一句。',source_ids:[0]},{text:'第二<句>。',source_ids:[0,1]}]}];
 await t.context.loadManualEdits();
 const html=t.context.readingParagraphHTML([0,1]);
 assert.match(html,/<span class="reading-sentence"[^>]*role="button"[^>]*tabindex="0"[^>]*data-sentence-ids="0" data-return="0">第一句。<\/span>/);
 assert.match(html,/data-sentence-ids="0,1" data-return="0">第二&#60;句&#62;。<\/span>/);
 await t.context.editTranscript(0,'open');t.draft(0,'新校字');await t.context.editTranscript(0,'save');
 const revised=t.context.readingParagraphHTML([0,1]);
 assert.match(revised,/data-sentence-ids="0" data-return="0">新校字<\/span>/);
 assert.match(revised,/data-sentence-ids="1" data-return="1">原句二<\/span>/);
});
