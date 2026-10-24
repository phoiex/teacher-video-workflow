"""No external services: verify recovery ownership, saved versions and course reuse."""
import json
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from werkzeug.exceptions import Conflict, NotFound

import controllers.console  # Match the API's controller bootstrap before loading execution services.
from models.enums import CreatorUserRole
from services import workflow_retry_service as recovery


class RetryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.app = SimpleNamespace(id="app", tenant_id="tenant")
        self.user = SimpleNamespace(id="teacher")
        self.graph = {"nodes": [{"id": "original"}]}
        self.run = SimpleNamespace(id="run", app_id="app", tenant_id="tenant", workflow_id="old-release",
                                   version="A", graph_dict=self.graph, status="failed",
                                   created_by_role=CreatorUserRole.END_USER, created_by="teacher")
        self.workflow = SimpleNamespace(id="old-release", app_id="app", tenant_id="tenant", version="A",
                                        graph_dict=self.graph)

    def test_published_run_uses_its_original_version(self):
        self.assertTrue(recovery.validate_retry_source(self.run, self.workflow, self.app, self.user, public=True))
        self.workflow.version = "B"
        with self.assertRaises(Conflict):
            recovery.validate_retry_source(self.run, self.workflow, self.app, self.user, public=True)

    def test_changed_draft_cannot_silently_replace_saved_graph(self):
        self.workflow.version = self.run.version = "draft"
        self.workflow.graph_dict = {"nodes": [{"id": "changed"}]}
        with self.assertRaises(Conflict):
            recovery.validate_retry_source(self.run, self.workflow, self.app, self.user, public=False)

    def test_other_teacher_app_or_workspace_cannot_retry(self):
        for field, value in (("created_by", "other"), ("app_id", "other"), ("tenant_id", "other")):
            with self.subTest(field=field), patch.object(self.run, field, value), self.assertRaises(NotFound):
                recovery.validate_retry_source(self.run, self.workflow, self.app, self.user, public=True)

    def test_running_or_completed_request_only_reconnects(self):
        for status in ("running", "paused", "succeeded"):
            self.run.status = status
            self.assertFalse(recovery.validate_retry_source(self.run, self.workflow, self.app, self.user, public=True))

    def test_original_course_is_recovered_from_node_outputs(self):
        course = "a" * 24
        for output in ({"course_id": course}, {"body": json.dumps({"course_id": course})}):
            self.assertEqual(recovery.retry_inputs({"requirement": "old"}, [output], supports_course_resume=True),
                             {"inputs": {"resume_course": course}, "files": []})

    def test_before_course_creation_original_files_and_inputs_survive(self):
        inputs = {"requirement": "topic", "source_files": [{"upload_file_id": "file"}],
                  "sys.files": [{"id": "original"}], "sys.workflow_run_id": "old"}
        result = recovery.retry_inputs(inputs, [], supports_course_resume=True)
        self.assertEqual(result["inputs"]["source_files"], inputs["source_files"])
        self.assertEqual(result["files"], inputs["sys.files"])
        self.assertNotIn("sys.workflow_run_id", result["inputs"])

    def test_repeated_request_queues_one_successor(self):
        cache = {}
        redis = MagicMock()
        redis.lock.side_effect = lambda *a, **k: nullcontext()
        redis.get.side_effect = lambda key: cache.get(key)
        redis.set.side_effect = lambda key, value: cache.__setitem__(key, value)
        plan = '{"workflow_run_id":"next"}'
        database = MagicMock()
        database.return_value.__enter__.return_value.scalar.return_value = "next"
        with patch.object(recovery, "_load_plan", return_value=plan), \
                patch.object(recovery, "redis_client", redis), patch.object(recovery, "Session", database), \
                patch.object(recovery, "db", SimpleNamespace(engine=None)), \
                patch.object(recovery, "_enqueue") as send:
            first = recovery.retry_workflow(self.app, self.user, "run", public=True)
            second = recovery.retry_workflow(self.app, self.user, "run", public=True)
        self.assertEqual(first["workflow_run_id"], second["workflow_run_id"])
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        send.assert_called_once()

    def test_lost_creation_response_recovers_the_saved_course_after_closing_database(self):
        from core.helper import ssrf_proxy
        from services.app_generate_service import AppGenerateService
        from tasks.app_generate.workflow_execute_task import AppExecutionParams

        course = "d" * 24
        self.run.inputs_dict = {"requirement": "saved input"}
        self.workflow.graph_dict = {
            "nodes": [{"id": "start", "data": {"type": "start", "variables": [{"variable": "resume_course"}]}},
                      {"id": "create", "data": {"type": "http-request"}}]}
        self.run.graph_dict = self.workflow.graph_dict
        self.workflow.environment_variables = [SimpleNamespace(name="LOCAL_TOOL_URL", value="http://host.docker.internal:8794")]
        database = MagicMock()
        session = database.return_value.__enter__.return_value
        session.scalar.side_effect = [self.run, self.workflow]
        session.get.return_value = self.user
        session.scalars.return_value.all.return_value = [SimpleNamespace(node_id="create", outputs_dict={})]
        closed = []
        database.return_value.__exit__.side_effect = lambda *args: closed.append(True)
        plan = SimpleNamespace(args={})
        plan.model_dump_json = lambda: json.dumps(plan.args)
        def receive(url, **kwargs):
            self.assertTrue(closed)
            self.assertEqual(url, "http://host.docker.internal:8794/stage-status/run")
            response = MagicMock()
            response.json.return_value = {"course_id": course}
            return response
        with patch.object(recovery, "Session", database), patch.object(recovery, "db", SimpleNamespace(engine=None)), \
                patch.object(AppGenerateService, "_ensure_workflow_service_mode_available"), \
                patch.object(AppExecutionParams, "new", return_value=plan), patch.object(ssrf_proxy, "get", side_effect=receive):
            result = json.loads(recovery._load_plan(self.app, self.user, "run", True))
        self.assertEqual(result["inputs"], {"resume_course": course})


if __name__ == "__main__":
    unittest.main()
