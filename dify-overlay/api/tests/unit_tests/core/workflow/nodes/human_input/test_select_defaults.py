"""Review forms retain resolved choices and identify genuinely required fields."""

from unittest.mock import Mock

import pytest

from core.workflow.nodes.human_input.entities import (
    HumanInputSubmissionValidationError,
    ParagraphInputConfig,
    SelectInputConfig,
    UserActionConfig,
    validate_human_input_submission,
)
from graphon.variables.segments import StringSegment


def test_select_resolves_saved_choice_and_registers_both_variable_dependencies():
    field = SelectInputConfig.model_validate({
        "output_variable_name": "style_preset",
        "label": "画面风格",
        "default": {"type": "variable", "selector": ["requirements_data", "style_preset"]},
        "option_source": {"type": "variable", "selector": ["styles", "options"]},
    })
    pool = Mock()
    pool.get.return_value = StringSegment(value="空间代码动画")
    assert field.resolve_default_value(pool).to_object() == "空间代码动画"
    pool.get.assert_called_once_with(["requirements_data", "style_preset"])
    assert field.extract_variable_selectors() == [["styles", "options"], ["requirements_data", "style_preset"]]
    assert SelectInputConfig.model_validate_json(field.model_dump_json()).label == "画面风格"


@pytest.mark.parametrize("default", [None, {"type": "constant", "value": "暖色图解"}])
def test_select_without_variable_default_never_reads_pool(default):
    field = SelectInputConfig.model_validate({
        "output_variable_name": "style_preset", "default": default,
        "option_source": {"type": "constant", "value": ["暖色图解"]},
    })
    pool = Mock()
    assert field.resolve_default_value(pool) is None
    assert field.extract_variable_selectors() == []
    pool.get.assert_not_called()


def test_blank_optional_feedback_is_accepted_but_blank_required_topic_is_rejected():
    fields = [
        ParagraphInputConfig(output_variable_name="topic", label="主题", required=True),
        ParagraphInputConfig(output_variable_name="feedback"),
    ]
    args = {"inputs": fields, "user_actions": [UserActionConfig(id="approve", title="确认")], "selected_action_id": "approve"}
    validate_human_input_submission(**args, form_data={"topic": "注意力机制", "feedback": ""})
    with pytest.raises(HumanInputSubmissionValidationError, match="主题"):
        validate_human_input_submission(**args, form_data={"topic": "  ", "feedback": ""})
