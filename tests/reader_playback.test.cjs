const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function reader() {
  const elements = new Map();
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      hidden: true, textContent: '', dataset: {}, clientHeight: 400, scrollTop: 0, append(child) {child.parentElement=this;}, scrollIntoView() {},
      setAttribute(name, value) { this[name] = value; }, contains() {return false;},
      classList: { add() {}, remove() {}, toggle() {} },
    });
    return elements.get(selector);
  };
  const pendingRejects = [];
  const video = element('#lesson-video'), audio = element('#lesson-audio');
  for (const media of [video, audio]) Object.assign(media, {
    readyState: 0, paused: true, currentTime: 0, duration: 100, playbackRate: 1,
    getAttribute(name) { return this[name] || null; },
    removeAttribute(name) { delete this[name]; },
    pause() { this.paused = true; this.onpause?.(); },
    load() { this.currentTime = 0; this.readyState = 0; },
    play() { this.paused = false; this.onplay?.(); return new Promise((_, reject) => { pendingRejects.push(reject); }); },
  });
  const timers = new Map(); let nextTimer = 0;
  const listeners = {};
  const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'reader.js'), 'utf8');
  const playback = source.slice(source.indexOf('function stopVideo('), source.indexOf("document.addEventListener('pointerdown'"));
  const context = vm.createContext({
    DATA: { transcript: [{ start: 12, end: 14 }, { start: 42, end: 45 }], video_src: 'lecture.mp4',
      segments: [{image: 'slide.jpg', sections: [{time: 10, end: 50, source_ids: [0, 1]}, {time: 50, end: 60, source_ids: []}]}] },
    state: {segment: 0},
    document: { body: { dataset: {} }, querySelectorAll() {return [];}, addEventListener(type, callback) { listeners[type] = callback; } },
    $: element, youtubeAt: t => String(t), stamp: t => String(t), setParagraph() {}, setSplit() {}, syncPlaybackPosition() {},
    setTimeout(callback, ms) { const id = ++nextTimer; timers.set(id, {callback, ms}); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  const globals = source.slice(source.indexOf('let playbackRequest='), source.indexOf('function setSplit('));
  const visibility = source.slice(source.indexOf('function updateMediaVisibility('), source.indexOf('const esc='));
  vm.runInContext(globals + visibility + playback, context);
  vm.runInContext(source.slice(source.indexOf("document.addEventListener('click'"), source.indexOf("document.addEventListener('focusin'")), context);
  return { context, video, audio, timers, element,
    emit(type, event) { listeners[type](event); },
    reject: (index = 0) => pendingRejects[index](new Error('interrupted')) };
}

test('the latest click wins before metadata is ready', () => {
  const { context, video } = reader();
  context.playSource(0,true);
  context.playSource(1,true);
  video.onloadedmetadata();
  assert.equal(video.currentTime, 42);
});

test('hiding unloads media and ignores an obsolete play rejection', async () => {
  const { context, video, element, reject } = reader();
  context.playSource(0,true);
  video.onloadedmetadata();
  context.hideVideo();
  reject();
  await Promise.resolve();
  assert.equal(video.paused, true);
  assert.equal(video.getAttribute('src'), null);
  assert.equal(video.onloadedmetadata, null);
  assert.equal(element('#video-view').hidden, true);
  assert.equal(element('#video-message').textContent, '');
});

test('an older click cannot report an error over a newer request', async () => {
  const { context, video, element, reject } = reader();
  context.playSource(0,true);
  video.onloadedmetadata();
  video.readyState = 1;
  context.playSource(1,true);
  reject(0);
  await Promise.resolve();
  assert.equal(element('#video-message').textContent, '');
});

test('current load errors remain visible after selecting another source', () => {
  const { context, video, element } = reader();
  context.playSource(0,true);
  context.playSource(1,true);
  video.onerror();
  assert.match(element('#video-message').textContent, /本機媒體無法載入/);
});

test('retiring the player invalidates callbacks before replacing a segment', async () => {
  const { context, video, element, reject } = reader();
  context.playSource(0,true);
  video.onloadedmetadata();
  const oldError = video.onerror;
  context.stopVideo();
  reject();
  oldError();
  await Promise.resolve();
  assert.equal(video.onerror, null);
  assert.equal(video.getAttribute('src'), null);
  assert.equal(element('#video-message').textContent, '');
});

test('audio keeps the slide visible and unloads video before making sound', () => {
  const {context, video, audio, element} = reader();
  context.playSource(0,true); video.onloadedmetadata();
  context.playSource(1); audio.onloadedmetadata();
  assert.equal(video.paused, true);
  assert.equal(video.getAttribute('src'), null);
  assert.equal(audio.currentTime, 42);
  assert.equal(audio.paused, false);
  assert.equal(element('#video-view').hidden, true);
  assert.equal(element('#slide-view').hidden, false);
  assert.equal(element('#media-area').hidden, false);
  assert.equal(element('#lesson-audio').hidden, false);
});

test('sentence pauses at its end plus 0.3 seconds and resume continues freely', () => {
  const {context, video, timers} = reader();
  context.playSource(0,true); video.onloadedmetadata();
  video.currentTime = 14.2; video.ontimeupdate();
  assert.equal(video.paused, false);
  assert.equal(timers.size, 1);
  video.currentTime = 14.4; video.ontimeupdate();
  assert.equal(video.paused, true);
  assert.equal(video.currentTime, 14.4);
  assert.equal(timers.size, 0);
  video.play();
  assert.equal(video.currentTime, 14.4);
  video.currentTime=18;video.ontimeupdate();assert.equal(video.paused,false);assert.equal(timers.size,0);
});

test('paragraph uses its own time range and clamps padding at media duration', () => {
  const {context, audio} = reader();
  audio.duration = 50.1;
  context.playSection(0); audio.onloadedmetadata();
  assert.equal(audio.currentTime, 10);
  audio.currentTime = 49; audio.ontimeupdate();
  assert.equal(audio.paused, false);
  audio.currentTime = 50.1; audio.ontimeupdate();
  assert.equal(audio.paused, true);
  assert.equal(audio.currentTime, 50.1);
});

test('boundary timer follows speed changes, clears on pause and ignores an old target', () => {
  const {context, video, timers} = reader();
  context.playSource(0,true); video.onloadedmetadata();
  video.currentTime = 13.3; video.playbackRate = 2; video.onratechange();
  assert.ok(Math.abs([...timers.values()][0].ms - 500) < .001);
  const oldTimer = [...timers.values()][0].callback;
  video.pause(); assert.equal(timers.size, 0);
  context.playSource(1,true); video.onloadedmetadata();
  oldTimer();
  assert.equal(video.currentTime, 42);
  assert.equal(video.paused, false);
  assert.equal(timers.size, 1, 'obsolete callbacks must not cancel the new target timer');
});

test('stopping audio clears timer and source; empty paragraphs do not start playback', () => {
  const {context, audio, timers, element} = reader();
  context.playSource(0); audio.onloadedmetadata();
  context.hideVideo();
  assert.equal(audio.paused, true);
  assert.equal(audio.getAttribute('src'), null);
  assert.equal(timers.size, 0);
  assert.equal(element('#inline-player').hidden, true);
  context.playSection(1);
  assert.equal(audio.getAttribute('src'), null);
});

test('text returns to notes while listening and video use separate buttons', () => {
  const {context, video, audio, emit} = reader();
  const click = (selector, dataset) => emit('click', {target: {id: '', closest: s => s === selector ? {dataset} : null}});
  click('[data-return]', {return: '0'});
  assert.equal(video.getAttribute('src'), null);
  assert.equal(audio.getAttribute('src'), null);
  click('[data-play]', {play: '0'});
  audio.onloadedmetadata();
  assert.equal(video.getAttribute('src'), null);
  assert.equal(audio.currentTime, 12);
  click('[data-play-section]', {playSection: '0'});
  audio.onloadedmetadata();
  assert.equal(audio.currentTime, 10);
  emit('keydown', {key: 'Escape', target: {matches() {return false;}}});
  assert.equal(audio.paused, true);
  assert.equal(audio.getAttribute('src'), null);
  context.playSource(0); audio.onloadedmetadata();
  emit('click', {target: {id: 'stop-playback', closest() {return null}}});
  assert.equal(audio.paused, true);
  assert.equal(audio.getAttribute('src'), null);
});

test('inline listening retains the mobile pane, both scroll offsets and paragraph selection', () => {
  const {context, element, audio} = reader();
  context.document.body.dataset.pane = 'transcript';
  context.state.paragraph = 3;
  let selections = 0;
  context.setParagraph = () => {selections++;};
  element('#notes-scroll').scrollTop = 420;
  element('#sources').scrollTop = 690;
  const slot = element('[data-audio-source="1"]');
  slot.append = player => {
    player.parentElement = slot;
    element('#notes-scroll').scrollTop = 0;
    element('#sources').scrollTop = 0;
  };
  context.playSource(1); audio.onloadedmetadata();
  assert.equal(context.document.body.dataset.pane, 'transcript');
  assert.equal(element('#notes-scroll').scrollTop, 420);
  assert.equal(element('#sources').scrollTop, 690);
  assert.equal(element('#inline-player').parentElement, slot);
  assert.equal(element('#video-view').hidden, true);
  assert.equal(context.state.paragraph, 3);
  context.playSection(0); audio.onloadedmetadata();
  assert.equal(selections, 0, 'listening must not invoke the auto-scroll selection path');
  assert.equal(context.state.paragraph, 3);
  assert.equal(element('#inline-player').parentElement, element('[data-audio-section="0"]'));
});
for(const mode of ['audio','video'])test(`${mode} can seek before or after a sentence, including while paused`,()=>{
 const {context,video,audio,timers,element}=reader();const v=mode==='audio'?audio:video;
 context.playSource(1,mode==='video');v.onloadedmetadata();
 // The initial metadata seek must keep the automatic sentence boundary.
 v.onseeking();v.onseeked();assert.equal(timers.size,1);
 v.pause();v.currentTime=5;v.onseeking();v.onseeked();
 assert.equal(v.currentTime,5);assert.equal(v.paused,true);assert.equal(timers.size,0);
 v.play();v.currentTime=80;v.onseeking();v.onseeked();v.ontimeupdate();
 assert.equal(v.currentTime,80);assert.equal(v.paused,false);assert.equal(timers.size,0);
 assert.match(element(mode==='audio'?'#playback-label':'#video-message').textContent,/自由播放/);
 // Clicking a sentence starts a new bounded selection.
 context.playSource(0,mode==='video');v.onloadedmetadata();v.currentTime=14.4;v.ontimeupdate();assert.equal(v.paused,true);
});
test('manual seek during initial positioning wins over the pending metadata target',()=>{
 const {context,video,timers}=reader();context.playSource(1,true);video.onloadedmetadata();
 video.currentTime=70;video.onseeking();video.onseeked();video.ontimeupdate();
 assert.equal(video.currentTime,70);assert.equal(video.paused,false);assert.equal(timers.size,0);
});
test('audio-only course keeps listening available and refuses video playback',()=>{
 const {context,audio,video}=reader();context.DATA.media_kind='audio';
 context.playSource(0,true);assert.equal(video.getAttribute('src'),null);
 context.playSource(0);audio.onloadedmetadata();assert.equal(audio.paused,false);
 context.playSource(1,true);assert.equal(audio.paused,false);assert.equal(video.getAttribute('src'),null);
});

test('standalone audio uses the published audio URL and preserves timed stopping',()=>{
 const {context,audio}=reader();context.DATA.audio_src='https://media.example.test/lecture.m4a';
 context.playSource(0);assert.equal(audio.src,context.DATA.audio_src);
 audio.onloadedmetadata();assert.equal(audio.currentTime,12);
 audio.currentTime=14.4;audio.ontimeupdate();assert.equal(audio.paused,true);
});

test('range-enabled published audio starts directly without a full download',()=>{
 const {context,audio}=reader();context.DATA.read_only=true;context.DATA.audio_src='audio.m4a';context.DATA.audio_stream_src='/api/audio?course=1008';
 context.fetch=()=>{throw Error('Must not download the whole file');};
 context.playSource(1);assert.equal(audio.src,context.DATA.audio_stream_src);
 audio.onloadedmetadata();assert.equal(audio.currentTime,42);assert.equal(audio.paused,false);
});

test('published audio caches a seekable blob and only the latest pending click starts',async()=>{
 const {context,audio}=reader();let downloads=0,finish;
 context.DATA.read_only=true;context.DATA.audio_src='audio.m4a';
 context.fetch=()=>{downloads++;return new Promise(resolve=>{finish=resolve;});};
 context.URL={createObjectURL:()=> 'blob:seekable-audio'};
 context.playSource(0);context.playSource(1);
 assert.equal(downloads,1);assert.equal(audio.getAttribute('src'),null);
 finish({ok:true,blob:async()=>({})});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(audio.src,'blob:seekable-audio');
 audio.onloadedmetadata();assert.equal(audio.currentTime,42);
 context.playSource(0);await new Promise(resolve=>setImmediate(resolve));
 audio.onloadedmetadata();assert.equal(audio.currentTime,12);assert.equal(downloads,1);
});

test('stopping while published audio downloads prevents delayed playback',async()=>{
 const {context,audio}=reader();let finish;
 context.DATA.read_only=true;context.DATA.audio_src='audio.m4a';
 context.fetch=()=>new Promise(resolve=>{finish=resolve;});
 context.URL={createObjectURL:()=> 'blob:seekable-audio'};
 context.playSource(1);context.stopVideo();
 finish({ok:true,blob:async()=>({})});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(audio.getAttribute('src'),null);assert.equal(audio.paused,true);
});
