import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from . import common, engine, stage_operations, network_retry


class StageOperationsTests(unittest.TestCase):
    def test_stage_failure_is_visible_and_a_new_cycle_can_complete(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(common,'COURSES',Path(tmp)/'courses'),patch.object(stage_operations,'RUNTIME',Path(tmp)):
            cid='c'*24;run='11111111-1111-1111-1111-111111111111'
            common.store(cid,{'id':cid})
            common.save(Path(tmp)/'workflow-runs'/f'{run}.json',{'course_id':cid})
            fail=True
            def prepare_script(cid,step):
                if fail:raise network_retry.NetworkFailure()
                return {'saved':True}
            with self.assertRaises(network_retry.NetworkFailure):stage_operations.execute(prepare_script,cid,'draft')
            failed=stage_operations.status_for_run(run)
            self.assertEqual(failed['status'],'failed');self.assertTrue(failed['retryable'])
            self.assertEqual(failed['course_id'],cid)
            fail=False
            self.assertTrue(stage_operations.execute(prepare_script,cid,'draft')['saved'])
            self.assertEqual(stage_operations.status_for_run(run)['status'],'complete')

    def test_network_failure_does_not_silently_skip_reference_analysis(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(common,'COURSES',Path(tmp)/'courses'):
            cid=engine.new_course({'requirement':'fixture','style_files':[{'filename':'test.png'}]})['course_id']
            prepared={'assets':[],'issues':[],'images':[{'image_id':'r','path':'fixture'}]}
            with patch.object(engine.style_references,'prepare',return_value=prepared),patch.object(engine.model_call,'generate',side_effect=network_retry.NetworkFailure()) as model:
                for _ in range(2):
                    with self.assertRaises(network_retry.NetworkFailure):engine.prepare_references(cid)
                self.assertEqual(model.call_count,2)
                self.assertTrue(common.state(cid)['style_reference']['retryable'])
