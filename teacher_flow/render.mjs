// 固定浏览器渲染入口；模型只提供场景HTML，没有终端或主机文件权限。
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL, fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {once} from 'node:events';

const task = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const root = fs.realpathSync(task.root);
const inside = p => p === root || p.startsWith(root + path.sep);
const html = fs.realpathSync(task.html);
if (!inside(html)) throw new Error('场景不在本课目录');
const output = path.join(fs.realpathSync(path.dirname(task.output)),path.basename(task.output));
if (!inside(output)) throw new Error('输出不在本课目录');
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(task.runtime, 'browsers');
const {chromium} = await import(pathToFileURL(path.join(task.runtime, 'node_modules/playwright-core/index.mjs')));
const browser = await chromium.launch({headless:true,chromiumSandbox:true});
try {
  const context = await browser.newContext({
    viewport:{width:1920,height:1080}, deviceScaleFactor:1,
    serviceWorkers:'block', acceptDownloads:false,
  });
  await context.route('**/*', async route => {
    const url = route.request().url();
    if (url.startsWith('file:')) {
      let local;
      try { local = fs.realpathSync(fileURLToPath(url)); } catch { return route.abort(); }
      return inside(local) ? route.continue() : route.abort();
    }
    return route.abort();
  });
  await context.addInitScript(scene => {window.SCENE=Object.freeze(scene);}, task.scene);
  const page = await context.newPage();
  const errors=[];
  page.on('pageerror', e=>errors.push(String(e.message).slice(0,500)));
  await page.goto(pathToFileURL(html).href,{waitUntil:'load',timeout:30000});
  await page.evaluate(async()=>{await document.fonts.ready;});
  await page.evaluate(()=>{
    if (typeof window.film?.frame !== 'function') throw new Error('缺少window.film.frame(t)');
    document.documentElement.style.cssText+=';width:1920px;height:1080px;overflow:hidden;';
    document.body.style.cssText+=';width:1920px;height:1080px;margin:0;overflow:hidden;';
    const caption=document.createElement('div');
    caption.id='teacher-flow-subtitle';
    caption.style.cssText='position:fixed;left:100px;right:100px;bottom:36px;z-index:2147483647;text-align:center;font:42px/1.35 sans-serif;color:#fff;white-space:pre-wrap;pointer-events:none;text-shadow:0 2px 4px #000;';
    document.body.appendChild(caption);
  });
  const draw=async(t,caption='')=>{
    await page.evaluate(({t,caption})=>{
      window.film.frame(t);
      const el=document.getElementById('teacher-flow-subtitle');
      el.textContent=caption;
      el.style.background=caption?'rgba(0,0,0,.68)':'transparent';
      el.style.padding=caption?'14px 24px':'0';
      el.style.borderRadius='12px';
    },{t,caption});
    if(errors.length)throw new Error(errors.join('\n'));
  };
  if(task.mode==='preview'){
    await draw(task.time || 0);
    await page.screenshot({path:output,type:'png'});
  }else if(task.mode==='video'){
    const fps=30, count=Math.ceil(task.scene.duration_seconds*fps);
    const args=['-hide_banner','-loglevel','error','-y','-f','image2pipe','-vcodec','png',
      '-framerate',String(fps),'-i','pipe:0','-i',task.audio,'-c:v','libx264',
      '-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k',
      '-af','apad','-t',String(count/fps),'-movflags','+faststart',output];
    const ff=spawn(task.ffmpeg,args,{stdio:['pipe','ignore','pipe']});
    const completed=once(ff,'close'); let stderr='';
    ff.stderr.on('data',v=>{stderr=(stderr+v.toString()).slice(-4000);});
    ff.stdin.on('error',()=>{});
    for(let i=0;i<count;i++){
      const t=i/fps;
      const cue=(task.cues||[]).find(c=>c.start<=t && t<c.end);
      await draw(t,cue?.text||'');
      const frame=await page.screenshot({type:'png'});
      if(!ff.stdin.write(frame))await once(ff.stdin,'drain');
      if(i % 60 === 0)fs.writeFileSync(task.progress,JSON.stringify({frames:i,total:count}));
    }
    ff.stdin.end();
    const [code]=await completed;
    if(code!==0)throw new Error('视频编码失败：'+stderr);
  }else throw new Error('渲染模式不正确');
  console.log(JSON.stringify({ok:true,output}));
}finally{
  await browser.close();
}
