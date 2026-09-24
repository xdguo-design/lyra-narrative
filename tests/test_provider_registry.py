import unittest

from app.ai.providers.base import ProviderConfig, ProviderError
from app.ai.providers.registry import DEFAULT_REGISTRY, build_provider


class ProviderRegistryTests(unittest.TestCase):
    def test_direct_and_gateway_modes_are_registered(self):
        kinds = set(DEFAULT_REGISTRY.kinds)
        self.assertTrue(
            {
                "openai",
                "openai-compatible",
                "deepseek",
                "gemini",
                "anthropic",
                "ollama",
                "vllm",
                "freellm-gateway",
            }.issubset(kinds)
        )

    def test_gateway_is_optional_peer_provider(self):
        direct = build_provider(
            ProviderConfig(name="direct", kind="openai", default_model="model")
        )
        gateway = build_provider(
            ProviderConfig(
                name="gateway",
                kind="freellm-gateway",
                base_url="https://example.invalid/v1",
                default_model="model",
            )
        )
        self.assertEqual(type(direct), type(gateway))

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(ProviderError):
            build_provider(ProviderConfig(name="bad", kind="does-not-exist"))


if __name__ == "__main__":
    unittest.main()
