import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

from . import common, engine, languages, production, subtitles, tts_client, tts_config
from .test_tts_retry import audio, response


class LanguageFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, name, value in ((common, 'COURSES', Path(self.tmp.name)/'courses'),
                                    (engine, 'public_url', lambda: 'http://127.0.0.1:8794')):
            item = patch.object(target, name, value)
            item.start(); self.addCleanup(item.stop)
        self.intake = {'topic': 'Attention', 'audience': '高中生', 'duration_minutes': '4',
                       'objectives': '理解加权汇总', 'prerequisites': '四则运算',
                       'style': '', 'questions': [], 'course_language': 'zh'}
        model = patch.object(engine.model_call, 'generate', return_value=self.intake)
        self.model = model.start(); self.addCleanup(model.stop)

    def create(self, language=''):
        return engine.new_course({'requirement': '讲解 Attention', 'course_language': language})['course_id']

    def approve(self, cid, language=None):
        shown = engine.show(cid, 'requirements')
        payload = {**shown, 'action': 'approve', 'production_mode': '先看分镜'}
        if language:
            payload['course_language'] = language
        engine.apply(cid, 'requirements', payload)
        return shown

    def test_selected_english_overrides_intake_and_prefills_review(self):
        cid = self.create('English')
        shown = self.approve(cid)
        self.assertEqual(shown['course_language'], 'English')
        saved = common.state(cid)
        self.assertEqual(saved['requirements']['course_language'], 'en')
        self.assertEqual(saved['tts_settings']['language'], 'en')
        self.assertEqual(engine.show(cid, 'requirements')['course_language'], 'English')

    def test_language_can_be_extracted_from_natural_request(self):
        self.intake['course_language'] = 'en'
        cid = self.create()
        self.approve(cid)
        self.assertEqual(languages.for_course(common.state(cid)), 'en')

    def test_review_language_change_replaces_default_voice_instruction(self):
        cid = self.create('中文（普通话）')
        self.approve(cid, 'English')
        saved = common.state(cid)
        self.assertEqual(saved['requirements']['voice_instruction'], languages.VOICE_INSTRUCTIONS['en'])
        self.assertEqual(tts_config.for_course(saved)['language'], 'en')

    def test_english_writer_and_editor_are_separate_and_keep_language(self):
        cid = self.create('English')
        self.approve(cid)
        self.model.reset_mock()
        raw = {'title': 'Attention', 'script': 'Attention combines information using weights.'}
        edited = {'script': 'Attention uses weights to combine information.'}
        self.model.side_effect = [raw, edited]
        engine.prepare_script(cid, 'draft')
        engine.prepare_script(cid, 'deslop')
        first, second = self.model.call_args_list
        self.assertIn('本课使用英文', first.args[1])
        self.assertIn('本课使用英文', second.args[1])
        self.assertNotIn(common.DESLOP.read_text(), first.args[1])
        self.assertIn(common.DESLOP.read_text(), second.args[1])
        self.assertEqual(second.args[2]['draft'], raw)
        self.assertEqual(common.state(cid)['draft']['script'], edited['script'])

    def test_legacy_chinese_audio_identity_is_unchanged(self):
        text, instruction = '测试。', common.DEFAULT_VOICE_INSTRUCTION
        legacy = 'tts_' + common.digest({'text': text, 'instruction': instruction, 'voice': 'longanlingxin'})[:24]
        self.assertEqual(tts_config.clip_name(text, instruction, tts_config.for_course({})), legacy)
        self.assertNotEqual(tts_config.clip_name(text, instruction,
                            tts_config.with_language(tts_config.LEGACY, 'en')), legacy)
        self.assertEqual(languages.for_course({}), 'zh')

    def test_english_chunks_preserve_words_and_caption_lines(self):
        text = 'Dr. Smith uses a value of 3.14. ' + 'Attention combines relevant information from the sentence. ' * 15
        parts = production.sentence_chunks(text, 'en')
        self.assertEqual(' '.join(parts).split(), text.split())
        self.assertTrue(parts[0].startswith('Dr. Smith'))
        for part in parts:
            lines = subtitles.caption(part, 'en').splitlines()
            self.assertLessEqual(len(lines), 2)
            self.assertTrue(all(len(line) <= 60 for line in lines))
        self.assertEqual(production.sentence_chunks('原文。保持！'), ['原文。', '保持！'])

    def test_english_production_exports_same_text_with_audio_timing(self):
        cid = self.create('English')
        self.approve(cid)
        text = 'Attention gives each word a weight, then combines their information.'
        scene = {'id': 's01', 'narration': text, 'caption': 'Attention', 'animation': 'A bar grows.',
                 'html': '<script>window.film={frame(t){document.title=SCENE.caption}}</script>'}
        board = {'scenes': [scene]}
        saved = common.state(cid)
        saved.update(approved_script=text, board=board, production={'input_version': 'fixture'})
        saved['approvals'].update(script=common.version(text), storyboard=common.version(board))
        common.store(cid, saved)
        folder = common.course_dir(cid)
        boards = folder/'boards'/common.version(board); boards.mkdir(parents=True)
        (boards/'s01.html').write_text(scene['html'])

        def synthesize(text, name, target, instruction, **kwargs):
            self.assertEqual(kwargs['settings']['language'], 'en')
            (Path(target)/(name+'.wav')).write_bytes(audio())

        def render(cid, scene, html, output, **kwargs):
            self.assertEqual(scene['language'], 'en')
            Path(output).write_bytes(b'fixture-video')

        def command(args, **kwargs):
            if args[-1].endswith('.mp4'):
                Path(args[-1]).write_bytes(b'fixture-video')

        with patch.object(production, 'checkpoint'), patch.object(production.tts_client, 'synthesize', synthesize), \
             patch.object(production, 'render', render), patch.object(production.subprocess, 'run', command):
            production.run(cid)
        result = common.state(cid)['production']
        self.assertEqual(result['status'], 'complete', result.get('message'))
        srt = (folder/'deliverables'/'fixture'/'lesson.srt').read_text()
        self.assertIn('00:00:00,000 --> 00:00:00,100', srt)
        self.assertIn(subtitles.caption(text, 'en'), srt)
        self.assertEqual((folder/'deliverables'/'fixture'/'讲稿.txt').read_text(), text)

    def test_every_workflow_carries_language_to_review_and_submission(self):
        for path in (common.TOOL/'workflow').glob('teacher-video*.yml'):
            with self.subTest(workflow=path.name):
                nodes = {n['id']: n['data'] for n in yaml.safe_load(path.read_text())['workflow']['graph']['nodes']}
                self.assertIn('English', next(v['options'] for v in nodes['start']['variables'] if v['variable']=='course_language'))
                review = next(v for v in nodes['requirements_review']['inputs'] if v['output_variable_name']=='course_language')
                self.assertEqual(review['default']['selector'], ['requirements_data', 'course_language'])
                for name in ('create_args', 'requirements_apply_args'):
                    namespace = {}
                    exec(nodes[name]['code'], namespace)
                    arguments = {v['variable']: '' for v in nodes[name]['variables']}
                    arguments['course_language'] = 'English'
                    payload = json.loads(namespace['main'](**arguments)['payload'])
                    self.assertEqual(payload['course_language'], 'English')


