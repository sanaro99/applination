"""Conservative native batch routes, verified 2026-10-01.

Unknown models must be reviewed against provider documentation before addition.
Prices are estimates per million ordinary text tokens, not invoices.
"""
ROUTES = {
    'openai': {
        'endpoint': 'https://api.openai.com/v1',
        'source': 'https://developers.openai.com/api/docs/guides/batch',
        'models': ['gpt-6-luna', 'gpt-6-sol', 'gpt-5.6-luna', 'gpt-4.1-mini', 'gpt-4.1'],
        'max_count': 50000, 'max_bytes': 190_000_000,
    },
    'claude': {
        'endpoint': 'https://api.anthropic.com',
        'source': 'https://platform.claude.com/docs/en/build-with-claude/batch-processing',
        'models': ['claude-haiku-4-5', 'claude-sonnet-4-6', 'claude-opus-4-6', 'claude-sonnet-5-5'],
        'max_count': 100000, 'max_bytes': 250_000_000,
    },
    'gemini': {
        'endpoint': 'https://generativelanguage.googleapis.com',
        'source': 'https://ai.google.dev/gemini-api/docs/batch-api',
        'models': ['gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-pro'],
        'max_count': 10000, 'max_bytes': 18_000_000,
    },
}


def validate_batch_route(provider: str, endpoint: str, model: str) -> dict:
    route = ROUTES.get(provider)
    if not route or (endpoint and endpoint.rstrip('/') != route['endpoint']):
        raise ValueError('Discounted batches require a supported native provider endpoint.')
    if model not in route['models']:
        raise ValueError(f'Model {model!r} has not been verified for {provider} batches.')
    return {**route, 'provider': provider, 'model': model, 'discount': .5,
            'verified_at': '2026-10-01',
            'input_per_million': .05 if model == 'gpt-6-luna' else None,
            'output_per_million': .25 if model == 'gpt-6-luna' else None}
