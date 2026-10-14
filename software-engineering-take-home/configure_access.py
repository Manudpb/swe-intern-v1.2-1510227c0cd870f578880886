"""Launch a local coding tool with the supplied Portkey access profile.

Python 3.10+. Run from the extracted packet root. --check prints only non-secret
configuration. The funded key is read from starter-kit/.env or PORTKEY_API_KEY.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone
from time import perf_counter
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent


def settings(profile, tool, directory):
    base = profile['gateway_base_url'].rstrip('/')
    model = profile['models'][tool]
    if not base.startswith('https://') or not base.endswith('/v1') or not model.startswith('@') or '/' not in model:
        raise ValueError('Invalid access profile; contact the coordinator')
    directory = Path(directory).resolve()
    env = {}
    if tool == 'codex':
        # Let the installed Codex recognize its model; select the Portkey provider separately.
        provider, raw_model = model.split('/', 1)
        config = '\n'.join([
            'model_provider = "bain_interview"', 'model = ' + json.dumps(raw_model),
            '[model_providers.bain_interview]', 'name = "Bain interview Portkey"',
            'base_url = ' + json.dumps(base), 'env_key = "PORTKEY_API_KEY"',
            'wire_api = "responses"', 'requires_openai_auth = false',
            '[model_providers.bain_interview.http_headers]',
            '"x-portkey-provider" = ' + json.dumps(provider),
            '[model_providers.bain_interview.env_http_headers]',
            '"x-portkey-api-key" = "PORTKEY_API_KEY"', ''])
        env['CODEX_HOME'] = str(directory / 'codex')
        return env, directory / 'codex/config.toml', config, ['codex']
    if tool == 'claude':
        provider, raw_model = model.split('/', 1)
        env = {'ANTHROPIC_BASE_URL': base[:-3], 'ANTHROPIC_API_KEY': '',
               'ANTHROPIC_MODEL': raw_model, 'ANTHROPIC_DEFAULT_SONNET_MODEL': raw_model,
               'ANTHROPIC_DEFAULT_OPUS_MODEL': raw_model, 'ANTHROPIC_DEFAULT_HAIKU_MODEL': raw_model}
        # Claude settings.env overrides its inherited process environment. Do not
        # load personal/project settings that can replace this packet's gateway
        # and key. Managed organization policy still applies.
        # Auth and routing headers are installed in the subprocess environment only.
        return env, None, None, ['claude', '--setting-sources', '', '--model', raw_model]
    config = {'$schema': 'https://opencode.ai/config.json',
              'provider': {'bain_interview': {'npm': '@ai-sdk/openai-compatible',
                'name': 'Bain interview', 'options': {'baseURL': base, 'apiKey': '{env:PORTKEY_API_KEY}',
                    'headers': {'x-portkey-api-key': '{env:PORTKEY_API_KEY}'}},
                'models': {model: {'name': 'Interview coding model'}}}},
              'model': 'bain_interview/' + model}
    env['OPENCODE_CONFIG'] = str(directory / 'opencode.json')
    return env, directory / 'opencode.json', json.dumps(config, indent=2) + '\n', ['opencode']


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def application_environment(path, environment):
    """Read the shared access variables; environment wins over .env.

    Supports plain or quoted single-line values, not shell expansion/execution.
    """
    values = {}
    fields = {'PORTKEY_API_KEY', 'PORTKEY_BASE_URL', 'LLM_MODEL'}
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            name, separator, value = line.strip().partition('=')
            name = name.strip()
            if not separator or name not in fields:
                continue
            value = value.strip()
            if value.startswith(('"', "'")):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError('Use single-line matched quotes in the application .env')
                value = value[1:-1]
            if '$' in value or '`' in value:
                raise ValueError('Use literal application settings in .env; expansion is not supported')
            values[name] = value
    values.update({name: environment[name] for name in fields if name in environment})
    return values


def check_application(profile, environment, opener=None):
    if profile['mode'] != 'live':
        raise ValueError('This packet has no funded access; request your funded packet')
    expiry = datetime.fromisoformat(profile['expires_at'].replace('Z', '+00:00'))
    if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
        raise ValueError('The access profile has expired or lacks a timezone; contact support')
    base = profile['gateway_base_url'].rstrip('/')
    parsed = urllib.parse.urlsplit(base)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not parsed.path.endswith('/v1')):
        raise ValueError('Invalid HTTPS gateway in access profile; contact support')
    model = profile['models']['application']
    if not isinstance(model, str) or not model.startswith('@') or '/' not in model or any(c.isspace() for c in model):
        raise ValueError('Invalid application route in access profile; contact support')
    if environment.get('PORTKEY_BASE_URL', base).rstrip('/') != base or environment.get('LLM_MODEL', model) != model:
        raise ValueError('PORTKEY_BASE_URL and LLM_MODEL must match ACCESS.json for the supplied-key check')
    key = environment.get('PORTKEY_API_KEY', '')
    if not key or any(c.isspace() for c in key):
        raise ValueError('PORTKEY_API_KEY is missing or invalid in starter-kit/.env; contact the coordinator')
    model_id = model.rsplit('/', 1)[-1].lower()
    reasoning_model = model_id.startswith(('gpt-5', 'o1', 'o3', 'o4'))
    token_limit = {'max_completion_tokens': 128} if reasoning_model else {'max_tokens': 16}
    body = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': 'Reply with OK.'}],
                       **token_limit}).encode('utf-8')
    request = urllib.request.Request(base + '/chat/completions', data=body, method='POST',
              headers={'Authorization': 'Bearer ' + key, 'x-portkey-api-key': key,
                       'Content-Type': 'application/json', 'User-Agent': 'swe-interview-setup/1.2'})
    opener = opener or urllib.request.build_opener(NoRedirect())
    started = perf_counter()
    try:
        with opener.open(request, timeout=45) as response:
            payload = json.loads(response.read(65536))
        content = payload['choices'][0]['message']['content']
        if not isinstance(content, str) or not content.strip():
            raise ValueError('empty completion')
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        if status in (401, 403):
            message = 'Authentication or route access denied; check your supplied key and contact support'
        elif status == 429:
            message = 'Rate limit or allowance exhausted; pause and contact support; no automatic retry'
        else:
            message = 'Gateway request failed; share the HTTP status and packet ID with support'
        raise ValueError(f'{message} (HTTP {status})') from None
    except (urllib.error.URLError, OSError):
        raise ValueError('Cannot reach the gateway (network, TLS or timeout); contact support; TLS verification remains enabled') from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise ValueError('Gateway returned no usable completion; contact support') from None
    return {'status': 'ok', 'elapsed_ms': round((perf_counter() - started) * 1000),
            'check': 'One small application completion; Docker forwarding, vision and tools still need application tests'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool', choices=['codex', 'claude', 'opencode', 'application-check'])
    parser.add_argument('--profile', type=Path, default=ROOT / 'ACCESS.json')
    parser.add_argument('--env-file', type=Path, default=ROOT / 'starter-kit/.env')
    parser.add_argument('--check', action='store_true', help='Validate and display non-secret configuration without launching')
    args = parser.parse_args()
    try:
        profile = json.loads(args.profile.read_text(encoding='utf-8-sig'))
        if args.tool == 'application-check':
            if args.check:
                raise ValueError('--check is for coding-tool configuration; application-check makes one small paid request')
            print(json.dumps(check_application(profile, application_environment(args.env_file, os.environ)), indent=2))
            return
        env, target, content, command = settings(profile, args.tool, ROOT / '.interview-tools')
        if args.check:
            print(json.dumps({'mode': profile['mode'], 'tool': args.tool, 'model': profile['models'][args.tool],
                              'gateway': profile['gateway_base_url'], 'config': content,
                              'environment': env, 'command': command}, indent=2))
            return
        if profile['mode'] != 'live':
            raise ValueError('This packet has no funded access. Ask the coordinator for your funded packet.')
        access_env = application_environment(args.env_file, os.environ)
        key = access_env.get('PORTKEY_API_KEY')
        if not key or any(c.isspace() for c in key):
            raise ValueError('PORTKEY_API_KEY is missing or invalid in the supplied .env; contact the coordinator')
        executable = shutil.which(command[0])
        if not executable:
            raise ValueError(f'Install {command[0]} first, or contact the coordinator for setup help')
        if target:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
        child_env = os.environ.copy()
        child_env.update(access_env)
        # Keep unrelated provider credentials from masking interview access failures.
        for variable in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN',
                         'ANTHROPIC_CUSTOM_HEADERS', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX',
                         'CLAUDE_CODE_USE_FOUNDRY', 'OPENAI_BASE_URL'):
            child_env.pop(variable, None)
        child_env.update(env)
        if args.tool == 'claude':
            child_env['ANTHROPIC_AUTH_TOKEN'] = key
            child_env['ANTHROPIC_CUSTOM_HEADERS'] = ('x-portkey-api-key: ' + key + '\nx-portkey-provider: ' + profile['models']['claude'].split('/', 1)[0])
        raise SystemExit(subprocess.call([executable, *command[1:]], env=child_env))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f'Access setup: {exc}\n')


if __name__ == '__main__':
    main()
