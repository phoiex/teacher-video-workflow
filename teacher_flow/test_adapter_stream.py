"""Replay provider chunks through the installed conversion code, without a model call."""
import unittest
from .response_stream import ResponseStream
import importlib.util
if importlib.util.find_spec("litellm") is None:
    raise unittest.SkipTest("安装 requirements-adapter.txt 后检查协议适配。")

from litellm.responses.litellm_completion_transformation.streaming_iterator import (
    LiteLLMCompletionStreamingIterator,
)
from litellm.types.utils import ModelResponseStream


class Chunks:
    logging_obj = None

    def __init__(self, rows):
        self.rows = iter(rows)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.rows)
        except StopIteration:
            raise StopAsyncIteration


async def replay(*, signed=False, normalize=True):
    # All text is synthetic; no actual model reasoning is recorded here.
    rows = [
        ({'role': 'assistant'}, None),
        ({'reasoning_content': 'Fixture summary.'}, None),
        ({'tool_calls': [{'index': 0, 'id': 'call_fixture', 'type': 'function',
                         'function': {'name': 'probe_save', 'arguments': ''}}]}, None),
        ({'tool_calls': [{'index': 0, 'function': {'arguments': '{"ok":true}'}}]}, None),
        ({}, 'tool_calls'),
    ]
    if signed:
        rows[1][0]['thinking_blocks'] = [{'type': 'thinking', 'thinking': 'Fixture summary.'}]
        rows.insert(2, ({'thinking_blocks': [{'type': 'thinking', 'thinking': '', 'signature': 'fixture-signature'}]}, None))
    stream = LiteLLMCompletionStreamingIterator(
        'claude-opus-5-5',
        Chunks([ModelResponseStream(id='resp_fixture', model='claude-opus-5-5',
                choices=[{'index': 0, 'delta': delta, 'finish_reason': finish}])
                for delta, finish in rows]),
        'fixture', {}, custom_llm_provider='anthropic')
    result = []
    bridge = ResponseStream(stream)
    async for event in stream:
        data = bridge.normalize(event) if normalize else event.model_dump(mode='json', exclude_none=True)
        result.append(data)
    return result


class AdapterStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixture_exposes_upstream_missing_fields(self):
        events = await replay(signed=True, normalize=False)
        reasoning = [e['item'] for e in events if e['type'] == 'response.output_item.added'
                     and e['item']['type'] == 'reasoning']
        self.assertNotIn('summary', reasoning[0])
    async def test_reasoning_start_is_parseable_before_deltas(self):
        events = await replay()
        active = {}
        for event in events:
            if event['type'] == 'response.output_item.added':
                item = event['item']
                if item['type'] == 'reasoning':
                    self.assertIsInstance(item.get('summary'), list,
                        'Codex cannot activate a reasoning item without its summary array')
                active[item['id']] = item['type']
            if event['type'] == 'response.reasoning_summary_text.delta':
                self.assertEqual(active.get(event['item_id']), 'reasoning')

    async def test_tool_call_survives_reasoning_transition(self):
        events = await replay()
        calls = [e['item'] for e in events if e['type'] == 'response.output_item.done'
                 and e['item']['type'] == 'function_call']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['name'], 'probe_save')
        self.assertEqual(calls[0]['arguments'], '{"ok":true}')

    async def test_streamed_reasoning_keeps_its_resume_signature(self):
        events = await replay(signed=True)
        done = next(e['item'] for e in events if e['type'] == 'response.output_item.done'
                    and e['item']['type'] == 'reasoning')
        final = next(item for item in events[-1]['response']['output'] if item['type'] == 'reasoning')
        self.assertTrue(final.get('encrypted_content'), 'Fixture must contain signed provider continuation data')
        self.assertEqual(done.get('encrypted_content'), final['encrypted_content'],
                         'Codex saves item.done, so a terminal-only signature is lost on the next request')

    async def test_empty_completed_output_is_not_misreported_as_success(self):
        bridge = ResponseStream(None)
        original = {'id': 'empty', 'status': 'completed', 'output': [
            {'type': 'reasoning', 'id': 'rs_fixture', 'summary': []}], 'usage': {'output_tokens': 100}}
        result = bridge.normalize({'type': 'response.completed', 'response': original})
        self.assertEqual(result['type'], 'response.failed')
        self.assertEqual(result['response']['error']['code'], 'empty_model_output')
        self.assertEqual(result['response']['usage'], original['usage'])
        self.assertEqual(bridge.snapshot()['upstream_status'], 'completed')
        self.assertEqual(original['status'], 'completed')

    async def test_output_budget_is_terminal_instead_of_a_reconnect(self):
        bridge = ResponseStream(None)
        result = bridge.normalize({'type': 'response.incomplete', 'response': {'status': 'incomplete',
            'incomplete_details': {'reason': 'max_output_tokens'}}})
        self.assertEqual(result['type'], 'response.failed')
        self.assertEqual(result['response']['error']['code'], 'provider_output_limit')

    async def test_native_fields_and_text_responses_are_unchanged(self):
        bridge = ResponseStream(None)
        event = {'type': 'response.output_item.done', 'item': {'type': 'reasoning', 'summary': [],
            'encrypted_content': 'opaque-native-value'}}
        self.assertEqual(bridge.normalize(event), event)
        event = {'type': 'response.completed', 'response': {'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Done.'}]}]}}
        self.assertEqual(bridge.normalize(event), event)


if __name__ == '__main__':
    unittest.main()
