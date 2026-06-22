import asyncio

import pytest

from novel_deconstructor.services.llm_provider import LLMRequest, OpenAICompatibleProvider


def test_dry_run_provider_returns_markdown():
    provider = OpenAICompatibleProvider("https://example.com/v1", "")
    result = asyncio.run(
        provider.complete(
            LLMRequest(
                system_prompt="system",
                user_prompt="user",
                model="",
                temperature=0.3,
                max_tokens=1000,
                dry_run=True,
            )
        )
    )

    assert "# Dry-run" in result
    assert "不输出原文" in result


def test_deepseek_base_url_normalization():
    provider = OpenAICompatibleProvider("https://api.deepseek.com/v1", "key")

    assert provider.base_url == "https://api.deepseek.com"
    assert provider.chat_completions_url == "https://api.deepseek.com/chat/completions"


def test_deepseek_models_are_not_rewritten_in_dry_run():
    provider = OpenAICompatibleProvider("https://api.deepseek.com", "")

    for model in ("deepseek-v4-flash", "deepseek-v4-pro"):
        result = asyncio.run(
            provider.complete(
                LLMRequest(
                    system_prompt="system",
                    user_prompt="user",
                    model=model,
                    temperature=0.3,
                    max_tokens=1000,
                    dry_run=True,
                )
            )
        )
        assert "# Dry-run" in result


def test_deepseek_missing_key_message():
    provider = OpenAICompatibleProvider("https://api.deepseek.com", "")

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        asyncio.run(
            provider.complete(
                LLMRequest(
                    system_prompt="system",
                    user_prompt="user",
                    model="deepseek-v4-flash",
                    temperature=0.3,
                    max_tokens=1000,
                )
            )
        )
