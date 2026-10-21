const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const src=fs.readFileSync('reader.js','utf8');
function group(transcript,sections,reading_transcript){
 const c={DATA:{transcript,reading_transcript},sourceIds:p=>p.source_ids};vm.createContext(c);
 vm.runInContext(src.slice(src.indexOf('function transcriptGroups('),src.indexOf('function renderTranscript(')),c);
 return JSON.parse(JSON.stringify(c.transcriptGroups({sections})));
}
test('connected short phrases become one passage without changing source data',()=>{
 const tx=Array.from({length:4},(_,i)=>({start:39+i*2,end:41+i*2,text:'連續講解'}));
 const before=JSON.stringify(tx);
 assert.deepEqual(group(tx,[{time:39,end:49,source_ids:[0,1,2,3]}]),[[0,1,2,3]]);
 assert.equal(JSON.stringify(tx),before);
});
test('topic changes, missing IDs and pauses never bridge a passage',()=>{
 const tx=Array.from({length:5},(_,i)=>({start:i*4,end:i*4+2,text:'講解'}));
 assert.deepEqual(group(tx,[{time:0,end:20,source_ids:[0,1,3,4]}]),[[0],[1],[3],[4]]);
 tx.forEach(t=>t.end=t.start+4);
 assert.deepEqual(group(tx,[{time:0,end:8,source_ids:[0,1]},{time:8,end:20,source_ids:[2,3,4]}]),[[0,1],[2,3,4]]);
});
test('long passages split with every source preserved exactly once',()=>{
 const tx=Array.from({length:30},(_,i)=>({start:i*3,end:i*3+3,text:'內容'.repeat(10)}));
 const groups=group(tx,[{time:0,end:90,source_ids:tx.map((_,i)=>i)}]);
 assert.deepEqual(groups.flat(),tx.map((_,i)=>i));
 assert.ok(groups.every(g=>tx[g.at(-1)].end-tx[g[0]].start<=28));
 assert.ok(groups.every(g=>g.length*20<=180));
});

test('authored sentence boundaries keep a thought intact across note subdivisions',()=>{
 const tx=Array.from({length:4},(_,i)=>({start:i*10,end:i*10+10,text:'語句'}));
 const reading=Object.fromEntries(tx.map((t,i)=>[i,{original:t.text,text:t.text,paragraph_end:i===2||i===3}]));
 assert.deepEqual(group(tx,[{time:0,end:20,source_ids:[0,1]},{time:20,end:40,source_ids:[2,3]}],reading),[[0,1,2],[3]]);
});
test('reading layer yields to manual corrections and stale source matches',()=>{
 const c={DATA:{transcript:[{text:'原句'}],reading_transcript:{0:{original:'原句',text:'原句。'}}},manualEdits:{}};
 vm.createContext(c);
 vm.runInContext(src.slice(src.indexOf('function transcriptText('),src.indexOf('async function editTranscript(')),c);
 assert.equal(c.readingText(0),'原句。');
 c.manualEdits[0]={corrected:'人工修訂！'};
 assert.equal(c.readingText(0),'人工修訂！');
 delete c.manualEdits[0];c.DATA.reading_transcript[0].original='舊原句';
 assert.equal(c.readingText(0),'原句');
});
