// Logic regression with synthetic DOM geometry; this is not browser coverage.
const {test} = require('node:test');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');

test('hidden notes retain selection; visible reading highlights and honors follow', () => {
 const source = readFileSync(join(__dirname, '..', 'reader.js'), 'utf8');
 const functions = source.slice(source.indexOf('function setParagraph('), source.indexOf('function youtubeAt('));
 const harness = String.raw`
const assert = require('node:assert/strict');
const state = {segment: 0, paragraph: 1, follow: true, frame: 3};
const DATA = {segments: [{sections: [
 {time: 0, end: 10, source_ids: [0]},
 {time: 10, end: 20, source_ids: [1]},
 {time: 20, end: 30, source_ids: [2]}
]}]};
const sourceIds = p => p.source_ids;
const syncReadingSlide = () => {};
const stamp = t => String(t);
let hidden = true, scrollCalls = 0, scrollTop = 0;
const pane = {
 get clientHeight() {return hidden ? 0 : 400},
 getBoundingClientRect() {return hidden ? {top: 0, bottom: 0} : {top: 100, bottom: 500}}
};
const lessons = [0, 1, 2].map(i => ({
 dataset: {paragraph: String(i)},
 classList: {toggle() {}},
 getBoundingClientRect() {return hidden ? {top: 0, bottom: 0} : {top: i * 200 - 100, bottom: i * 200 + 100}}
}));
const utterances = [0, 1, 2].map(i => ({
 dataset: {source: String(i)}, linked: i === 1, pressed: 'false',
 classList: {toggle(name, value) {utterances[i].linked = value}},
 querySelector() {return {setAttribute(name, value) {utterances[i].pressed = value}}},
 getBoundingClientRect() {return {top: i * 100}}
}));
const sources = {
 get scrollTop() {return scrollTop},
 getBoundingClientRect() {return {top: 0}},
 scrollTo({top}) {scrollCalls++; scrollTop = top}
};
const status = {textContent: ''};
function $(selector) {
 return selector === '#notes-scroll' ? pane : selector === '#status' ? status :
 selector === '#sources' ? sources : selector === '.transcript-header' ? {offsetHeight: 50} :
 selector === '.utterance.is-linked' ? utterances.find(u => u.linked) : null;
}
const document = {querySelectorAll(selector) {return selector === '.lesson' ? lessons : utterances}};
`;
 const checks = String.raw`
// A mobile transcript tab hides notes. Resizing must not select its zero-size first lesson.
trackReading();
assert.equal(state.paragraph, 1, 'hidden notes must retain the selected paragraph');
assert.equal(scrollCalls, 0, 'hidden notes must not move the transcript');
assert.equal(state.frame, 0, 'the pending animation frame must still clear');
hidden = false;
trackReading();
assert.equal(state.paragraph, 1, 'the visible reading anchor should select the middle lesson');
state.paragraph = -1;
trackReading();
assert.equal(utterances[1].linked, true);
assert.equal(utterances[1].pressed, 'true');
assert.equal(utterances[0].linked, false);
assert.equal(scrollCalls, 1, 'following should scroll the transcript on selection');
state.follow = false;
setParagraph(2);
assert.equal(utterances[2].linked, true, 'turning follow off should retain highlighting');
assert.equal(scrollCalls, 1, 'turning follow off must preserve the transcript position');
assert.equal(status.textContent, '20–30 · 對應 1 句');
`;
 runInNewContext(harness + functions + checks, {require});
});
