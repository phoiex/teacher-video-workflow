import contextlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import Mock, patch

import yaml
from teacher_flow import common, engine, model_call, model_connections, model_roles, prompts, tts_config

ROOT = Path(__file__).resolve().parents[1]


class ReleaseProfilesTests(unittest.TestCase):
    def profile(self, name):
        return model_roles.validate(common.load(ROOT / 'presets' / (name + '.json')))

    def test_workflows_share_every_node_and_have_distinct_roles(self):
        variants = [yaml.safe_load((ROOT / 'workflow' / f'teacher-video-{n}.yml').read_text())['workflow']
                    for n in ('economy', 'quality')]
        self.assertEqual(variants[0]['graph'], variants[1]['graph'])
        self.assertEqual(len(variants[0]['graph']['nodes']), 76)
        for name, workflow in zip(('economy', 'quality'), variants):
            env = {e['name']: e['value'] for e in workflow['environment_variables']}
            self.assertEqual(json.loads(env['COURSE_MODELS']), self.profile(name))
            self.assertEqual(env['LOCAL_TOOL_TOKEN'], '')

    def test_economy_separates_qwen_content_from_deepseek_harness(self):
        roles = self.profile('economy')
        with patch.object(model_roles, 'default_roles', return_value=roles):
            for stage in ('teacher-script-draft-v2', 'teacher-script-deslop-v1'):
                self.assertEqual(model_roles.for_stage(stage)['provider'], 'qwen')
            self.assertEqual(model_roles.for_stage('teacher-script-plan-v1')['harness'], 'deepseek')
            self.assertEqual(model_roles.for_stage('teacher-storyboard-v1')['harness'], 'deepseek')

    def test_dsh_dispatch_preserves_images_and_profile(self):
        profile = self.profile('economy')['planner']
        with patch('teacher_flow.dsh_call.generate', return_value={'ok': True}) as generate:
            self.assertEqual(model_call.generate('plan', 'instruction', {'topic': 'x'}, [{'path': 'fixture.png'}], profile=profile), {'ok': True})
            self.assertEqual(generate.call_args.kwargs['profile'], profile)
            self.assertEqual(generate.call_args.args[3], [{'path': 'fixture.png'}])

    def test_qwen_thinking_wire_and_cache(self):
        for role in ('writer', 'editor'):
            with self.subTest(role=role):
                profile = self.profile('economy')[role]
                event = Obj(id='fixture', model=profile['model'], usage=None,
                            choices=[Obj(delta=Obj(content='{"script":"测试稿"}'), finish_reason='stop')])
                create = Mock(side_effect=lambda **_: contextlib.nullcontext(iter([event])))
                client = Obj(chat=Obj(completions=Obj(create=create)))
                with tempfile.TemporaryDirectory() as tmp, patch.object(model_call, 'RUNTIME', Path(tmp)), \
                     patch.dict(os.environ, {'QWEN_API_KEY': 'fixture-only'}), \
                     patch('openai.OpenAI', side_effect=lambda **_: contextlib.nullcontext(client)):
                    for _ in range(2):
                        self.assertEqual(model_call.generate(role, '写稿', {}, profile=profile), {'script': '测试稿'})
                    self.assertEqual(create.call_count, 1)
                    self.assertEqual(create.call_args.kwargs['extra_body'], {'enable_thinking': True})
                    self.assertEqual(create.call_args.kwargs['reasoning_effort'], 'xhigh')
                    self.assertNotIn('max_tokens', create.call_args.kwargs)

    def test_qwen_key_can_share_dashscope_and_gemini_has_own_endpoint(self):
        with patch.dict(os.environ, {'QWEN_API_KEY': '', 'DASHSCOPE_API_KEY': 'fixture-only',
                                    'GEMINI_API_KEY': 'gemini-fixture'}):
            self.assertEqual(model_connections.connection({'provider': 'qwen'})['api_key'], 'fixture-only')
            self.assertIn('generativelanguage.googleapis.com', model_connections.connection({'provider': 'gemini'})['base_url'])

    def test_thinking_parameter_is_provider_scoped(self):
        roles = self.profile('quality')
        roles['writer']['enable_thinking'] = True
        with self.assertRaisesRegex(ValueError, 'Qwen'):
            model_roles.validate(roles)

    def test_writer_then_full_skill_editor(self):
        skill = common.DESLOP.read_text()
        self.assertNotIn(skill, prompts.assemble('script'))
        self.assertIn(skill, prompts.assemble('script_deslop'))

    def test_course_freezes_voice_and_old_clip_identity(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'COURSES', Path(tmp)), \
             patch.object(tts_config, 'VOICE', 'longanlufeng'):
            cid = engine.new_course({'requirement': '讲清注意力', 'model_roles': self.profile('economy')})['course_id']
            frozen = common.state(cid)
        self.assertEqual(tts_config.for_course(frozen)['voice'], 'longanlufeng')
        self.assertEqual(tts_config.for_course({}), tts_config.LEGACY)
        old = 'tts_' + common.digest({'text': '原文', 'instruction': '普通话', 'voice': 'longanlingxin'})[:24]
        self.assertEqual(tts_config.clip_name('原文', '普通话', tts_config.LEGACY), old)
        self.assertNotEqual(tts_config.clip_name('原文', '普通话', tts_config.for_course(frozen)), old)


if __name__ == '__main__':
    unittest.main()
