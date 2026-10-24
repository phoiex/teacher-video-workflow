"""制作中的展示、动作与完成状态回归；不生成配音或视频。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import common, production, production_ui


class ProductionUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.paths = patch.object(common, "COURSES", Path(self.temp.name))
        self.paths.start()
        self.url = patch.object(production, "public_url", return_value="http://127.0.0.1:8794")
        self.url.start()
        self.url2 = patch.object(production_ui, "public_url", return_value="http://127.0.0.1:8794")
        self.url2.start()
        self.cid = "c" * 24
        common.store(self.cid, {"requirements": {"duration_minutes": "4"},
            "board": {"scenes": [{}] * 12}, "approvals": {},
            "production": {"status": "running", "message": "制作画面：第6/12段", "input_version": "v1"}})
        build = common.course_dir(self.cid) / "build/v1"
        build.mkdir(parents=True)
        for index in range(5):
            (build / f"s{index}.done.json").write_text("{}")

    def tearDown(self):
        self.paths.stop(); self.url.stop(); self.url2.stop(); self.temp.cleanup()

    def status(self, status, **fields):
        s = common.state(self.cid); s["production"].update(status=status, **fields)
        common.store(self.cid, s)

    def test_running_has_one_consistent_progress_and_only_pause(self):
        result = production_ui.snapshot(self.cid)
        self.assertEqual(result["actions"], ["pause"])
        self.assertEqual(result["completed_segments"], 5)
        self.assertEqual(result["message"], "已完成 5 / 12 段动画。")
        self.assertEqual(result["status"], "running")

    def test_pause_resume_and_duration_are_different_decisions(self):
        for status, actions in [("paused", ["continue"]), ("duration_review", ["accept_duration", "revise"]),
                                ("failed", []), ("complete", [])]:
            self.status(status, actual_seconds=260)
            self.assertEqual(production_ui.snapshot(self.cid)["actions"], actions)

    def test_complete_has_only_existing_results_and_stale_pause_cannot_undo_it(self):
        self.status("complete", output_version="v1", actual_seconds=181.9)
        folder = common.course_dir(self.cid) / "deliverables/v1"
        folder.mkdir(parents=True); (folder / "lesson.mp4").write_bytes(b"fixture")
        result = production_ui.snapshot(self.cid)
        self.assertEqual(list(result["files"]), ["lesson.mp4"])
        before = common.state(self.cid)
        for action in ("pause", "continue", "check"):
            self.assertTrue(production.control(self.cid, action, "v1")["done"])
        self.assertEqual(before, common.state(self.cid))

    def test_active_render_must_stop_before_script_changes(self):
        production.ACTIVE.add(self.cid)
        try:
            with self.assertRaises(ValueError):
                production.control(self.cid, "revise", "v1")
        finally:
            production.ACTIVE.discard(self.cid)
        self.assertEqual(common.state(self.cid)["production"]["status"], "running")

    def test_explicit_revision_after_completion_still_returns_to_script(self):
        self.status("complete", output_version="v1", actual_seconds=181.9)
        production.control(self.cid, "revise", "v1")
        self.assertEqual(common.state(self.cid)["phase"], "script")
        self.assertEqual(common.state(self.cid)["production"]["status"], "needs_script")

    def test_pause_request_keeps_current_work_without_invalid_buttons(self):
        self.status("running", pause_requested=True)
        result = production_ui.snapshot(self.cid)
        self.assertEqual(result["actions"], [])
        self.assertIn("保存后暂停", result["message"])


if __name__ == "__main__":
    unittest.main()
