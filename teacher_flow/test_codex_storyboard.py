"""课程工具边界及任务幂等；不调用模型或配音。"""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import common,codex_jobs
from .codex_storyboard import BoardTools


class StoryboardContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.scene={'id':'s01','narration':'固定原稿。','caption':'标题','animation':'图形展开',
                    'html':'<script>window.SCENE;window.film={frame(t){}}</script>'}
        self.inputs={'script':'固定原稿。','requirements':{},
                     'previous_storyboard':{'scenes':[self.scene]}}
        self.tools=BoardTools(self.folder,self.inputs)
        self.tools.allowed_scene='s01'

    def tearDown(self):self.temp.cleanup()

    def test_plan_cannot_change_script(self):
        self.tools.allow_plan=True
        scene={**self.scene,'narration':'修改后的讲稿。'}
        with self.assertRaisesRegex(ValueError,'固定讲稿'):
            self.tools.call('course_plan',{'visual_direction':'清晰','scenes':[scene]})

    def test_scene_scope_and_paths_are_restricted(self):
        for sid in ['../state','s02']:
            with self.assertRaises(ValueError):self.tools.call('course_scene',{'scene_id':sid})

    def test_saved_scene_can_finish_without_preview_or_review_quota(self):
        for _ in range(30):
            self.tools.call('course_scene',{'scene_id':'s01'})
        result=self.tools.result()
        self.assertEqual(result['scenes'][0]['html'],self.scene['html'])
        self.assertFalse((self.folder/'s01.review.json').exists())

    def test_plan_and_delivery_accept_more_than_forty_scenes(self):
        from .engine import validate_board
        scenes=[{**self.scene,'id':f's{index:02d}','narration':'词。'} for index in range(1000,1042)]
        inputs={'script':'词。'*len(scenes),'requirements':{}}
        tools=BoardTools(self.folder/'large',inputs);tools.allow_plan=True
        board={'scenes':scenes,'visual_direction':'fixture'}
        self.assertTrue(tools.call('course_plan',board)['success'])
        self.assertEqual(tools.scene('s1041')['narration'],'词。')
        validate_board(board,inputs['script'])

    def test_scene_source_is_not_cut_off_at_a_local_character_budget(self):
        source=self.scene['html']+'<!--'+('visual content '*15000)+'-->'
        self.assertTrue(self.tools.call('course_write',{'scene_id':'s01','html':source})['success'])
        self.assertEqual((self.folder/'s01.html').read_text(),source)

    def test_review_is_an_optional_note_not_a_render_gate(self):
        review={'scene_id':'s01','observations':'待看转场。','approved':False}
        self.assertTrue(self.tools.call('course_review',review)['success'])
        note=common.load(self.folder/'s01.review.json')
        self.assertEqual(note['viewed_paths'],[])
        self.assertFalse(note['approved'])
        self.assertEqual(self.tools.result()['scenes'][0]['id'],'s01')

    def test_preview_times_are_chosen_by_agent(self):
        rendered=[]
        def render(command, **kwargs):
            spec=common.load(command[-1]);rendered.append(spec['time'])
            Path(spec['output']).write_bytes(b'image')
            from types import SimpleNamespace
            return SimpleNamespace(returncode=0)
        with patch('teacher_flow.codex_storyboard.subprocess.run',side_effect=render):
            self.tools.call('course_render',{'scene_id':'s01'})
            record=common.load(self.folder/'s01.rendered.json')
            self.assertEqual(record['time_fractions'],[.5])
            self.tools.call('course_render',{'scene_id':'s01','time_fractions':[0,.8]})
            record=common.load(self.folder/'s01.rendered.json')
            self.assertEqual(record['time_fractions'],[0,.8])
            self.assertEqual(len(record['paths']),2)
        self.assertEqual(len(rendered),3)

    def test_fixed_input_tampering_stops_tools(self):
        altered=copy.deepcopy(self.inputs);altered['script']='偷偷修改'
        common.save(self.folder/'input.json',altered)
        with self.assertRaisesRegex(ValueError,'固定输入'):
            self.tools.call('course_read',{})

    def test_same_job_does_not_launch_twice(self):
        cid='1'*24
        with patch.object(common,'COURSES',self.folder/'courses'), \
             patch.object(codex_jobs,'inputs_for',return_value=self.inputs), \
             patch.object(codex_jobs,'_launch') as launch:
            s={'approved_script':'固定原稿。','approvals':{'script':common.version('固定原稿。')}}
            common.store(cid,s)
            first=codex_jobs.ensure(cid,s);second=codex_jobs.ensure(cid,s)
        self.assertEqual(first['key'],second['key']);self.assertEqual(launch.call_count,1)

    def test_paused_job_needs_explicit_continue(self):
        cid='2'*24
        with patch.object(common,'COURSES',self.folder/'courses'), \
             patch.object(codex_jobs,'inputs_for',return_value=self.inputs), \
             patch.object(codex_jobs,'_launch') as launch:
            s={'approved_script':'固定原稿。','approvals':{'script':common.version('固定原稿。')}}
            common.store(cid,s);job=codex_jobs.ensure(cid,s)
            codex_jobs.update_job(codex_jobs.job_dir(cid,job['key']),status='paused')
            codex_jobs.ensure(cid,s);codex_jobs.touch(cid)
            self.assertEqual(launch.call_count,1)
            codex_jobs.control(cid,job['key'],'continue')
            self.assertEqual(launch.call_count,2)

    def test_unknown_job_is_not_resubmitted(self):
        cid='3'*24
        with patch.object(common,'COURSES',self.folder/'courses'), \
             patch.object(codex_jobs,'inputs_for',return_value=self.inputs), \
             patch.object(codex_jobs,'_launch') as launch:
            s={'approved_script':'固定原稿。','approvals':{'script':common.version('固定原稿。')}}
            common.store(cid,s);job=codex_jobs.ensure(cid,s)
            codex_jobs.update_job(codex_jobs.job_dir(cid,job['key']),status='unknown')
            codex_jobs.ensure(cid,s);codex_jobs.control(cid,job['key'],'continue')
            self.assertEqual(launch.call_count,1)


if __name__=='__main__':unittest.main()
