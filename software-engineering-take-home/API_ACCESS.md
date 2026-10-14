# Funded API and coding-tool access

Bain supplies one candidate-specific **Portkey API key** for your application and local coding assistant. Your funded packet already includes it in `starter-kit/.env`, together with the gateway and application model. `ACCESS.json` contains the approved model routes, total allowance and expiry. There is no key to copy from your invitation or enter in a terminal. Do not purchase access yourself. Ask the invitation sender if either file is missing.

`budget_usd` in `ACCESS.json` describes your allowance. The actual limit is attached to your key in Portkey; editing the file does not change it. The allowance is shared across application requests, evaluation and coding tools. Use the key with the supplied gateway URL: it is not a native OpenAI or Anthropic credential. A commercial editor subscription is not included; the local tools below are supported alternatives.

## Coding assistant

Install your preferred local tool and Python 3.10+. From the extracted packet root, run one of:

```sh
python configure_access.py codex
python configure_access.py claude
python configure_access.py opencode
```

The launcher reads the key from `starter-kit/.env` and your approved route from `ACCESS.json`, then passes the settings to the tool. Codex gets an isolated configuration directory; Claude uses the Anthropic-compatible gateway endpoint and skips personal/project settings for this session so they cannot replace the supplied access; OpenCode gets a custom OpenAI-compatible provider. Claude's managed organization policies still apply. Generated files live in the ignored `.interview-tools/` directory. Your application uses the same `.env`, as described below.

An explicitly set `PORTKEY_API_KEY` in your terminal overrides the file. To read a different file, add `--env-file PATH` to the launcher command.

Use `python configure_access.py codex --check` (or the other tool name) to inspect non-secret settings without launching or spending credit. This is a configuration check, not a successful model request.

Make one short request after launch and confirm the selected model matches `ACCESS.json`. If existing tool settings or a personal subscription take precedence, contact support before proceeding. The launcher cannot guarantee compatibility with every installed tool version or organization policy.

Manual references: [Codex custom providers](https://learn.chatgpt.com/docs/config-file/config-advanced), [Claude Code through Portkey](https://portkey.ai/docs/integrations/libraries/claude-code-anthropic), [OpenCode through Portkey](https://portkey.ai/docs/integrations/libraries/opencode). Other harnesses are allowed if they support the supplied gateway and model; contact us for setup help.

## Application

`starter-kit/.env` is ready to use: `PORTKEY_API_KEY` holds your key, `PORTKEY_BASE_URL` the gateway and `LLM_MODEL` the application route. Your backend must receive these settings through Compose `environment` or `env_file`. For example, add `env_file: .env` to your backend service in `starter-kit/docker-compose.yml`. Compose does not automatically pass every value in `.env` into a container.

To verify application access, run from the packet root:

```sh
python configure_access.py application-check
```

This standard-library check reads `ACCESS.json`, then `starter-kit/.env` and terminal environment overrides. It sends **one small paid Chat Completions request** with the application route, a 16-token output limit and a 45-second timeout, with no retries. It checks authentication and a usable text completion; it does not validate Docker environment forwarding, image inputs or tool calls. It prints no credential or model response. Use literal single-line values in `.env` (optionally quoted); shell expansion is not supported. Match `PORTKEY_BASE_URL` and `LLM_MODEL` to the profile. Python's standard TLS verification stays enabled.

`make setup` runs this check before starting containers. Run `make check-access` to repeat only the check; override `PYTHON=python3` if needed. Without Make, run the command above before the Docker startup command in README.md. If you deliberately use a permitted local model or another provider, use `make setup CHECK_PORTKEY=0`, document the choice, and provide an equivalent readiness check. Skipping is never reported as successful Portkey access.

For your application, use the OpenAI-compatible SDK with `PORTKEY_BASE_URL` as `base_url`, the key as `api_key` and in `x-portkey-api-key`, and the full `@provider/model` route as `model`. Implement image inputs and actual tools yourself. For an Anthropic SDK integration, use the gateway root **without /v1**, the unprefixed Claude model ID and the supplied provider route in `x-portkey-provider`. Ask support if unsure which interface your approved model supports.

Use local embeddings for the pilot so retrieval does not require another paid credential. Document the embedding model and first-run download. An approved hosted embedding route may be used if the coordinator explicitly supplies it.

## Access failures and cleanup

- `401/403`: confirm the key, gateway and approved route. Share only a redacted error and packet ID with support.
- `429` or exhausted budget: pause and contact support. Do not buy replacement credit or loop on retries.
- Container cannot see the key: check backend environment forwarding without printing the value.
- TLS/certificate error: contact support; do not disable certificate validation.

Access failures are not engineering assessment failures. Ask for an adjusted deadline if needed. Before submitting, remove `.env`, credentials and `.interview-tools/`; retain `PACKET.json`. Bain ends the key's access at the stated expiry or earlier after agreed completion.
