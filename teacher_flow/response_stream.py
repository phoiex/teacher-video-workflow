"""Keep the converted Responses stream usable by a stateful tool runner."""
from collections import Counter
import time


def usable_output(items):
    for item in items or []:
        kind = item.get('type')
        if kind in ('function_call', 'custom_tool_call', 'computer_call', 'image_generation_call'):
            return True
        if kind == 'message' and any(
            (part.get('text') or part.get('refusal') or '').strip()
            for part in item.get('content') or []
        ):
            return True
    return False


class ResponseStream:
    def __init__(self, source):
        self.source = source
        self.counts = Counter()
        self.reasoning_chars = 0
        self.text_chars = 0
        self.tool_calls = 0
        self.last_event_at = None
        self.upstream_status = None
        self.upstream_finish_reason = None
        self.failure_code = None
        self.fixed_reasoning_starts = 0
        self.preserved_signatures = 0

    def normalize(self, event):
        data = event.model_dump(mode='json', exclude_none=True) if hasattr(event, 'model_dump') else event
        data = dict(data)
        kind = data.get('type', '')
        self.last_event_at = time.time()
        self.counts[kind] += 1
        if kind == 'response.reasoning_summary_text.delta':
            self.reasoning_chars += len(data.get('delta') or '')
        elif kind == 'response.output_text.delta':
            self.text_chars += len(data.get('delta') or '')
        item = data.get('item')
        if isinstance(item, dict) and item.get('type') == 'reasoning':
            item = dict(item)
            data['item'] = item
            if item.get('summary') is None:
                item['summary'] = []
                self.fixed_reasoning_starts += 1
            if kind == 'response.output_item.done' and not item.get('encrypted_content'):
                # LiteLLM puts signed provider continuation data in response.completed,
                # while Codex persists output_item.done. Preserve it at that boundary.
                build = getattr(self.source, 'create_litellm_model_response', None)
                if build:
                    reply = build()
                    choices = getattr(reply, 'choices', None) or []
                    message = getattr(choices[0], 'message', None) if choices else None
                    blocks = getattr(message, 'thinking_blocks', None) or []
                    if blocks:
                        from litellm.responses.litellm_completion_transformation.reasoning_items import encode_thinking_blocks
                        signed = encode_thinking_blocks(blocks)
                        if signed:
                            item['encrypted_content'] = signed
                            self.preserved_signatures += 1
        if kind == 'response.output_item.done' and (item or {}).get('type') in ('function_call', 'custom_tool_call'):
            self.tool_calls += 1
        if kind in ('response.completed', 'response.failed', 'response.incomplete'):
            reply = dict(data.get('response') or {})
            self.upstream_status = reply.get('status', kind.removeprefix('response.'))
            model_reply = getattr(self.source, 'litellm_model_response', None)
            choices = getattr(model_reply, 'choices', None) or []
            if choices:
                self.upstream_finish_reason = getattr(choices[0], 'finish_reason', None)
            if kind == 'response.completed' and not usable_output(reply.get('output')):
                self.failure_code = 'empty_model_output'
                message = '模型响应已结束，但没有返回正文或工具调用。'
            elif kind == 'response.incomplete' and (reply.get('incomplete_details') or {}).get('reason') == 'max_output_tokens':
                self.failure_code = 'provider_output_limit'
                message = '服务商结束了本次输出，结果尚未完成。'
            else:
                message = None
            if message:
                # A completed empty result or known output boundary is not a dropped
                # connection. Report a terminal failure so the harness does not replay it.
                reply.update(status='failed', error={'code': self.failure_code,
                    'message': f'[course-model:{self.failure_code}] '+message})
                data.update(type='response.failed', response=reply)
        return data

    def snapshot(self):
        return {'event_counts': dict(self.counts), 'reasoning_chars': self.reasoning_chars,
                'text_chars': self.text_chars, 'tool_calls': self.tool_calls,
                'last_event_at': self.last_event_at, 'upstream_status': self.upstream_status,
                'upstream_finish_reason': self.upstream_finish_reason, 'failure_code': self.failure_code,
                'fixed_reasoning_starts': self.fixed_reasoning_starts,
                'preserved_signatures': self.preserved_signatures}
