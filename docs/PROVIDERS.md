# Provider Profiles

Lyra Narrative treats a **Provider as a user-defined runtime instance**, not as
a vendor name.

Examples of valid Provider names:

- 主写作
- 科学审稿
- 国内备用
- 夜间批处理

The name is chosen by the user. Vendor names such as OpenAI, Kimi, GLM, Claude
or Gemini are not reserved Provider identities.

## Provider data model

A Provider profile contains:

| field | meaning |
| --- | --- |
| `name` | user-defined instance name |
| `protocol` | optional wire protocol / adapter |
| `base_url` | endpoint used by the selected protocol |
| `api_key_env` | environment-variable name containing the secret |
| `default_model` | model ID used by this instance |
| `enabled` | whether the instance can be used |
| `is_default` | default runtime instance |
| `options` | protocol-specific options |

The protocol may be left empty while a Provider is being created. An instance
without a protocol is saved as configuration only and is never selected by the
runtime.

A Provider can become the default only after both protocol and default model are
configured.

## Supported protocols

| protocol | adapter |
| --- | --- |
| `openai-compatible` | OpenAI-compatible Chat Completions |
| `anthropic` | Anthropic Messages |
| `gemini` | Gemini GenerateContent |
| `ollama` | Ollama Chat |

Kimi, GLM, DeepSeek, Qwen-compatible services, vLLM and compatible gateways are
normally configured as **named Provider instances using the
`openai-compatible` protocol**.

For example, these are two different Provider profiles even though they use the
same protocol:

```text
主写作
  protocol: openai-compatible
  base_url: https://api.moonshot.cn/v1
  model: <model id>
  api_key_env: KIMI_API_KEY

科学审稿
  protocol: openai-compatible
  base_url: https://open.bigmodel.cn/api/paas/v4
  model: <model id>
  api_key_env: GLM_API_KEY
```

The runtime records the user-defined Provider name in AgentRun provenance.

## Secrets

Never store API key values in Provider profiles.

Only the environment-variable name is persisted:

```text
api_key_env = KIMI_API_KEY
```

The actual value remains in the deployment environment, secret manager or
GitHub Actions Secret.

## GitHub Actions

The full-book workflow uses the same separation:

```text
NARRATIVE_PROVIDER_NAME
NARRATIVE_PROVIDER_PROTOCOL
NARRATIVE_PROVIDER_MODEL
NARRATIVE_PROVIDER_BASE_URL
NARRATIVE_PROVIDER_SECRET_NAME
```

`NARRATIVE_PROVIDER_NAME` is arbitrary. It can be `主写作` or any name the
user wants.

`NARRATIVE_PROVIDER_PROTOCOL` selects the adapter. The workflow resolves the
configured Secret into a runtime-only environment value; the key itself is
never committed.
