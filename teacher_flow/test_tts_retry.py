import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from . import tts_client, network_retry


def audio():
    data=io.BytesIO()
    with wave.open(data,'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(b'\0\0'*2400)
    return data.getvalue()


def response():
    return io.BytesIO(json.dumps({'request_id':'fixture','output':{'audio':{'url':'https://audio.invalid/a.wav'}}}).encode())


class TTSRetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.provider=patch.object(tts_client,'provider',return_value=SimpleNamespace(MODEL='fixture',read_credential=lambda _: 'fixture'))
        self.provider.start();self.addCleanup(self.provider.stop)
        self.wait=patch.object(network_retry,'wait');self.wait.start();self.addCleanup(self.wait.stop)

    def test_network_retries_then_finished_audio_is_reused(self):
        with patch.object(tts_client.urllib.request,'urlopen',side_effect=[ConnectionError(),response(),TimeoutError(),io.BytesIO(audio())]) as send:
            first=tts_client.synthesize('测试配音。','test',self.folder,'自然')
            self.assertTrue(first.is_file())
            self.assertEqual(tts_client.synthesize('测试配音。','test',self.folder,'自然'),first)
            self.assertEqual(send.call_count,4)
            methods=[x.args[0].get_method() if hasattr(x.args[0],'get_method') else 'GET' for x in send.call_args_list]
            self.assertEqual(methods,['POST','POST','GET','GET'])

    def test_download_failure_resumes_without_another_synthesis(self):
        with patch.object(tts_client.urllib.request,'urlopen',side_effect=[response(),TimeoutError(),TimeoutError(),TimeoutError()]):
            with self.assertRaises(network_retry.NetworkFailure):tts_client.synthesize('测试配音。','test',self.folder,'自然')
        with patch.object(tts_client.urllib.request,'urlopen',return_value=io.BytesIO(audio())) as send:
            tts_client.synthesize('测试配音。','test',self.folder,'自然')
            self.assertEqual(send.call_count,1)
            self.assertIsInstance(send.call_args.args[0],str)
        self.assertFalse((self.folder/'download-recovery/test.json').exists())
