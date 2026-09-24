# Model Providers

Novel Workbench must remain usable as an open-source project without requiring
freellm-gateway. The runtime talks only to a provider abstraction; gateway,
vendor APIs, and local models are peer choices.

## Supported provider kinds

| kind | mode | default endpoint |
| --- | --- | --- |
| `openai` | direct | `https://api.openai.com/v1` |
| `openai-compatible` | direct/custom | configured by user |
| `deepseek` | direct/custom | configured by user |
| `gemini` | native direct | Google Generative Language API |
| `anthropic` | native direct | Anthropic Messages API |
| `ollama` | local | `http://127.0.0.1:11434` |
| `vllm` | local/remote | OpenAI-compatible endpoint |
| `freellm-gateway` | optional gateway | configured by user |

## Design rule

Agents and Task DAG nodes must never import vendor SDKs directly.

```text
Agent / Task
    |
    v
BaseProvider
    |
    +-- GeminiProvider
    +-- AnthropicProvider
    +-- OpenAICompatibleProvider
    |      +-- OpenAI
    |      +-- DeepSeek
    |      +-- vLLM
    |      +-- freellm-gateway
    |
    +-- OllamaProvider
```

freellm-gateway can provide centralized routing, quotas, failover, accounting,
and model aliases, but it is not a required dependency.

## Python example

```python
from app.ai import ChatMessage, ChatRequest, ProviderConfig, build_provider

provider = build_provider(
    ProviderConfig(
        name="writer",
        kind="gemini",
        api_key_env="GEMINI_API_KEY",
        default_model="your-gemini-model",
    )
)

response = await provider.chat(
    ChatRequest(
        system="You are the prose writer for a long-form novel.",
        messages=[ChatMessage(role="user", content="Continue chapter 12.")],
    )
)
```

## OpenAI-compatible / gateway example

```python
provider = build_provider(
    ProviderConfig(
        name="reviewer",
        kind="freellm-gateway",
        base_url="https://gateway.example.com/v1",
        api_key_env="FREELLM_GATEWAY_API_KEY",
        default_model="review-model",
    )
)
```

The same code works for a standalone OpenAI-compatible endpoint by changing
`kind`, `base_url`, and the selected environment variable.

## Secrets

Only environment-variable names belong in project configuration. Never persist
API key values in the database, workspace files, task snapshots, or Git.
