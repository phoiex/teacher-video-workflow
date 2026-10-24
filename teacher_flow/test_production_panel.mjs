import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const html = readFileSync(new URL('./production-panel.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1]
  .replace('__COURSE__', JSON.stringify('course')).replace('__CHANNEL__', JSON.stringify('test'));
const flush = () => new Promise(resolve => setImmediate(resolve));

async function panel(status) {
  const nodes = new Map(), timers = [], requests = [], messages = [], events = {};
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, {
      textContent: '', style: {}, dataset: {}, disabled: false, hidden: false, open: false, children: [],
      classList: { toggle() {} }, setAttribute() {},
      replaceChildren() { this.children = []; }, append(child) { this.children.push(child); },
      get firstChild() { return this.children[0]; },
      getBoundingClientRect() { return { height: 300 }; },
      showModal() { this.open = true; }, close() { this.open = false; },
    });
    return nodes.get(id);
  };
  const durationButtons = ['accept_duration', 'revise'].map(action => {
    const button = element(action); button.dataset.action = action; return button;
  });
  const parent = { postMessage(value) { messages.push(value); } };
  vm.runInNewContext(script, {
    document: {
      getElementById: element, body: element('body'), createElement: name => element(name + nodes.size),
      querySelector: element,
      querySelectorAll: selector => selector === '[data-phase]' ? [] : [...durationButtons, ...element('actions').children],
    },
    window: { addEventListener(name, fn) { events[name] = fn; } }, parent,
    ResizeObserver: class { observe() {} }, Image: class {},
    setTimeout(fn, delay) { timers.push({ fn, delay }); },
    fetch(url, options) { return new Promise(resolve => requests.push({ url, options, resolve })); },
  });
  const data = { status, title: status, message: '进度', progress: 100, actions: [], files: {}, actual_seconds: 280, target_seconds: 240 };
  const answer = async value => { requests.shift().resolve({ ok: true, json: async () => value }); await flush(); };
  await answer(data);
  const ack = ok => events.message({ origin: 'http://127.0.0.1:8788', source: parent, data: { type: 'production-ack', channel: 'test', ok, error: '连接中断' } });
  return { element, timers, requests, messages, data, answer, ack, actions: () => messages.filter(value => value.type === 'production-action') };
}

for (const status of ['complete', 'needs_script']) {
  test(`${status}结果交接失败后延迟重试，只读取结果，不重启制作`, async () => {
    const p = await panel(status);
    assert.deepEqual(p.actions().map(value => value.action), ['check']);
    p.ack(false);
    assert.equal(p.actions().length, 1);
    assert.equal(p.element('error').textContent, '连接中断');
    assert.equal(p.timers.length, 1);
    assert.equal(p.timers[0].delay, 2000);
    p.timers.shift().fn();
    assert.equal(p.requests[0].url, '/production-status/course');
    assert.equal(p.requests[0].options.method, undefined);
    await p.answer(p.data);
    assert.deepEqual(p.actions().map(value => value.action), ['check', 'check']);
    p.ack(true);
    assert.equal(p.timers.length, 0);
  });
}

test('超时长需要老师选择，关闭提示和普通轮询不会批准或重新弹窗', async () => {
  const p = await panel('duration_review');
  assert.equal(p.element('duration').open, true);
  assert.equal(p.actions().length, 0);
  p.element('close-dialog').onclick();
  p.timers.shift().fn();
  await p.answer({ ...p.data, actions: ['accept_duration', 'revise'] });
  assert.equal(p.element('duration').open, false);
  assert.equal(p.actions().length, 0);
  p.element('accept_duration').onclick();
  p.element('accept_duration').onclick();
  assert.deepEqual(p.actions().map(value => value.action), ['accept_duration']);
});
