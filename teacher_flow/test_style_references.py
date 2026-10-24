"""验证上传素材到风格确认的契约；模型使用固定回执，不发起外部请求。"""
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from . import common, engine, prompts, style_references as refs, styles


class StyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = patch.object(common, "COURSES", self.root / "courses")
        self.paths.start()
        self.model_patch = patch.object(engine.model_call, "generate")
        self.model = self.model_patch.start()
        self.cid = engine.new_course({"requirement": "面向中学生，四分钟的注意力机制讲解。",
                                     "style_preset": "暖色图解", "style_notes": "中文大一些。",
                                     "style_files": [{"filename": "参考.png"}]})["course_id"]

    def tearDown(self):
        self.paths.stop()
        self.model_patch.stop()
        self.temp.cleanup()

    def sample_prepared(self):
        return {"assets": [{"name": "参考.png", "kind": "image", "image_ids": ["ref01_01"],
                            "sample_times": [], "duration_seconds": None}],
                "images": [{"image_id": "ref01_01", "path": str(self.root / "image.jpg"),
                            "sha256": "abc", "timestamp_seconds": None}],
                "issues": []}

    def test_no_reference_does_not_call_model(self):
        s = common.state(self.cid); s["style_files"] = []; common.store(self.cid, s)
        engine.prepare_references(self.cid)
        self.model.assert_not_called()

    def test_reference_and_teacher_preferences_reach_review_then_approval(self):
        self.model.return_value = {"summary": "米色背景和深棕字。", "evidence_ids": ["ref01_01"]}
        with patch.object(refs, "prepare", return_value=self.sample_prepared()):
            engine.prepare_references(self.cid)
            engine.prepare_references(self.cid)
        self.assertEqual(self.model.call_count, 1)
        self.assertEqual(self.model.call_args.kwargs["images"][0]["image_id"], "ref01_01")
        self.assertNotIn("path", self.model.call_args.args[2]["frames"][0])
        self.model.return_value = {"topic": "注意力机制", "audience": "中学生",
                                  "duration_minutes": "4", "style": "", "questions": []}
        shown = engine.show(self.cid, "requirements")
        self.assertIn("米色背景", shown["style"])
        self.assertIn("中文大一些", shown["style"])
        engine.apply(self.cid, "requirements", {**shown, "action": "approve",
                     "style_preset": styles.KEEP, "production_mode": "先看分镜",
                     "style": "老师改为白底棕字，保留细线。"})
        requirements = common.state(self.cid)["requirements"]
        self.assertEqual(requirements["style_preset"], "暖色图解")
        self.assertEqual(requirements["style"], "老师改为白底棕字，保留细线。")
        self.assertNotIn("script", common.state(self.cid)["approvals"])

    def test_failed_unknown_analysis_is_not_resent(self):
        self.model.side_effect = RuntimeError("unknown")
        with patch.object(refs, "prepare", return_value=self.sample_prepared()):
            engine.prepare_references(self.cid)
            engine.prepare_references(self.cid)
        self.assertEqual(self.model.call_count, 1)
        self.assertEqual(common.state(self.cid)["style_reference"]["status"], "unavailable")

    def test_interrupted_analysis_is_not_resent(self):
        s = common.state(self.cid); s["style_reference"] = {"status": "analyzing"}
        common.store(self.cid, s)
        engine.prepare_references(self.cid)
        self.model.assert_not_called()

    def test_bad_reference_is_visible_and_never_sent_to_model(self):
        bad = {"assets": [], "images": [], "issues": [{"name": "坏文件", "message": "请重新上传"}]}
        with patch.object(refs, "prepare", return_value=bad):
            engine.prepare_references(self.cid)
        self.model.assert_not_called()
        self.model.return_value = {"topic": "主题"}
        self.assertIn("请重新上传", engine.show(self.cid, "requirements")["view"])

    def test_resume_does_not_replace_approved_work_or_references(self):
        before = common.state(self.cid)
        engine.new_course({"requirement": "继续", "resume_course": self.cid,
                           "style_preset": "空间代码动画", "style_files": []})
        self.assertEqual(common.state(self.cid), before)

    def test_presets_route_explicitly_without_keywords_in_notes_taking_over(self):
        self.assertEqual(styles.branch("不要暖色", "ASCII 终端科技"), "ascii-terminal.md")
        self.assertIsNone(styles.branch("用暖色也行", "自由设计"))
        self.assertEqual(styles.branch("深色科技"), "openfilm-cinematic.md")
        self.assertIn("分支一", prompts.assemble("storyboard", "", "暖色图解"))

    def test_no_reference_means_free_design_and_custom_needs_details(self):
        self.assertEqual(styles.resolve("", "")["style_preset"], "自由设计")
        with self.assertRaises(ValueError):
            styles.resolve("自定义", "")

    def test_graph_orders_reference_before_requirements_and_offers_optional_upload(self):
        import yaml
        graph=yaml.safe_load((common.TOOL/'workflow/teacher-video.yml').read_text())['workflow']['graph']
        nodes = {node["id"]: node for node in graph["nodes"]}
        edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}
        chain = ["create_data", "materials_args", "materials_prepare", "materials_data", "style_args", "style_prepare", "style_data", "requirements_loop"]
        self.assertTrue(all(pair in edges for pair in zip(chain, chain[1:])))
        self.assertNotIn(("create_data", "requirements_loop"), edges)
        fields = {field["variable"]: field for field in nodes["start"]["data"]["variables"]}
        self.assertFalse(fields["style_files"]["required"])
        self.assertEqual(fields["style_files"]["allowed_file_types"], ["image", "video"])
        self.assertEqual(fields["style_preset"]["options"], list(styles.PRESETS))

    def test_local_reader_rejects_webpages_traversal_and_other_services(self):
        for url in ["file:///etc/passwd", "http://127.0.0.1:8794/assets/a",
                    "http://127.0.0.1:8788/console/api/apps", "https://example.com/video.mp4",
                    "http://127.0.0.1:8788/files/%2e%2e/secret"]:
            with self.assertRaises(ValueError, msg=url):
                refs.local_file_url(url)
        self.assertTrue(refs.local_file_url("http://127.0.0.1:8788/files/a/file-preview?sign=abc"))

    def test_real_image_is_read_and_evidence_ids_checked(self):
        source = self.root / "sample.png"
        Image.new("RGB", (1920, 1080), "#ffedcf").save(source)
        with patch.object(refs, "download", return_value=source):
            prepared = refs.prepare(self.cid, [{"filename": "图片.png"}])
        self.assertEqual(len(prepared["images"]), 1)
        with Image.open(prepared["images"][0]["path"]) as image:
            self.assertEqual(image.size, (1280, 720))
        with self.assertRaises(ValueError):
            refs.style_description({"summary": "暖色", "evidence_ids": ["invented"]}, {"ref01_01"})

    def test_real_video_has_ordered_timestamped_motion_samples(self):
        source = self.root / "moving.mp4"
        subprocess.run([refs.executable("ffmpeg"), "-v", "error", "-f", "lavfi",
                        "-i", "testsrc2=size=320x180:rate=10:duration=3",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source)], check=True)
        with patch.object(refs, "download", return_value=source):
            prepared = refs.prepare(self.cid, [{"filename": "动图.mp4"}])
        self.assertFalse(prepared["issues"])
        self.assertEqual(len(prepared["images"]), 12)
        times = prepared["assets"][0]["sample_times"]
        self.assertEqual(times, sorted(times))
        self.assertTrue(all(0 <= time < 3 for time in times))
        self.assertGreater(len({item["sha256"] for item in prepared["images"]}), 3)


if __name__ == "__main__":
    unittest.main()
