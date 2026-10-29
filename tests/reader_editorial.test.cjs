const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'..','reader.js'),'utf8');

test('editorial reading uses each actual occurrence, including annotation changes and revisits',()=>{
 const view={dataset:{},innerHTML:''},caption={textContent:''};
 const context=vm.createContext({DATA:{alignment:'editorial-source-ids-with-occurrence-appendix',segments:[
  {start:0,end:20}, {start:0,end:20,image:'representative.png',title:'Chapter'},
  {occurrence_id:1,start:0,end:5,image:'first.png',title:'First'},
  {occurrence_id:2,start:5,end:10,image:'annotated.png',title:'Annotation'},
  {occurrence_id:3,start:10,end:20,image:'first.png',title:'Revisit'}]},state:{segment:1},
  esc:s=>s,$:selector=>selector==='#slide-view'?view:caption});
 vm.runInContext(source.slice(source.indexOf('function syncReadingSlide('),source.indexOf("document.addEventListener('click',e=>{",source.indexOf('function syncReadingSlide('))),context);
 context.syncReadingSlide({time:1});assert.equal(view.dataset.image,'first.png');
 context.syncReadingSlide({time:5});assert.equal(view.dataset.image,'annotated.png');assert.equal(caption.textContent,'Annotation');
 context.syncReadingSlide({time:12});assert.equal(view.dataset.image,'first.png');assert.equal(caption.textContent,'Revisit');
 context.syncReadingSlide({time:6});assert.equal(view.dataset.image,'annotated.png');
 context.DATA.alignment='source-time-overlap';context.syncReadingSlide({time:6});
 assert.equal(view.dataset.image,'representative.png','legacy course behavior is retained');
});

test('editorial playback updates slides even when the speaking source has not changed',()=>{
 const slides=[];
 const context=vm.createContext({DATA:{alignment:'editorial-source-ids-with-occurrence-appendix',transcript:[]},
  playbackRange:{free:true},speakingSource:-1,speakingReadingSentence:null,lastAutoFollowTarget:null,
  document:{querySelectorAll:()=>[]},syncReadingSlide:s=>slides.push(s.time)});
 vm.runInContext(source.slice(source.indexOf('function updateSpeaking('),source.indexOf('function setSplit(')),context);
 context.updateSpeaking(5);context.updateSpeaking(6);context.updateSpeaking(null);
 assert.deepEqual(slides,[5,6]);
 context.playbackRange={free:false,start:0,end:8};context.updateSpeaking(9);
 assert.equal(slides.at(-1),7.999,'bounded playback retains the final actual occurrence');
});

test('editorial playback chooses the chapter before its overlapping source appendix',()=>{
 const state={segment:1,paragraph:0,notesFollow:true};let switches=[];
 const context=vm.createContext({playbackRange:{free:true},savingEdits:new Set(),document:{activeElement:null},state,
 DATA:{segments:[{start:0,end:20},
  {start:0,end:10,sections:[{time:0,end:10}]},{start:10,end:20,sections:[{time:10,end:20}]},
  {occurrence_id:1,start:0,end:5,sections:[{time:0,end:5}]},{occurrence_id:2,start:5,end:20,sections:[{time:5,end:20}]}]},
 showPlaybackSegment(i){switches.push(i);state.segment=i;state.paragraph=-1;},setParagraph(i){state.paragraph=i;},$:()=>null});
 vm.runInContext(source.slice(source.indexOf('function syncPlaybackPosition('),source.indexOf('function showSegment(')),context);
 context.syncPlaybackPosition(6);assert.equal(state.segment,1);
 context.syncPlaybackPosition(12);assert.deepEqual(switches,[2]);
 context.syncPlaybackPosition(3);assert.deepEqual(switches,[2,1]);
});
