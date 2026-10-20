const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'..','reader.js'),'utf8');
test('free playback follows occurrence boundaries, paragraphs, revisits and backward seeks',()=>{
 const state={segment:1,paragraph:0};let switches=[],selections=[];
 const context=vm.createContext({playbackRange:{free:true},savingEdits:new Set(),document:{activeElement:null},state,
 DATA:{segments:[{start:0,end:30},{start:0,end:10,sections:[{time:0,end:5},{time:5,end:10}]},{start:10,end:20,sections:[{time:11,end:20}]},{start:20,end:30,sections:[{time:20,end:30}]}]},
 showPlaybackSegment(i){switches.push(i);state.segment=i;state.paragraph=-1;},setParagraph(i){selections.push(i);state.paragraph=i;},$:()=>null});
 vm.runInContext(source.slice(source.indexOf('function syncPlaybackPosition('),source.indexOf('function showSegment(')),context);
 context.syncPlaybackPosition(5);assert.deepEqual(selections,[1]);
 context.syncPlaybackPosition(10);assert.deepEqual(switches,[2]);assert.equal(state.paragraph,0);
 context.syncPlaybackPosition(20);assert.deepEqual(switches,[2,3]);
 context.syncPlaybackPosition(2);assert.deepEqual(switches,[2,3,1]);
 context.playbackRange.free=false;context.syncPlaybackPosition(25);assert.equal(state.segment,1);
});
test('content refresh keeps every ancestor of the playing audio connected',()=>{
 function node(name){return {name,children:[],parentElement:null,hidden:false,attrs:{},className:'',removeAttribute(k){delete this.attrs[k]},append(n){this.children.push(n);n.parentElement=this},contains(n){return n===this||this.children.some(c=>c.contains(n))},remove(){const p=this.parentElement;p.children=p.children.filter(c=>c!==this);this.parentElement=null},insertAdjacentHTML(_,html){this.html=html}}}
 const pane=node('pane'),row=node('old-row'),slot=node('slot'),player=node('player'),oldText=node('old-text'),otherRow=node('other-row');
 pane.append(row);pane.append(otherRow);row.append(oldText);row.append(slot);slot.append(player);row.attrs['data-source']='9';slot.attrs['data-audio-source']='9';
 const context=vm.createContext({$:()=>player});vm.runInContext(source.slice(source.indexOf('function replaceContentKeepingAudio('),source.indexOf('function showPlaybackSegment(')),context);
 context.replaceContentKeepingAudio(pane,'new chapter');
 assert.equal(player.parentElement,slot);assert.equal(slot.parentElement,row);assert.equal(row.parentElement,pane);assert.equal(oldText.parentElement,null);assert.equal(otherRow.parentElement,null);assert.equal(row.attrs['data-source'],undefined);assert.equal(pane.html,'new chapter');
 context.replaceContentKeepingAudio(pane,'another chapter');assert.equal(player.parentElement,slot);assert.equal(slot.parentElement,row);assert.equal(pane.html,'another chapter');
});
