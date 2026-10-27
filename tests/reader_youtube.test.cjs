const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('reader.js','utf8');
function harness(){
 const elements=new Map(),intervals=new Map();let options,clock=0;
 const $=s=>{if(!elements.has(s))elements.set(s,{hidden:false,textContent:'',classList:{add(){}},append(){}});return elements.get(s);};
 const player={time:10,status:1,getCurrentTime(){return this.time},getPlayerState(){return this.status},getPlaybackRate(){return 1},loadVideoById(v){this.loaded=v},pauseVideo(){this.status=2},destroy(){this.destroyed=true}};
 const c=vm.createContext({DATA:{youtube_source_id:'AP9JV9cCZTk'},$,location:{origin:'https://example.test'},document:{createElement(){return {}}},performance:{now:()=>clock},PLAYBACK_TAIL:.3,
  setInterval(fn){intervals.set(1,fn);return 1},clearInterval(id){intervals.delete(id)},updateSpeaking(){},syncPlaybackPosition(){},updateMediaVisibility(){},youtubeAt:t=>'https://youtube.test/'+t,
  window:{YT:{Player:function(m,o){options=o;return player}}}});
 vm.runInContext('let playbackRequest=0,playbackRange=null,youtubePlayer=null,youtubePoll=null; function stopVideo(){playbackRequest++;clearInterval(youtubePoll);if(youtubePlayer)youtubePlayer.destroy();}',c);
 vm.runInContext(source.slice(source.indexOf('let youtubeAPI=null;')),c);
 return {c,player,$,get options(){return options},tick(t){player.time=t;clock+=100;intervals.get(1)?.()}};
}
test('YouTube segment pauses at its boundary and resumes freely',async()=>{
 const h=harness();await h.c.playYouTubeRange(10,12,'此句');h.options.events.onReady({target:h.player});
 assert.equal(h.player.loaded.startSeconds,10);assert.equal(h.$('#video-view').hidden,false);
 for(let t=10;t<12.5;t+=.1)h.tick(t);
 assert.equal(h.player.status,2);
 h.options.events.onStateChange({data:1});h.player.status=1;h.tick(13);
 assert.equal(h.player.status,1);
});
test('YouTube pending load cannot revive a stopped selection',async()=>{
 const h=harness();const pending=h.c.playYouTubeRange(10,12,'此句');h.c.stopVideo();await pending;
 assert.equal(h.options,undefined);
});
test('YouTube embed errors retain a usable original-video link',async()=>{
 const h=harness();await h.c.playYouTubeRange(10,12,'此句');h.options.events.onError();
 assert.match(h.$('#video-message').textContent,/無法嵌入/);assert.match(h.$('#video-youtube').href,/10/);
});