class EnglishTTSTests(unittest.TestCase):
    def test_english_request_receipt_and_cached_audio(self):
        settings = tts_config.with_language(tts_config.LEGACY, 'en')
        provider = SimpleNamespace(MODEL=settings['model'], read_credential=lambda _: 'fixture')
        with tempfile.TemporaryDirectory() as tmp, patch.object(tts_client, 'provider', return_value=provider), \
             patch.object(tts_client.urllib.request, 'urlopen', side_effect=[response(), io.BytesIO(audio())]) as send:
            path = tts_client.synthesize('A weighted sum.', 'sample', tmp, 'Clear English.', settings=settings)
            payload = json.loads(send.call_args_list[0].args[0].data)
            self.assertEqual(payload['input']['language_hints'], ['en'])
            self.assertEqual(json.loads(path.with_suffix('.json').read_text())['language'], 'en')
            self.assertEqual(tts_client.synthesize('A weighted sum.', 'sample', tmp, 'Clear English.', settings=settings), path)
            self.assertEqual(send.call_count, 2)
            with self.assertRaisesRegex(ValueError, '声音设置不一致'):
                tts_client.synthesize('A weighted sum.', 'sample', tmp, 'Clear English.', settings=tts_config.LEGACY)


if __name__ == '__main__':
    unittest.main()
