"""断网后的显式续作；用本地回执替代模型请求。"""
import fcntl
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import common, codex_jobs


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cid = 'a' * 24
        self.inputs = {'script': '已确认的讲稿。', 'requirements': {}}
        self.saved = {'approved_script': self.inputs['script'],
                      'approvals': {'script': common.version(self.inputs['script'])}}
        self.courses = patch.object(common, 'COURSES', self.root / 'courses')
        self.courses.start(); self.addCleanup(self.courses.stop)
        self.launcher = patch.object(codex_jobs, '_launch')
        self.launch = self.launcher.start(); self.addCleanup(self.launcher.stop)
        common.store(self.cid, self.saved)
        with patch.object(codex_jobs, 'inputs_for', return_value=self.inputs):
            self.job = codex_jobs.ensure(self.cid, self.saved)
        self.launch.reset_mock()
        self.key = self.job['key']
        self.folder = codex_jobs.job_dir(self.cid, self.key)
        self.session = common.course_dir(self.cid) / 'harness/sessions' / self.saved['approvals']['script']
        common.save(self.session / 'thread.json', {'id': 'same-session'})
        common.save(self.folder / 'work/plan.json', {'scenes': [{'id': 's01'}, {'id': 's02'}]})
        (self.folder / 'work/s01.html').write_text('finished scene')
        (self.folder / 'work/s02.html').write_text('partial scene')
        self.receipt('s01', 'completed')
        self.receipt('s02', 'failed')
        codex_jobs.update_job(self.folder, status='failed', completed=1, total=2, scene_id='s02')

    def receipt(self, scene, status):
        common.save(self.session / 'turns' / (self.key + '-' + scene + '.json'),
                    {'label': self.key + '-' + scene, 'status': status, 'thread_id': 'same-session'})

    def test_one_click_resumes_same_job_and_preserves_all_saved_work(self):
        old_files = {p: p.read_bytes() for p in self.session.rglob('*.json')}
        old_files.update({p: p.read_bytes() for p in (self.folder / 'work').iterdir()})
        data = codex_jobs.control(self.cid, self.key, 'retry')
        codex_jobs.control(self.cid, self.key, 'retry')
        self.assertEqual(data['status'], 'queued')
        self.launch.assert_called_once_with(self.cid, self.key)
        for p, before in old_files.items():
            self.assertEqual(p.read_bytes(), before)
        pointer = common.load(self.session / 'continuations' / (self.key + '-s02.json'))
        self.assertEqual(pointer['authorized_by'], 'user')
        self.assertEqual(pointer['original_label'], self.key + '-s02')
        self.assertNotEqual(pointer['continuation_label'], self.key + '-s02')
        self.assertFalse((self.session / 'continuations' / (self.key + '-s01.json')).exists())

    def test_poll_keeps_failure_available_for_user_retry_without_new_request(self):
        with patch.object(codex_jobs, 'inputs_for', return_value=self.inputs):
            data, result = codex_jobs.poll(self.cid, self.saved, seconds=0)
        self.assertEqual(data['status'], 'failed')
        self.assertIsNone(result)
        self.launch.assert_not_called()

    def test_retry_does_not_overlap_a_worker(self):
        with (self.folder / 'worker.lock').open('a') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, '仍在运行'):
                codex_jobs.control(self.cid, self.key, 'retry')
        self.launch.assert_not_called()

    def test_changed_approved_script_cannot_continue_old_job(self):
        common.store(self.cid, {**self.saved, 'approved_script': '新讲稿'})
        with self.assertRaisesRegex(ValueError, '讲稿'):
            codex_jobs.control(self.cid, self.key, 'retry')
        self.launch.assert_not_called()

    def test_unknown_requires_click_and_plan_can_resume(self):
        (self.folder / 'work/plan.json').unlink()
        self.receipt('plan', 'unknown')
        codex_jobs.update_job(self.folder, status='unknown', scene_id=None)
        with patch.object(codex_jobs, 'inputs_for', return_value=self.inputs):
            codex_jobs.ensure(self.cid, self.saved)
        self.launch.assert_not_called()
        codex_jobs.control(self.cid, self.key, 'retry')
        self.launch.assert_called_once_with(self.cid, self.key)
        self.assertTrue((self.session / 'continuations' / (self.key + '-plan.json')).exists())

    def test_completed_response_without_plan_can_be_retried_explicitly(self):
        (self.folder / 'work/plan.json').unlink()
        self.receipt('plan', 'completed')
        previous=(self.session/'turns'/(self.key+'-plan.json')).read_bytes()
        codex_jobs.control(self.cid,self.key,'retry')
        self.launch.assert_called_once_with(self.cid,self.key)
        pointer=common.load(self.session/'continuations'/(self.key+'-plan.json'))
        self.assertEqual(pointer['previous_status'],'completed')
        self.assertEqual((self.session/'turns'/(self.key+'-plan.json')).read_bytes(),previous)

    def test_late_duplicate_click_does_not_retry_a_new_failure(self):
        codex_jobs.control(self.cid, self.key, 'retry', retry_generation=0)
        codex_jobs.update_job(self.folder, status='failed')
        codex_jobs.control(self.cid, self.key, 'retry', retry_generation=0)
        self.launch.assert_called_once_with(self.cid, self.key)

    def test_current_failed_turn_is_not_confused_with_an_old_unknown_turn(self):
        self.receipt('s01-old', 'unknown')
        codex_jobs.update_job(self.folder, active_label=self.key + '-s02')
        with patch('teacher_flow.codex_storyboard.produce', side_effect=RuntimeError('disconnected')):
            with self.assertRaises(RuntimeError):
                codex_jobs.worker(self.cid, self.key)
        self.assertEqual(common.load(self.folder / 'job.json')['status'], 'failed')

    def test_retry_failure_shows_current_service_error_without_exposing_raw_details(self):
        label=self.key+'-s02'
        common.save(self.session/'turns'/(label+'.json'), {
            'status':'failed', 'terminal':{'error':{'message':'request rejected at https://private.example/v1',
                'codexErrorInfo':{'responseTooManyFailedAttempts':{'httpStatusCode':429}}}}})
        codex_jobs.update_job(self.folder,active_label=label,retry_generation=1)
        public=codex_jobs.public_status(self.cid)
        self.assertIn('本次重试未成功',public['message'])
        self.assertIn('429',public['message'])
        self.assertNotIn('private.example',str(public))
        self.assertEqual(public['retry_generation'],1)
        self.assertIn('updated_at',public)

    def test_running_status_does_not_keep_an_earlier_error(self):
        codex_jobs.update_job(self.folder,status='queued',retry_generation=2,message='正在恢复制作。')
        public=codex_jobs.public_status(self.cid)
        self.assertEqual(public['status'],'queued')
        self.assertEqual(public['message'],'正在恢复制作。')

    def test_completed_response_without_plan_reports_missing_result(self):
        (self.folder / 'work/plan.json').unlink()
        self.receipt('plan', 'completed')
        codex_jobs.update_job(self.folder, active_label=self.key+'-plan', completed=0, total=0)
        public = codex_jobs.public_status(self.cid)
        self.assertIn('没有保存分镜计划', public['message'])
        self.assertNotIn('已保存完成', public['message'])
        self.launch.assert_not_called()

    def test_empty_response_is_not_reported_as_a_network_error(self):
        label = self.key+'-s02'
        common.save(self.session/'turns'/(label+'.json'), {'status':'failed',
            'terminal':{'error':{'message':'模型响应已结束，但没有返回正文或工具调用。'}}})
        codex_jobs.update_job(self.folder, active_label=label)
        public = codex_jobs.public_status(self.cid)
        self.assertIn('没有返回制作内容', public['message'])
        self.assertNotIn('连接中断', public['message'])

    def test_timeout_shows_saved_draft_and_preview_without_marking_scene_complete(self):
        label = self.key+'-s01'
        (self.folder/'work/s02.html').unlink()
        preview = self.folder/'work/frame.png'
        preview.write_bytes(b'fixture-preview')
        common.save(self.folder/'work/s01.rendered.json', {
            'source_hash': common.digest((self.folder/'work/s01.html').read_bytes()),
            'paths': [str(preview)]})
        common.save(self.session/'turns'/(label+'.json'), {'status':'failed',
            'terminal':{'error':{'codexErrorInfo':'other', 'message':
                'unexpected status 408 Request Timeout: {"detail":"litellm.Timeout: AnthropicException - request body receive timeout"}, url: http://private.example/responses'}}})
        codex_jobs.update_job(self.folder, active_label=label, scene_id='s01', completed=0)
        public = codex_jobs.public_status(self.cid)
        self.assertEqual(public['completed'], 0)
        self.assertEqual(public['saved_scenes'], ['s01'])
        self.assertEqual(public['previewed_scenes'], ['s01'])
        self.assertIn('408', public['message'])
        self.assertIn('第1段草稿和预览已保存', public['message'])
        self.assertNotIn('private.example', str(public))
        self.assertNotIn('已保存完成', public['message'])

    def test_stale_render_is_not_counted_as_current_preview(self):
        common.save(self.folder/'work/s02.rendered.json', {'source_hash':'old', 'paths':['gone.png']})
        public = codex_jobs.public_status(self.cid)
        self.assertEqual(public['saved_scenes'], ['s01','s02'])
        self.assertEqual(public['previewed_scenes'], [])

    def test_pause_stops_existing_worker_once_and_shows_pausing_until_exit(self):
        codex_jobs.update_job(self.folder,status='running',pid=os.getpid())
        with patch.object(codex_jobs,'_signal_legacy_worker') as signal_worker:
            codex_jobs.control(self.cid,self.key,'pause')
            codex_jobs.control(self.cid,self.key,'pause')
            signal_worker.assert_called_once()
            self.assertEqual(codex_jobs.public_status(self.cid)['status'],'pausing')
        self.launch.assert_not_called()
        with patch.object(codex_jobs,'_worker_alive',return_value=False):
            self.assertEqual(codex_jobs.status(self.cid)['status'],'paused')

    def test_continue_after_pause_preserves_interrupted_receipt_and_uses_new_turn(self):
        self.receipt('s02','interrupted')
        old=(self.session/'turns'/(self.key+'-s02.json')).read_bytes()
        codex_jobs.update_job(self.folder,status='paused')
        common.save(self.folder/'control.json',{'pause':True})
        codex_jobs.control(self.cid,self.key,'continue')
        self.launch.assert_called_once_with(self.cid,self.key)
        self.assertEqual((self.session/'turns'/(self.key+'-s02.json')).read_bytes(),old)
        pointer=common.load(self.session/'continuations'/(self.key+'-s02.json'))
        self.assertIn('-continue-',pointer['continuation_label'])
        self.assertFalse(common.load(self.folder/'control.json')['pause'])


if __name__ == '__main__':
    unittest.main()
