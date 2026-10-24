"""用固定数据检查审核与恢复，不调用模型、配音或视频生成。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import common, engine, production, prompts


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path_patch=patch.object(common,"COURSES",Path(self.temp.name)/"courses")
        self.path_patch.start()
        self.url_patch=patch.object(engine,"public_url",return_value="http://127.0.0.1:8794")
        self.url_patch.start()
        self.model_patch=patch.object(engine.model_call,"generate")
        self.model=self.model_patch.start()
        self.codex_patch=patch.object(engine.codex_jobs,'enabled',return_value=False)
        self.codex_patch.start()
        self.model.return_value={"topic":"测试主题","audience":"中学生","duration_minutes":"4",
            "objectives":"理解一个关系","prerequisites":"会读图","style":"","questions":[]}
        self.cid=engine.new_course({"requirement":"离线流程检查","existing_script":"这是固定原稿。"})["course_id"]

    def tearDown(self):
        self.codex_patch.stop();self.model_patch.stop();self.url_patch.stop();self.path_patch.stop();self.temp.cleanup()

    def approve_requirements(self):
        r=engine.show(self.cid,"requirements")
        engine.apply(self.cid,"requirements",{**r,"action":"approve","production_mode":"先看分镜"})

    def approve_script(self):
        self.approve_requirements()
        r=engine.show(self.cid,"script")
        engine.apply(self.cid,"script",{**r,"action":"approve"})

    def test_empty_input_rejected(self):
        with self.assertRaises(ValueError):engine.new_course({"requirement":""})

    def test_optional_null_fields_are_empty(self):
        cid=engine.new_course({"requirement":"另一课","source_text":None,
                              "existing_script":None,"resume_course":None})["course_id"]
        self.assertEqual(common.state(cid)["existing_script"],"")

    def test_intake_result_reused(self):
        engine.show(self.cid,"requirements");engine.show(self.cid,"requirements")
        self.assertEqual(self.model.call_count,1)

    def test_stale_approval_rejected(self):
        engine.show(self.cid,"requirements")
        with self.assertRaises(ValueError):engine.apply(self.cid,"requirements",{"version":"old","action":"approve"})

    def test_script_blocked_without_requirement_approval(self):
        with self.assertRaises(ValueError):engine.show(self.cid,"script")
        self.model.assert_not_called()

    def test_invalid_duration_does_not_approve(self):
        r=engine.show(self.cid,"requirements")
        with self.assertRaises(ValueError):
            engine.apply(self.cid,"requirements",{**r,"action":"approve","duration_minutes":"0",
                                                 "production_mode":"先看分镜"})
        self.assertNotIn("requirements",common.state(self.cid)["approvals"])

    def test_voice_preference_is_preserved(self):
        r=engine.show(self.cid,"requirements")
        voice="普通话，语速稍慢，语气亲切。"
        engine.apply(self.cid,"requirements",{**r,"action":"approve","production_mode":"先看分镜",
                                              "voice_instruction":voice})
        self.assertEqual(common.state(self.cid)["requirements"]["voice_instruction"],voice)

    def test_existing_script_does_not_call_writer(self):
        self.approve_requirements();self.model.reset_mock()
        r=engine.show(self.cid,"script")
        self.assertEqual(r["approved_script"],"这是固定原稿。")
        self.model.assert_not_called()

    def start_generated_script(self):
        self.approve_requirements()
        s=common.state(self.cid);s["existing_script"]="";common.store(self.cid,s)
        self.model.reset_mock()
        self.raw={"title":"初稿标题","script":"初稿中的例子，权重零点六。",
                  "added_content":["权重示例"],"teacher_message":""}
        self.edited={"script":"改过表达的例子，权重零点六。","teacher_message":""}
        self.model.side_effect=[self.raw,self.edited]

    def test_script_is_written_then_independently_deslopped(self):
        self.start_generated_script()
        engine.prepare_script(self.cid,"draft")
        self.assertNotIn("draft",common.state(self.cid))
        self.assertEqual(common.state(self.cid)["script_job"]["raw"],self.raw)
        engine.prepare_script(self.cid,"deslop")
        self.assertEqual(self.model.call_count,2)
        first,second=self.model.call_args_list
        self.assertEqual(first.args[0],"teacher-script-draft-v2")
        self.assertEqual(second.args[0],"teacher-script-deslop-v1")
        skill=common.DESLOP.read_text()
        self.assertNotIn(skill,first.args[1])
        self.assertIn(skill,second.args[1])
        self.assertEqual(second.args[2]["draft"],self.raw)
        self.assertEqual(set(second.args[2]),{"requirements","draft"})
        s=common.state(self.cid)
        self.assertEqual(s["draft"]["script"],self.edited["script"])
        self.assertEqual(s["draft"]["added_content"],self.raw["added_content"])
        self.assertNotIn("script",s["approvals"])
        self.assertTrue(list((common.course_dir(self.cid)/"versions/script_raw").glob("*.json")))
        self.assertTrue(list((common.course_dir(self.cid)/"versions/script_deslopped").glob("*.json")))

    def test_finished_script_steps_are_reused(self):
        self.start_generated_script()
        engine.prepare_script(self.cid,"draft");engine.prepare_script(self.cid,"deslop")
        engine.prepare_script(self.cid,"draft");engine.prepare_script(self.cid,"deslop")
        r=engine.show(self.cid,"script")
        self.assertEqual(self.model.call_count,2)
        self.assertEqual(r["approved_script"],self.edited["script"])

    def test_deslop_failure_keeps_raw_and_does_not_retry(self):
        self.start_generated_script()
        self.model.side_effect=[self.raw,RuntimeError("请求结果未知")]
        engine.prepare_script(self.cid,"draft")
        with self.assertRaises(RuntimeError):engine.prepare_script(self.cid,"deslop")
        s=common.state(self.cid)
        self.assertEqual(s["script_job"]["raw"],self.raw)
        self.assertNotIn("draft",s)
        self.assertNotIn("script",s["approvals"])
        engine.prepare_script(self.cid,"draft")
        self.assertEqual(self.model.call_count,2)

    def test_invalid_raw_does_not_enter_deslop(self):
        self.start_generated_script();self.model.side_effect=[{"script":""}]
        with self.assertRaises(ValueError):engine.show(self.cid,"script")
        self.assertEqual(self.model.call_count,1)
        self.assertNotIn("draft",common.state(self.cid))

    def test_current_review_draft_is_not_silently_rewritten(self):
        self.start_generated_script()
        s=common.state(self.cid);s["draft"]=self.raw;common.store(self.cid,s)
        self.model.reset_mock()
        engine.prepare_script(self.cid,"draft");engine.prepare_script(self.cid,"deslop")
        r=engine.show(self.cid,"script")
        self.assertEqual(r["approved_script"],self.raw["script"])
        self.model.assert_not_called()

    def test_teacher_revision_uses_two_passes(self):
        self.approve_requirements();r=engine.show(self.cid,"script")
        engine.apply(self.cid,"script",{**r,"action":"revise","feedback":"把例子说具体一些"})
        self.model.reset_mock()
        self.model.side_effect=[{"title":"标题","script":"具体的初稿","added_content":[]},
                                {"script":"修改表达后的具体讲稿"}]
        r=engine.show(self.cid,"script")
        self.assertEqual(self.model.call_count,2)
        self.assertEqual(self.model.call_args_list[0].args[2]["feedback"],"把例子说具体一些")
        self.assertEqual(self.model.call_args_list[0].args[2]["previous_script"],"这是固定原稿。")
        self.assertEqual(r["approved_script"],"修改表达后的具体讲稿")
        self.assertNotIn("script_feedback",common.state(self.cid))

    def test_teacher_communication_still_uses_deslop(self):
        self.assertIn(common.DESLOP.read_text(),prompts.assemble("intake"))

    def test_dify_shows_two_ordered_script_nodes(self):
        import yaml
        graph=yaml.safe_load((common.TOOL/'workflow/teacher-video.yml').read_text())['workflow']['graph']
        nodes={n["id"]:n for n in graph["nodes"]}
        edges={(e["source"],e["target"]) for e in graph["edges"]}
        chain=["script_show_args","script_plan","script_plan_data","script_draft","script_draft_data","script_deslop",
               "script_deslop_data","script_show","script_data","script_check","script_review"]
        for pair in zip(chain,chain[1:]):self.assertIn(pair,edges)
        self.assertEqual(nodes["script_draft"]["data"]["title"],"生成讲稿初稿")
        self.assertEqual(nodes["script_deslop"]["data"]["title"],"调整讲稿表达")
        self.assertIn("materials_prepare",nodes)
        self.assertTrue(all(e['source'] in nodes and e['target'] in nodes for e in graph['edges']))
        self.assertIn(('storyboard_data','storyboard_ready'),edges)
        self.assertIn(('storyboard_ready','storyboard_paused'),edges)
        self.assertIn(('storyboard_paused','storyboard_resume'),edges)

    def test_edit_without_rewrite_preserves_original(self):
        self.approve_requirements()
        r=engine.show(self.cid,"script")
        engine.apply(self.cid,"script",{**r,"action":"revise","approved_script":"老师编辑的原文。","feedback":""})
        self.model.reset_mock();r=engine.show(self.cid,"script")
        self.assertEqual(r["approved_script"],"老师编辑的原文。")
        self.model.assert_not_called()

    def test_longer_edit_requires_new_duration_review(self):
        self.approve_requirements();r=engine.show(self.cid,"script")
        result=engine.apply(self.cid,"script",{**r,"action":"approve","approved_script":"较长讲解。"*400})
        self.assertFalse(result["done"])
        self.assertNotIn("script",common.state(self.cid)["approvals"])

    def test_script_approval_bound_to_text(self):
        self.approve_script()
        s=common.state(self.cid)
        self.assertEqual(s["approvals"]["script"],common.version(s["approved_script"]))

    def test_storyboard_cannot_change_narration(self):
        board={"scenes":[{"id":"s01","narration":"被改过。","caption":"题目",
                         "animation":"变化","html":"SCENE frame"}]}
        with self.assertRaises(ValueError):engine.validate_board(board,"固定原文。")

    def test_duplicate_scene_ids_rejected(self):
        scene={"id":"s01","narration":"原文。","caption":"题目","animation":"变化","html":"SCENE frame"}
        with self.assertRaises(ValueError):engine.validate_board({"scenes":[scene,scene]},"原文。原文。")

    def test_confirmed_bad_storyboard_repaired_once(self):
        self.approve_script();self.model.reset_mock()
        scene={"id":"s01","narration":"这是固定原稿。","caption":"题目",
               "animation":"变化","html":"SCENE frame"}
        bad={"scenes":[{**scene,"narration":"被改动。"}]}
        self.model.side_effect=[bad,{"scenes":[scene]}]
        with patch.object(engine,"save_board"):
            engine.show(self.cid,"storyboard")
        self.assertEqual(self.model.call_count,2)
        self.assertEqual(self.model.call_args_list[1].args[0],"teacher-storyboard-repair-v1")

    def test_unknown_model_request_is_not_repaired_or_retried(self):
        self.approve_script();self.model.reset_mock()
        self.model.side_effect=RuntimeError("请求结果未知")
        with self.assertRaises(RuntimeError):engine.show(self.cid,"storyboard")
        self.assertEqual(self.model.call_count,1)

    def test_codex_running_does_not_open_a_review_form(self):
        self.approve_script();self.model.reset_mock()
        with patch.object(engine.codex_jobs,'enabled',return_value=True), \
             patch.object(engine.codex_jobs,'poll',return_value=({'message':'正在制作第1段。','status':'running','key':'k'},None)):
            result=engine.show(self.cid,'storyboard',producer='codex')
        self.assertFalse(result['ready']);self.assertFalse(result['done'])
        self.assertNotIn('storyboard',common.state(self.cid)['approvals'])
        self.model.assert_not_called()

    def test_codex_result_still_requires_teacher_confirmation_and_is_cached(self):
        self.approve_script();self.model.reset_mock()
        board={'visual_direction':'清晰图解','scenes':[{'id':'s01','narration':'这是固定原稿。',
            'caption':'题目','animation':'依次展开','html':'SCENE frame'}]}
        with patch.object(engine.codex_jobs,'enabled',return_value=True), \
             patch.object(engine.codex_jobs,'poll',return_value=({'status':'complete'},board)) as generate, \
             patch.object(engine,'save_board'):
            result=engine.show(self.cid,'storyboard',producer='codex')
            again=engine.show(self.cid,'storyboard',producer='codex')
        self.assertFalse(result['done']);self.assertFalse(again['done'])
        self.assertEqual(generate.call_count,1)
        self.assertNotIn('storyboard',common.state(self.cid)['approvals'])
        self.assertEqual(common.state(self.cid)['approved_script'],'这是固定原稿。')
        self.model.assert_not_called()

    def test_production_needs_storyboard_confirmation(self):
        self.approve_script()
        with self.assertRaises(ValueError):production.start(self.cid)

    def test_course_path_traversal_rejected(self):
        with self.assertRaises(ValueError):common.course_dir("../outside")

    def test_tts_split_preserves_text_and_limit(self):
        text="这是第一句话。"+"字"*1100+"！最后一句。"
        parts=production.sentence_chunks(text)
        self.assertEqual("".join(parts),text)
        self.assertTrue(all(len(x)<=500 for x in parts))

    def test_returning_presence_does_not_auto_resume(self):
        s=common.state(self.cid)
        s["production"]={"status":"paused","manual_resume":True}
        common.store(self.cid,s)
        production.touch(self.cid)
        with patch.object(production.threading,"Thread") as thread:
            production.maybe_launch(self.cid)
            thread.assert_not_called()

    def test_pause_at_segment_boundary_preserves_progress(self):
        s=common.state(self.cid);s["production"]={"status":"running","completed_segments":3}
        common.store(self.cid,s)
        with patch.object(production,"present",return_value=False):
            with self.assertRaises(production.Paused):production.checkpoint(self.cid)
        self.assertEqual(common.state(self.cid)["production"]["completed_segments"],3)
        self.assertEqual(common.state(self.cid)["production"]["status"],"paused")


if __name__=="__main__":
    unittest.main()
