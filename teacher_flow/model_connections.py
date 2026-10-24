"""Provider credentials and model metadata, separate from workflow roles."""
import os

PROVIDERS = {'openai', 'deepseek', 'anthropic', 'custom'}
PROTOCOLS = {'responses', 'chat.completions', 'messages'}
MODEL_PRESETS = {}
DEFAULT_URLS = {'openai': 'https://api.openai.com/v1', 'deepseek': 'https://api.deepseek.com',
                'anthropic': 'https://api.anthropic.com'}


def route(profile):
    return dict(profile)


def connection(profile, runtime=None):
    provider = profile['provider']
    if provider not in PROVIDERS:
        raise ValueError('模型服务商尚未配置。')
    prefix = provider.upper()
    key = os.environ.get(prefix + '_API_KEY', '').strip()
    base = os.environ.get(prefix + '_BASE_URL', DEFAULT_URLS.get(provider, '')).strip()
    if not key or not base:
        raise ValueError(f'请在 .env 中配置 {prefix}_API_KEY 和 {prefix}_BASE_URL。')
    from urllib.parse import urlsplit
    parsed = urlsplit(base)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('模型 API 地址格式不正确。')
    return {'base_url': base, 'api_key': key}


def adapter_provider(profile):
    if profile['protocol'] == 'messages': return 'anthropic'
    if profile['provider'] == 'deepseek': return 'deepseek'
    return 'openai'


def catalog_info(profile, catalog):
    profile = route(profile)
    provider = adapter_provider(profile)
    native = profile.get('catalog_model', profile['model'])
    info = catalog.get(provider+'/'+native)
    if info is None:
        candidate = catalog.get(native)
        if candidate and (candidate.get('litellm_provider') == provider or profile.get('catalog_model')):
            info = candidate
    return dict(info or {})


def output_policy(profile, catalog, requested=None):
    info = catalog_info(profile, catalog)
    maximum = info.get('max_output_tokens') or info.get('max_tokens')
    if profile['protocol'] == 'messages' and not maximum and requested is None:
        raise ValueError('这个Messages模型需要输出上限，请用catalog_model关联它的模型资料。')
    return {'source': 'caller' if requested is not None else 'model_metadata' if profile['protocol'] == 'messages' else 'provider_default',
            'max_output_tokens': requested if requested is not None else maximum if profile['protocol'] == 'messages' else None,
            'context_window': info.get('max_input_tokens')}
