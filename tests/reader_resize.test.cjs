const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'reader.js'), 'utf8');
function sizing(width=1440) {
 const attrs={};
 const root={clientHeight:600,style:{setProperty(k,v){this[k]=v}}};
 const context=vm.createContext({window:{innerWidth:width},$:key=>key==='#reading'?root:{setAttribute(k,v){attrs[k]=v}}});
 vm.runInContext('let splitFraction=.45;'+source.slice(source.indexOf('function setSplit('),source.indexOf('function updateMediaVisibility(')),context);
 return {context,root,attrs};
}
test('split clamps both extremes and announces the desktop divider direction',()=>{
 const {context:c,root,attrs}=sizing();
 c.setSplit(.95);assert.equal(root.style['--media-share'],.7);assert.equal(attrs['aria-valuenow'],70);assert.equal(attrs['aria-orientation'],'vertical');
 c.setSplit(.01);assert.equal(root.style['--media-share'],.2);
});
test('mobile divider uses the horizontal orientation; hidden reading is not resized',()=>{
 const {context:c,root,attrs}=sizing(390);
 c.setSplit(.45);assert.equal(attrs['aria-orientation'],'horizontal');
 root.clientHeight=0;c.setSplit(.6);assert.equal(root.style['--media-share'],.45);
});
test('overview follows slide occurrences including revisits and annotation changes',()=>{
 const view={dataset:{},innerHTML:''},caption={};
 const context=vm.createContext({DATA:{segments:[{image:null},{image:'a.jpg',title:'First',start:0,end:10},{image:'b.jpg',title:'Next',start:10,end:20},{image:'a-revisit.jpg',title:'Revisit',start:20,end:30}]},state:{segment:0},esc:s=>s,$:key=>key==='#slide-view'?view:caption});
 vm.runInContext(source.slice(source.indexOf('function syncReadingSlide('),source.indexOf("document.addEventListener('click',e=>{",source.indexOf('function syncReadingSlide('))),context);
 context.syncReadingSlide({time:10});assert.equal(view.dataset.image,'b.jpg');
 context.syncReadingSlide({time:20});assert.equal(view.dataset.image,'a-revisit.jpg');assert.equal(caption.textContent,'Revisit');
 context.state.segment=1;context.syncReadingSlide({time:22});assert.equal(view.dataset.image,'a.jpg');
});
function drawer() {
 const elements={};const listeners={};let focused=0;
 for(const id of ['#chapter-nav','#chapter-dock','#toggle-nav','#chapter-tab','#search','#sources','#transcript-divider','#toggle-transcript','#close-transcript'])elements[id]={hidden:true,attrs:{},classList:{toggle(){}},setAttribute(k,v){this.attrs[k]=v},contains(el){return el===this},focus(){focused++},addEventListener(type,fn){listeners[type]=fn}};
 const layout={clientHeight:800,style:{setProperty(k,v){this[k]=v}},classList:{toggle(){}}};
 const document={activeElement:null,querySelector(){return layout}};
 const context=vm.createContext({DATA:{},$:key=>elements[key],document,window:{innerWidth:1440},scrollTranscript(){},persistLayoutPreferences(){}});
 vm.runInContext('let navPinned=false,transcriptFraction=null,transcriptOpen=false;'+source.slice(source.indexOf('function setNav('),source.indexOf('function syncReadingSlide(')),context);
 return {context,elements,layout,listeners,focusCount:()=>focused};
}
test('drawer height stays bounded and retains its ratio when reopened',()=>{
 const {context:c,elements,layout}=drawer();
 c.setTranscript(true);const initial=layout.style['--transcript-height'];
 c.setTranscriptHeight(.95);assert.ok(parseFloat(layout.style['--transcript-height'])<=786*.7);
 assert.equal(elements['#transcript-divider'].hidden,false);
 const expanded=layout.style['--transcript-height'];c.setTranscript(false);assert.equal(elements['#transcript-divider'].hidden,true);
 c.setTranscript(true);assert.equal(layout.style['--transcript-height'],expanded);assert.notEqual(initial,expanded);
 layout.clientHeight=280;c.setTranscriptHeight(.7);assert.ok(parseFloat(layout.style['--transcript-height'])<=86);
});
test('chapter drawer changes state immediately and never opens on hover',()=>{
 const {context:c,elements,listeners,focusCount}=drawer();
 assert.equal(listeners.pointerenter,undefined);
 c.setNav(true);assert.equal(elements['#chapter-nav'].hidden,false);assert.equal(elements['#chapter-nav'].inert,false);assert.equal(focusCount(),1);
 c.setNav(false);assert.equal(elements['#chapter-nav'].hidden,true);assert.equal(elements['#chapter-nav'].inert,true);
 c.setNav(true);assert.equal(elements['#chapter-tab'].attrs['aria-expanded'],'true');
});

