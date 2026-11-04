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


def page(presets, prefix, language='zh'):
    en = language == 'en'
    title = 'Video style previews' if en else '画面风格参考'
    intro = 'Ten eight-second animations, with the same example in each style.' if en else '十种风格都有中英文样片，每段 8 秒，使用同一个例子比较画面效果。'
    meta = '8 seconds · 1080p · Silent' if en else '8 秒 · 1080p · 静音'
    download = 'Download video' if en else '下载视频'
    credit = 'Original animations generated with DeepSeek Flash. English text and layouts adapted from the Chinese versions.' if en else '原动画由 DeepSeek Flash 生成，英文版沿用动画并调整文字与排版。'
    project = 'Project and instructions' if en else '项目与使用说明'
    cards = []
    for index, p in enumerate(presets, 1):
        name = html.escape(p['name_en'] if en else p['name'])
        description = html.escape(p['description_en'] if en else p['description'])
        variant = p['preview_languages']['en'] if en else {
            'video': p['preview_video'], 'poster': p['preview_poster'], 'captions': p['preview_captions']}
        video, poster, captions = (prefix + variant[key] for key in ('video', 'poster', 'captions'))
        cards.append(f'''<article><div class="caption"><h2>{index:02d} · {name}</h2><p>{description}</p></div><video aria-label="{name}" controls playsinline preload="none" poster="{poster}"><source src="{video}" type="video/mp4"><track kind="captions" src="{captions}" srclang="{'en' if en else 'zh-CN'}"></video><div class="meta"><span>{meta}</span><a href="{video}" download>{download}</a></div></article>''')
    navigation = f'''<nav aria-label="{'Preview language' if en else '样片语言'}"><a href="index.html" lang="zh-CN" {'aria-current="page"' if not en else ''}>中文</a><a href="en.html" lang="en" {'aria-current="page"' if en else ''}>English</a></nav>'''
    styles = CSS + 'nav{display:flex;gap:8px;margin-top:20px}nav a{padding:6px 16px;border:1px solid var(--line);border-radius:20px}nav a[aria-current]{font-weight:650;border-color:var(--accent)}'
    return f'''<!doctype html><html lang="{'en' if en else 'zh-CN'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · Teacher Video Workflow</title><style>{styles}</style></head><body><main><header><h1>{title}</h1><p>{intro}</p>{navigation}</header><div class="grid">''' + '\n'.join(cards) + f'''</div><footer>{credit} <a href="https://github.com/phoiex/teacher-video-workflow">{project}</a></footer></main><script>document.querySelectorAll('video').forEach(v=>v.addEventListener('play',()=>document.querySelectorAll('video').forEach(other=>{{if(other!==v)other.pause()}})));</script></body></html>'''


def main():
    presets = [p for p in json.loads((ROOT / 'assets/style/catalog.json').read_text())['presets'] if p.get('preview_video')]
    for p in presets:
        for key in ('preview_video', 'preview_poster', 'preview_captions'):
            if not (ROOT / 'assets/style' / p[key]).is_file():
                raise FileNotFoundError(p[key])
        for asset in p['preview_languages']['en'].values():
            if not (ROOT / 'assets/style' / asset).is_file():
                raise FileNotFoundError(asset)
    for language, filename in (('zh', 'index.html'), ('en', 'en.html')):
        (ROOT / filename).write_text(page(presets, 'assets/style/', language))
        live = page(presets, '', language)
        (ROOT / 'assets/style' / filename).write_text(live)
        (ROOT / 'dify-overlay/web/public/teacher-style' / filename).write_text(live)
    print(f'已生成 {len(presets)} 种风格的中英文试看页。')


if __name__ == '__main__':
    main()
