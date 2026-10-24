import unittest
import urllib.error
from unittest.mock import Mock, patch
from . import network_retry as retry


class NetworkRetryTests(unittest.TestCase):
    def test_transient_connection_recovers_and_reports_progress(self):
        fn = Mock(side_effect=[ConnectionError(), TimeoutError(), 'saved'])
        events = []
        with patch.object(retry, 'wait') as wait:
            self.assertEqual(retry.call(fn, on_retry=events.append), 'saved')
        self.assertEqual(fn.call_count, 3)
        self.assertEqual([x['attempt'] for x in events if x['waiting']], [2,3])
        self.assertEqual([x['attempt'] for x in events if not x['waiting']], [2,3])
        self.assertEqual(wait.call_count, 2)

    def test_exhaustion_is_bounded_and_manual_retry_starts_new_cycle(self):
        fn = Mock(side_effect=TimeoutError())
        with patch.object(retry, 'wait'):
            with self.assertRaises(retry.NetworkFailure): retry.call(fn)
        self.assertEqual(fn.call_count, 3)
        self.assertEqual(retry.call(lambda _: 'next cycle'), 'next cycle')

    def test_content_auth_and_quota_failures_are_not_network_retries(self):
        for exc in (ValueError('invalid JSON'), urllib.error.HTTPError('http://local',401,'denied',{},None),
                    urllib.error.HTTPError('http://local',429,'insufficient_quota',{},None)):
            fn = Mock(side_effect=exc)
            with self.assertRaises(type(exc)): retry.call(fn)
            self.assertEqual(fn.call_count,1)

    def test_pause_interrupts_backoff_before_next_request(self):
        checkpoint=Mock(side_effect=[None, RuntimeError('paused')])
        fn=Mock(side_effect=ConnectionError())
        with self.assertRaisesRegex(RuntimeError,'paused'):
            retry.call(fn,checkpoint=checkpoint)
        self.assertEqual(fn.call_count,1)
