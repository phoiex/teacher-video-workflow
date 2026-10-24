"""用固定页面和测试音轨检查渲染，不调用模型或 TTS。"""
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from teacher_flow import common, engine


def main():
    output = common.RUNTIME.parent / 'checks'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as tmp, patch.object(common, 'COURSES', Path(tmp)):
        cid = 'f' * 24
        folder = common.course_dir(cid); folder.mkdir()
        html = folder/'scene.html'
        html.write_text('''<!doctype html><meta charset="utf-8"><style>
body{background:#0b1020;color:#88ffcc;font:48px monospace}h1{margin:180px 120px}
#bar{height:18px;margin:0 120px;background:#88ffcc}</style>
<h1 id="title"></h1><div id="bar"></div><script>
window.film={frame(t){document.querySelector('#title').textContent=SCENE.caption;
document.querySelector('#bar').style.width=(100+800*t/SCENE.duration_seconds)+'px'}};
</script>''')
        audio = folder/'tone.wav'
        with wave.open(str(audio), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(b''.join(struct.pack('<h', int(1200*math.sin(2*math.pi*440*i/24000))) for i in range(24000)))
        scene = {'id':'s01', 'caption':'渲染检查 · 1 秒', 'narration':'测试字幕。', 'duration_seconds':1.0}
        engine.render(cid, scene, html, folder/'preview.png', mode='preview', time=.5)
        engine.render(cid, scene, html, folder/'lesson.mp4', mode='video', audio=str(audio),
                      ffmpeg=shutil.which('ffmpeg'), progress=str(folder/'progress.json'),
                      cues=[{'start':0, 'end':1, 'text':'测试字幕。'}])
        result = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(folder/'lesson.mp4')]))
        video = next(s for s in result['streams'] if s['codec_type']=='video')
        sound = next(s for s in result['streams'] if s['codec_type']=='audio')
        assert (video['width'], video['height'], video['avg_frame_rate']) == (1920,1080,'30/1')
        assert video['codec_name']=='h264' and sound['codec_name']=='aac'
        subprocess.run(['ffmpeg','-v','error','-i',str(folder/'lesson.mp4'),'-f','null','-'],check=True,capture_output=True)
        shutil.copyfile(folder/'preview.png', output/'preview.png')
        shutil.copyfile(folder/'lesson.mp4', output/'render-check.mp4')
        report={'passed':True,'video':'h264','audio':'aac','width':1920,'height':1080,
                'fps':30,'seconds':float(result['format']['duration']),'model_calls':0,'tts_calls':0}
        (output/'render.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report))


if __name__=='__main__': main()
