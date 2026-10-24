"""只读运行事件驱动网络等待显示，不操作制作会话。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import common, codex_jobs


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.courses = patch.object(common, 'COURSES', Path(self.temp.name))
        self.courses.start(); self.addCleanup(self.courses.stop)
        self.cid = 'c' * 24; self.key = 'd' * 20
        self.course = common.course_dir(self.cid)
        self.folder = self.course / 'harness/jobs' / self.key
        self.session = self.course / 'harness/sessions' / 'script'
        self.label = self.key + '-s05'
        common.save(self.course / 'harness/current.json', {'key': self.key})
        common.save(self.folder / 'job.json', {'status': 'running', 'message': '制作分镜：第5/10段。',
            'completed': 4, 'total': 10, 'scene_id': 's05', 'script_version': 'script',
            'active_label': self.label, 'retry_generation': 2, 'updated_at': 100})
        common.save(self.session / 'turns' / (self.label + '.json'),
            {'status': 'running', 'turn_id': 'current-turn', 'started_at': 100})

    def event(self, method, at, **params):
        with (self.session / 'events.jsonl').open('a') as out:
            out.write(json.dumps({'time': at, 'method': method,
                'params': {'turnId': 'current-turn', **params}}) + '\n')

    def network_error(self, at=110, **extra):
        self.event('error', at, willRetry=True,
            error={'message': 'Reconnecting... waiting for network',
                'codexErrorInfo': {'responseStreamDisconnected': {'httpStatusCode': None}}}, **extra)

    def test_reconnecting_is_displayed_without_changing_the_running_job(self):
        self.network_error()
        before = (self.folder / 'job.json').read_bytes()
        data = codex_jobs.public_status(self.cid)
        self.assertEqual(data['status'], 'network_wait')
        self.assertIn('等待网络恢复', data['message'])
        self.assertEqual(data['completed'], 4)
        self.assertEqual(data['retry_generation'], 2)
        self.assertEqual((self.folder / 'job.json').read_bytes(), before)

    def test_real_output_restores_running_with_a_newer_timestamp(self):
        self.network_error()
        waiting = codex_jobs.public_status(self.cid)
        self.event('item/reasoning/textDelta', 120, delta='model activity')
        resumed = codex_jobs.public_status(self.cid)
        self.assertEqual(resumed['status'], 'running')
        self.assertEqual(resumed['message'], '制作分镜：第5/10段。')
        self.assertGreater(resumed['updated_at'], waiting['updated_at'])

    def test_old_turn_or_local_liveness_does_not_change_connection_state(self):
        self.network_error()
        self.event('item/started', 120, item={'type': 'userMessage'})
        self.event('thread/status/changed', 121, status='active')
        self.event('item/reasoning/textDelta', 122, turnId='old-turn', delta='old response')
        self.assertEqual(codex_jobs.public_status(self.cid)['status'], 'network_wait')

    def test_long_silence_does_not_invent_a_network_failure(self):
        self.assertEqual(codex_jobs.public_status(self.cid)['status'], 'running')

    def test_completed_job_ignores_old_network_errors(self):
        self.network_error()
        codex_jobs.update_job(self.folder, status='complete', message='分镜已保存。')
        self.assertEqual(codex_jobs.public_status(self.cid)['status'], 'complete')


if __name__ == '__main__':
    unittest.main()
