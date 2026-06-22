import asyncio

import pytest

from novel_deconstructor.services.llm_provider import DoubaoResponsesProvider, LLMRequest, OpenAICompatibleProvider, is_doubao_base_url


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


def test_doubao_base_url_and_response_parsing():
    provider = DoubaoResponsesProvider("https://ark.cn-beijing.volces.com/api/v3/responses", "key")

    assert is_doubao_base_url(provider.base_url)
    assert provider.base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert provider.responses_url == "https://ark.cn-beijing.volces.com/api/v3/responses"
    assert (
        provider._extract_response_text(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "第一段正文"},
                            {"type": "output_text", "text": "第二段正文"},
                        ],
                    }
                ]
            }
        )
        == "第一段正文\n第二段正文"
    )


def test_doubao_missing_key_message():
    provider = DoubaoResponsesProvider("https://ark.cn-beijing.volces.com/api/v3", "")

    with pytest.raises(ValueError, match="DOUBAO_API_KEY|ARK_API_KEY"):
        asyncio.run(
            provider.complete(
                LLMRequest(
                    system_prompt="system",
                    user_prompt="user",
                    model="doubao-seed-2-0-pro-260215",
                    temperature=0.3,
                    max_tokens=1000,
                )
            )
        )
