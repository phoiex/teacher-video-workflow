"""生成 GitHub 与软件内共用的样片试看页。"""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CSS = '''
:root{color-scheme:light dark;--paper:#f6f6f3;--card:#fff;--text:#20252a;--muted:#6d7479;--line:#e5e7e6;--accent:#405bd2}
@media(prefers-color-scheme:dark){:root{--paper:#141719;--card:#1d2124;--text:#edf0ed;--muted:#acb4b8;--line:#333a3d;--accent:#a7b7ff}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6}main{max-width:1280px;padding:44px 24px 60px;margin:auto}header{margin-bottom:30px}h1{font-size:clamp(27px,4vw,42px);line-height:1.3;margin:0 0 12px;font-weight:650}header p{margin:0;color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}article{min-width:0;border:1px solid var(--line);border-radius:18px;background:var(--card);overflow:hidden}h2{margin:0;font-size:20px;font-weight:600}.caption{padding:18px 20px}.caption p{font-size:13px;color:var(--muted);margin:3px 0 0}video{display:block;width:100%;aspect-ratio:16/9;background:#121416}.meta{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:13px;padding:12px 20px;color:var(--muted)}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}a:focus-visible,video:focus-visible{outline:3px solid var(--accent);outline-offset:3px}footer{margin-top:28px;color:var(--muted);font-size:13px}@media(max-width:680px){main{padding:28px 14px 36px}.grid{grid-template-columns:1fr;gap:18px}.caption{padding:15px 16px}.meta{padding:12px 16px}}
'''


def page(presets, prefix):
    cards = []
    for index, p in enumerate(presets, 1):
        name = html.escape(p['name'])
        video = prefix + p['preview_video']
        poster = prefix + p['preview_poster']
        captions = prefix + p['preview_captions']
        cards.append(f'''<article><div class="caption"><h2>{index:02d} · {name}</h2><p>{html.escape(p['description'])}</p></div><video aria-label="{name}" controls playsinline preload="none" poster="{poster}"><source src="{video}" type="video/mp4"><track kind="captions" src="{captions}" srclang="zh-CN"></video><div class="meta"><span>8 秒 · 1080p · 静音</span><a href="{video}" download>下载视频</a></div></article>''')
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>画面风格参考 · 教师微课工作流</title><style>''' + CSS + '''</style></head><body><main><header><h1>画面风格参考</h1><p>十种 8 秒样片，使用同一个例子比较画面效果。</p></header><div class="grid">''' + '\n'.join(cards) + '''</div><footer>样片由 DeepSeek Flash 生成。<a href="https://github.com/phoiex/teacher-video-workflow">项目与使用说明</a></footer></main><script>document.querySelectorAll('video').forEach(v=>v.addEventListener('play',()=>document.querySelectorAll('video').forEach(other=>{if(other!==v)other.pause()})));</script></body></html>'''


def main():
    presets = [p for p in json.loads((ROOT / 'assets/style/catalog.json').read_text())['presets'] if p.get('preview_video')]
    for p in presets:
        for key in ('preview_video', 'preview_poster', 'preview_captions'):
            if not (ROOT / 'assets/style' / p[key]).is_file():
                raise FileNotFoundError(p[key])
    (ROOT / 'index.html').write_text(page(presets, 'assets/style/'))
    live = page(presets, '')
    (ROOT / 'assets/style/index.html').write_text(live)
    (ROOT / 'dify-overlay/web/public/teacher-style/index.html').write_text(live)
    print(f'已生成 {len(presets)} 种风格的试看页。')


if __name__ == '__main__':
    main()
