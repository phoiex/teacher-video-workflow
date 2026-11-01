"""风格选项、实际图片、参考代码和在制任务的版本接续。"""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from . import common, codex_jobs, prompts, styles
from .codex_storyboard import BoardTools


SELECTED = ['黑板粉笔', '手绘白板', '立体微缩工坊', '纸张拼贴',
            '水彩角色动画', '数据叙事', '极简动态排版']


class InstalledStylesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def packet(self, name):
        return {'requirements': {'style_preset': name, 'style': ''},
                'approved_script': '这是固定讲稿。', 'style_preview_version': 1}

    def test_selected_styles_reach_model_with_real_matching_images_and_sources(self):
        self.assertNotIn('等距信息图', styles.PRESETS)
        self.assertEqual(len([x for x in styles.DETAILS.values() if x.get('image')]), 10)
        for name in SELECTED:
            with self.subTest(style=name):
                packet = codex_jobs.inputs_for(self.packet(name))
                self.assertIn('# ' + name, packet['style_instructions'])
                self.assertIn('# ' + name, prompts.assemble('storyboard', '', name))
                reference = packet['style_reference_images'][0]
                with Image.open(reference['path']) as image:
                    self.assertEqual(image.format, 'PNG')
                    self.assertGreater(image.width, 300)
                tools = BoardTools(self.root / styles.DETAILS[name]['id'], packet)
                read = tools.call('course_read', {})
                images = [x for x in read['contentItems'] if x['type'] == 'inputImage']
                self.assertEqual(len(images), 1)
                source = next(x for x in packet['style_reference_sources'] if x['kind'] == 'code')
                result = tools.call('course_style_source', {'source_id': source['id']})
                text = '\n'.join(x.get('text', '') for x in result['contentItems'])
                self.assertIn(source['name'], text)
                self.assertIn(source['source_url'], text)

    def test_source_read_is_limited_to_selected_verified_material(self):
        packet = codex_jobs.inputs_for(self.packet('纸张拼贴'))
        source = packet['style_reference_sources'][0]
        source['path'] = str(self.root / 'changed.md')
        Path(source['path']).write_text('changed')
        tools = BoardTools(self.root / 'work', packet)
        with self.assertRaisesRegex(ValueError, '已变化'):
            tools.call('course_style_source', {'source_id': source['id']})
        with self.assertRaisesRegex(ValueError, '未找到'):
            tools.call('course_style_source', {'source_id': '../../another-course'})

    def test_style_install_keeps_started_job_inputs_but_teacher_change_creates_new_inputs(self):
        cid = 'a' * 24
        state = self.packet('ASCII 终端科技')
        saved = codex_jobs.inputs_for(state)
        key = common.version(saved)
        with patch.object(common, 'COURSES', self.root / 'courses'):
            folder = codex_jobs.job_dir(cid, key)
            common.save(folder / 'input.json', saved)
            common.save(common.course_dir(cid) / 'harness/current.json', {'key': key})
            changed_resources = {**saved, 'style_instructions': 'new installed library'}
            with patch.object(codex_jobs, 'inputs_for', return_value=changed_resources) as build:
                resumed = codex_jobs.saved_inputs_for(cid, state)
                self.assertEqual(resumed, saved)
                self.assertEqual(common.version(resumed), key)
                build.assert_not_called()
                revised = copy.deepcopy(state)
                revised['board_feedback'] = '调整第二段的图形。'
                self.assertEqual(codex_jobs.saved_inputs_for(cid, revised), changed_resources)
                build.assert_called_once_with(revised)

    def test_review_and_new_course_share_options(self):
        import yaml
        workflow = yaml.safe_load((common.TOOL / 'workflow/teacher-video.yml').read_text())
        nodes = {node['id']: node for node in workflow['workflow']['graph']['nodes']}
        start = next(x for x in nodes['start']['data']['variables'] if x['variable'] == 'style_preset')
        review = next(x for x in nodes['requirements_review']['data']['inputs']
                      if x['output_variable_name'] == 'style_preset')
        self.assertEqual(start['options'], list(styles.PRESETS))
        self.assertEqual(review['option_source']['value'], [styles.KEEP, *styles.PRESETS])
        markdown = styles.choices_markdown()
        for name in SELECTED:
            self.assertIn(styles.DETAILS[name]['image'], markdown)
            self.assertIn(styles.DETAILS[name]['video_url'], markdown)


if __name__ == '__main__':
    unittest.main()
