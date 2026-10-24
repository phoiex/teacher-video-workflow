"""配音连接中断后的原断点恢复；不调用外部接口。"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import common, production, production_ui


class AudioResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = patch.object(common, "COURSES", Path(self.tmp.name))
        self.paths.start()
        self.url = patch.object(production, "public_url", return_value="http://127.0.0.1:8794")
        self.url.start()
        self.cid = "d" * 24
        self.texts = ["这是已经完成的第一句。", "这是网络中断的一句。", "这是还没开始的最后一句。"]
        self.instruction = common.DEFAULT_VOICE_INSTRUCTION
        common.store(self.cid, {
            "requirements": {"duration_minutes": "4"},
            "board": {"scenes": [{"narration": x} for x in self.texts]},
            "production": {"status": "failed", "message": "配音未完成，制作已暂停。", "input_version": "v1"},
        })
        self.audio = common.course_dir(self.cid) / "audio"
        self.audio.mkdir()
        self.names = []
        for text, status in zip(self.texts, ["complete", "needs_review"]):
            name = "tts_" + common.digest({"text": text, "instruction": self.instruction, "voice": "longanlingxin"})[:24]
            self.names.append(name)
            data = {"status": status, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "instruction": self.instruction, "voice": "longanlingxin", "error_type": "URLError"}
            common.save(self.audio / (name + ".json"), data)
            if status == "complete":
                (self.audio / (name + ".wav")).write_bytes(b"existing-audio")
        self.finished = (self.audio / (self.names[0] + ".json")).read_bytes()
        self.failed = (self.audio / (self.names[1] + ".json")).read_bytes()

    def tearDown(self):
        self.paths.stop()
        self.url.stop()
        self.tmp.cleanup()

    def test_failed_audio_has_clear_location_and_retry_action(self):
        view = production_ui.snapshot(self.cid)
        self.assertEqual(view["actions"], ["continue"])
        self.assertEqual(view["action_labels"]["continue"], "重试未完成配音")
        self.assertIn("第2段第1句", view["message"])
        self.assertIn("1 / 3", view["message"])

    def test_explicit_retry_archives_only_unfinished_receipt_and_is_idempotent(self):
        result = production.control(self.cid, "continue", "v1")
        self.assertEqual(result["status"], "armed")
        self.assertEqual((self.audio / (self.names[0] + ".json")).read_bytes(), self.finished)
        self.assertEqual((self.audio / (self.names[0] + ".wav")).read_bytes(), b"existing-audio")
        self.assertFalse((self.audio / (self.names[1] + ".json")).exists())
        archives = list((self.audio / "attempts").rglob(self.names[1] + ".json"))
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0].read_bytes(), self.failed)
        production.control(self.cid, "continue", "v1")
        self.assertEqual(len(list((self.audio / "attempts").rglob(self.names[1] + ".json"))), 1)
        self.assertFalse(production.ACTIVE)

    def test_stale_version_cannot_requeue_audio(self):
        with self.assertRaises(ValueError):
            production.control(self.cid, "continue", "old-version")
        self.assertTrue((self.audio / (self.names[1] + ".json")).exists())

    def test_unmatched_receipt_does_not_offer_retry(self):
        file = self.audio / (self.names[1] + ".json")
        data = json.loads(file.read_text())
        data["text_sha256"] = "different-input"
        common.save(file, data)
        self.assertEqual(production_ui.snapshot(self.cid)["actions"], [])
        with self.assertRaises(ValueError):
            production.control(self.cid, "continue", "v1")


if __name__ == "__main__":
    unittest.main()