function preferences(storage) {
 const elements={
  '#reading':{clientHeight:600,style:{setProperty(){}}},
  '#media-divider':{setAttribute(){}},'#transcript-divider':{setAttribute(){}},
  '#layout-storage-status':{hidden:true,textContent:''}
 };
 const layout={clientHeight:800,style:{setProperty(){}}};
 const c=vm.createContext({DATA:{youtube_id:'course-a'},localStorage:storage,$:key=>elements[key],window:{innerWidth:1440},document:{querySelector(){return layout}}});
 vm.runInContext('let splitFraction=.45,transcriptFraction=null,transcriptOpen=false;'+source.slice(source.indexOf('const LAYOUT_KEY='),source.indexOf('let manualEdits='))+source.slice(source.indexOf('function setSplit('),source.indexOf('function updateMediaVisibility('))+source.slice(source.indexOf('function setTranscriptHeight('),source.indexOf('function syncReadingSlide(')),c);
 return {c,layout,elements,values:()=>JSON.parse(vm.runInContext('JSON.stringify([splitFraction,transcriptFraction])',c))};
}
test('explicit layout changes survive a fresh page; resize does not overwrite preferred height',()=>{
 const data=new Map();const storage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)};
 const first=preferences(storage);first.c.setSplit(.57,true);first.c.setTranscriptHeight(.6,true);
 const saved=data.get('lecturethread:layout:v1:course-a');
 first.layout.clientHeight=280;first.c.setTranscriptHeight(.6);assert.equal(data.get('lecturethread:layout:v1:course-a'),saved);
 const reopened=preferences(storage);reopened.c.restoreLayoutPreferences();assert.deepEqual(reopened.values(),[.57,.6]);
});
test('invalid or unavailable layout storage keeps valid defaults and does not block resizing',()=>{
 for(const value of ['{broken','null','{"schema":2,"slideFraction":0.6}','{"schema":1,"slideFraction":"0.6","transcriptFraction":999}']){
  const page=preferences({getItem:()=>value});page.c.restoreLayoutPreferences();assert.deepEqual(page.values(),[.45,null]);
 }
 const page=preferences({getItem(){throw Error('blocked')},setItem(){throw Error('blocked')}});
 page.c.restoreLayoutPreferences();page.c.setSplit(.55,true);page.c.setTranscriptHeight(.5,true);
 assert.deepEqual(page.values(),[.55,.5]);assert.equal(page.elements['#layout-storage-status'].hidden,false);
});
test('transcript open state survives a fresh page and old preferences remain compatible',()=>{
 const data=new Map(),storage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)};
 const first=preferences(storage);vm.runInContext('transcriptOpen=true;persistLayoutPreferences()',first.c);
 const reopened=preferences(storage);reopened.c.restoreLayoutPreferences();assert.equal(vm.runInContext('transcriptOpen',reopened.c),true);
 vm.runInContext('transcriptOpen=false;persistLayoutPreferences()',reopened.c);
 const closed=preferences(storage);closed.c.restoreLayoutPreferences();assert.equal(vm.runInContext('transcriptOpen',closed.c),false);
});
