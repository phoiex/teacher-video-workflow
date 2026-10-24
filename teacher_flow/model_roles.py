"""每节课保存模型分工，凭据与流程配置分开存放。"""
from contextvars import ContextVar
import copy
import json
import os
from .common import TOOL, load
from .model_connections import MODEL_PRESETS, PROVIDERS, PROTOCOLS

CURRENT = ContextVar('course_model_roles', default=None)
DEFAULT_MODEL_ROLES = {
    role: {'provider': 'deepseek', 'model': 'deepseek-flash',
           'protocol': 'responses', 'reasoning_effort': 'max'}
    for role in ('planner', 'writer', 'editor', 'producer')
}


def default_roles():
    from pathlib import Path
    path = Path(os.environ.get('TEACHER_MODELS_FILE', str(TOOL / 'models.json'))).expanduser()
    return validate(load(path) if path.exists() else DEFAULT_MODEL_ROLES)


def validate(value):
    if value is None or value == '':
        return None
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict) or set(value) != set(DEFAULT_MODEL_ROLES):
        raise ValueError('模型分工需包含planner、writer、editor和producer。')
    for role, config in value.items():
        if not isinstance(config, dict) or set(config) - {'provider','model','protocol','reasoning_effort','catalog_model'}:
            raise ValueError('模型配置字段不正确。')
        model, protocol = config.get('model',''), config.get('protocol')
        if config.get('provider') not in PROVIDERS or not isinstance(model,str) or not model:
            raise ValueError('模型服务商或名称配置不正确。')
        preset = MODEL_PRESETS.get((config['provider'], model))
        if protocol not in PROTOCOLS or preset and protocol != preset['protocol'] or not all(c.isalnum() or c in '-._:/' for c in model):
            raise ValueError('模型名称与调用协议不匹配。')
        if config.get('reasoning_effort') not in (None,'none','minimal','low','medium','high','xhigh','max'):
            raise ValueError('思考强度不正确。')
        if 'catalog_model' in config and (not isinstance(config['catalog_model'],str) or not config['catalog_model']):
            raise ValueError('模型资料名称不正确。')
    return copy.deepcopy(value)


def for_stage(stage):
    roles = CURRENT.get() or default_roles()
    role = ('planner' if 'plan' in stage else
            'editor' if 'deslop' in stage else
            'writer' if 'script' in stage else
            'producer' if 'storyboard' in stage else 'planner')
    return roles[role]

