import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const html = readFileSync(new URL('./storyboard-panel.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1].replace('__CONFIG__', JSON.stringify({ cid: 'course', channel: 'test' }));
const flush = () => new Promise(resolve => setImmediate(resolve));
const initial = { status: 'failed', message: '制作中断。', completed: 4, total: 10, key: 'job', retry_generation: 1, updated_at: 100 };

async function panel() {
  const nodes = new Map(); const requests = []; const timers = []; const messages = [];
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, { textContent: '', style: {}, dataset: {}, disabled: false, hidden: false });
    return nodes.get(id);
  };
  vm.runInNewContext(script, {
    document: { getElementById: element, body: { scrollHeight: 250 } },
    window: { addEventListener() {} },
    parent: { postMessage(value) { messages.push(value); } },
    setTimeout(fn) { timers.push(fn); },
    fetch(url, options) { return new Promise(resolve => requests.push({ url, options, resolve })); },
  });
  const answer = async (request, data) => { request.resolve({ ok: true, json: async () => data }); await flush(); };
  await answer(requests.shift(), initial);
  return { element, requests, timers, messages, answer };
}

test('点击立即显示正在恢复；旧轮询不能覆盖；重复点击不重复提交', async () => {
  const p = await panel(); const button = p.element('control');
  p.timers.shift()(); const oldPoll = p.requests.shift();
  const click = button.onclick();
  assert.equal(button.textContent, '正在恢复…');
  assert.equal(button.disabled, true);
  assert.equal(p.messages.at(-1).status, 'starting');
  await button.onclick();
  assert.equal(p.requests.length, 1);
  const post = p.requests.shift();
  assert.deepEqual(JSON.parse(post.options.body), { key: 'job', action: 'retry', retry_generation: 1 });
  await p.answer(post, { ...initial, status: 'queued', message: '正在继续制作。', retry_generation: 2, updated_at: 200 });
  await click;
  await p.answer(oldPoll, initial);
  assert.equal(button.textContent, '正在恢复…');
  assert.equal(button.disabled, true);
  assert.notEqual(p.element('message').textContent, initial.message);
  p.timers.shift()();
  await p.answer(p.requests.shift(), { ...initial, status: 'running', message: '制作分镜：第5/10段。', retry_generation: 2, updated_at: 201 });
  assert.equal(button.textContent, '暂停');
  assert.equal(button.disabled, false);
  assert.equal(p.messages.at(-1).status, 'running');
});

test('重试很快返回失败时，明确显示本次失败原因和再次重试', async () => {
  const p = await panel(); const button = p.element('control');
  const click = button.onclick();
  const failed = { ...initial, message: '本次重试未成功：制作服务暂时无法接受请求（429），请稍后再试。', retry_generation: 2, updated_at: 201 };
  await p.answer(p.requests.shift(), failed); await click;
  assert.equal(p.element('message').textContent, failed.message);
  assert.equal(button.textContent, '再次重试');
  assert.equal(button.disabled, false);
  assert.equal(p.messages.at(-1).status, 'failed');
});

test('网络等待保持进度、停止动画并保留暂停；有新输出后恢复制作', async () => {
  const p = await panel();
  p.timers.shift()();
  await p.answer(p.requests.shift(), { ...initial, status: 'network_wait', message: '等待网络恢复，正在重连。', updated_at: 200 });
  assert.equal(p.element('card').className, 'paused');
  assert.equal(p.element('message').textContent, '等待网络恢复，正在重连。');
  assert.equal(p.element('control').textContent, '暂停');
  assert.equal(p.element('control').dataset.action, 'pause');
  assert.equal(p.element('count').textContent, '已完成 4 / 10 段');
  assert.equal(p.messages.at(-1).status, 'network_wait');
  p.timers.shift()();
  await p.answer(p.requests.shift(), { ...initial, status: 'running', message: '制作分镜：第5/10段。', updated_at: 201 });
  assert.equal(p.element('card').className, '');
  assert.equal(p.element('message').textContent, '制作分镜：第5/10段。');
  assert.equal(p.messages.at(-1).status, 'running');
  assert.equal(p.requests.length, 0);
});

test('网络等待中暂停立即锁定按钮，收到实际停止状态后显示已暂停', async () => {
  const p=await panel();const button=p.element('control');
  p.timers.shift()();
  await p.answer(p.requests.shift(),{...initial,status:'network_wait',message:'等待网络恢复。',updated_at:200});
  const click=button.onclick();
  assert.equal(button.textContent,'正在暂停…');
  assert.equal(button.disabled,true);
  assert.equal(p.messages.at(-1).status,'pausing');
  await button.onclick();
  assert.equal(p.requests.length,1);
  await p.answer(p.requests.shift(),{...initial,status:'pausing',message:'正在暂停，保留当前制作进度。',updated_at:201});
  await click;
  assert.equal(button.textContent,'正在暂停…');
  assert.equal(button.disabled,true);
  p.timers.shift()();
  await p.answer(p.requests.shift(),{...initial,status:'paused',message:'已暂停，制作进度已保存。',updated_at:202});
  assert.equal(p.messages.at(-1).status,'paused');
  assert.equal(p.element('message').textContent,'已暂停，制作进度已保存。');
  assert.equal(button.hidden,true);
});

test('超时后显示已保存草稿，保持完成数和进度条准确', async () => {
  const p=await panel();
  p.timers.shift()();
  await p.answer(p.requests.shift(),{...initial,completed:0,total:16,scene_id:'s01',
    saved_scenes:['s01'],previewed_scenes:['s01'],updated_at:201,
    message:'本次重试未成功：模型请求超时（408），制作已停止。第1段草稿和预览已保存。'});
  assert.equal(p.element('count').textContent,'已完成 0 / 16 段 · 另有 1 段草稿已保存');
  assert.equal(p.element('fill').style.width,'0%');
  assert.match(p.element('message').textContent,/408/);
  assert.equal(p.element('control').textContent,'再次重试');
});
