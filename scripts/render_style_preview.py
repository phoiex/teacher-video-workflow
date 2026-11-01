"""从已保存的场景源码重新导出样片，不调用模型或配音服务。"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from teacher_flow.common import NODE, RENDER_RUNTIME


def main():
    presets = json.loads((ROOT / 'assets/style/catalog.json').read_text())['presets']
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('style', choices=[p['id'] for p in presets if p.get('preview_video')])
    args = parser.parse_args()
    source = ROOT / 'examples/style-previews' / args.style
    scene = json.loads((source / 'scene.json').read_text())
    output = ROOT / '.runtime/style-previews' / args.style
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / 'scene.html', output / 'scene.html')
    audio = output / 'silence.wav'
    with wave.open(str(audio), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(bytes(round(scene['duration_seconds'] * 24000 * 2)))
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('请先安装 FFmpeg，再重新导出。')
    spec = {
        'root': str(output), 'runtime': str(RENDER_RUNTIME),
        'html': str(output / 'scene.html'), 'scene': scene,
        'mode': 'video', 'output': str(output / f'{args.style}.mp4'),
        'audio': str(audio), 'ffmpeg': ffmpeg, 'cues': [],
        'progress': str(output / 'progress.json'),
    }
    task = output / 'render.json'
    task.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n')
    subprocess.run([str(NODE), str(ROOT / 'teacher_flow/render.mjs'), str(task)], check=True)
    print(spec['output'])


if __name__ == '__main__':
    main()
