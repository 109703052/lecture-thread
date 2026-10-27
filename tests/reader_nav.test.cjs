const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'..','reader.js'),'utf8');
test('formal navigation excludes occurrences, lazy source pages preserve indices and search',()=>{
 const formal={title:'正式講義',region:'講義',sections:[],start:0,end:10};
 const segments=[formal,{...formal,title:'第二章'},...Array.from({length:75},(_,i)=>({...formal,title:'來源畫面 '+i,occurrence_id:i}))];
 const elements=Object.fromEntries(['segments','source-nav','source-search','source-segments','source-more','source-count'].map(k=>['#'+k,{value:'',innerHTML:'',open:false}]));
 const c=vm.createContext({DATA:{segments},state:{segment:0},$:s=>elements[s],esc:s=>s,stamp:String});
 vm.runInContext(source.slice(source.indexOf('let sourceNavLimit='),source.indexOf('function renderNotes(')),c);
 c.renderNav();assert.equal((elements['#segments'].innerHTML.match(/data-segment=/g)||[]).length,2);assert.equal(elements['#source-segments'].innerHTML,'');
 assert.equal(c.adjacentSegment(1,1),-1);assert.equal(c.adjacentSegment(2,-1),-1);assert.equal(c.adjacentSegment(2,1),3);
 c.renderSourceNav();assert.equal((elements['#source-segments'].innerHTML.match(/data-segment=/g)||[]).length,60);assert.equal(elements['#source-more'].hidden,false);
 vm.runInContext('sourceNavLimit+=60',c);c.renderSourceNav();assert.equal((elements['#source-segments'].innerHTML.match(/data-segment=/g)||[]).length,75);
 elements['#source-search'].value='來源畫面 74';c.renderSourceNav();assert.match(elements['#source-segments'].innerHTML,/data-segment="76"/);
});
