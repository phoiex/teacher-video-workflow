import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from teacher_flow import common, engine, model_call, model_connections, model_roles, codex_runtime

ROOT = Path(__file__).resolve().parents[1]


class PublicConfigTests(unittest.TestCase):
    def test_new_course_freezes_default_roles(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'COURSES', Path(tmp)):
            cid = engine.new_course({'requirement': '解释距离'})['course_id']
            before = common.state(cid)['model_roles']
            changed = {r: {'provider': 'openai', 'model': 'fixture', 'protocol': 'responses'} for r in before}
            with patch.object(model_roles, 'default_roles', return_value=changed):
                engine.new_course({'resume_course': cid})
            self.assertEqual(common.state(cid)['model_roles'], before)

    def test_missing_key_does_not_read_personal_credential_files(self):
        with patch.dict(os.environ, {'CUSTOM_API_KEY': '', 'CUSTOM_BASE_URL': ''}):
            with self.assertRaisesRegex(ValueError, 'CUSTOM_API_KEY'):
                model_connections.connection({'provider': 'custom'})

    def test_native_responses_does_not_start_adapter(self):
        profile = {'provider': 'custom', 'model': 'fixture', 'protocol': 'responses'}
        with patch.dict(os.environ, {'CUSTOM_API_KEY': 'fixture-key', 'CUSTOM_BASE_URL': 'http://127.0.0.1:9999/v1'}), \
             patch('teacher_flow.model_adapter_setup.ensure', side_effect=AssertionError('unexpected adapter')):
            self.assertEqual(codex_runtime.provider_settings(profile=profile)['model'], 'fixture')

    def test_generated_dsl_keeps_public_template_empty(self):
        spec = importlib.util.spec_from_file_location('local_setup', ROOT/'scripts/local.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        import yaml
        with tempfile.TemporaryDirectory() as tmp, patch.object(module, 'RUNTIME', Path(tmp)/'teacher-flow'):
            target = module.initialize()
            local = yaml.safe_load(target.read_text())
            first = next(v['value'] for v in local['workflow']['environment_variables'] if v['name']=='LOCAL_TOOL_TOKEN')
            module.initialize()
            self.assertEqual(first, common.load(Path(tmp)/'teacher-flow/bridge.json')['token'])
            self.assertTrue(first)
        public = yaml.safe_load((ROOT/'workflow/teacher-video.yml').read_text())
        self.assertFalse(next(v['value'] for v in public['workflow']['environment_variables'] if v['name']=='LOCAL_TOOL_TOKEN'))

    def test_content_network_retry_and_completed_result_reuse(self):
        from types import SimpleNamespace as Obj
        reply = Obj(id='fixture', model='fixture', usage=None, status='completed', output_text='{"ok":true}')
        response = contextlib.nullcontext(iter([Obj(type='response.completed', response=reply)]))
        from unittest.mock import Mock
        create = Mock(side_effect=[ConnectionError('offline fixture'), response])
        client = Obj(responses=Obj(create=create))
        profile = {'provider': 'custom', 'model': 'fixture', 'protocol': 'responses'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(model_call, 'RUNTIME', Path(tmp)), \
             patch.dict(os.environ, {'CUSTOM_API_KEY': 'fixture-key', 'CUSTOM_BASE_URL': 'https://example.invalid/v1'}), \
             patch('openai.OpenAI', side_effect=lambda **_: contextlib.nullcontext(client)), \
             patch('teacher_flow.network_retry.wait'):
            self.assertEqual(model_call.generate('fixture', '规则', {}, profile=profile), {'ok': True})
            self.assertEqual(model_call.generate('fixture', '规则', {}, profile=profile), {'ok': True})
            self.assertEqual(create.call_count, 2)
            self.assertNotIn('max_output_tokens', create.call_args.kwargs)


if __name__ == '__main__': unittest.main()
