from __future__ import annotations

from dataclasses import dataclass
import asyncio
from urllib.parse import urlparse

import httpx


@dataclass
class LLMRequest:
    system_prompt: str
    user_prompt: str
    model: str
    temperature: float
    max_tokens: int
    timeout_seconds: int = 120
    retry_count: int = 2
    dry_run: bool = False


class LLMProvider:
    async def complete(self, request: LLMRequest) -> str:
        raise NotImplementedError


def is_deepseek_base_url(base_url: str | None) -> bool:
    if not base_url:
        return False
    candidate = base_url.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    return parsed.netloc.lower() == "api.deepseek.com"


def is_doubao_base_url(base_url: str | None) -> bool:
    if not base_url:
        return False
    candidate = base_url.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    return parsed.netloc.lower().endswith("volces.com") and "/api/v3" in parsed.path


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str):
        self.base_url = self._normalize_base_url(base_url)
        self.api_key = (api_key or "").strip()

    async def complete(self, request: LLMRequest) -> str:
        if request.dry_run:
            return self._dry_run_response(request)
        if not self.api_key:
            raise ValueError(self._missing_api_key_message())
        if not request.model:
            raise ValueError("缺少模型名称。请在 .env 或任务配置中填写 model。")

        payload = {
            "model": request.model,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_error: Exception | None = None
        for attempt in range(request.retry_count + 1):
            try:
                async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                    response = await client.post(self.chat_completions_url, json=payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                    choice = data["choices"][0]
                    message = choice.get("message") or {}
                    content = message.get("content") or choice.get("text")
                    if not content:
                        if message.get("reasoning_content"):
                            raise ValueError("LLM 返回正文为空，只返回 reasoning_content。请调大 max_tokens 后重试。")
                        raise ValueError("LLM 返回为空")
                    return content
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:800]
                last_error = RuntimeError(f"{exc.response.status_code} {exc.response.reason_phrase}: {detail}")
                if attempt < request.retry_count:
                    await asyncio.sleep(1.5 * (attempt + 1))
            except Exception as exc:  # noqa: BLE001 - persisted into JobLog for diagnosis.
                last_error = exc
                if attempt < request.retry_count:
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"LLM 调用失败: {last_error}") from last_error

    @property
    def chat_completions_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        cleaned = (base_url or "").strip().rstrip("/")
        if cleaned and "://" not in cleaned:
            cleaned = f"https://{cleaned}"
        if is_deepseek_base_url(cleaned) and cleaned.endswith("/v1"):
            return cleaned.removesuffix("/v1").rstrip("/")
        return cleaned

    def _missing_api_key_message(self) -> str:
        if is_deepseek_base_url(self.base_url):
            return "缺少 DeepSeek API Key。请在任务配置中填写 API Key，或设置 DEEPSEEK_API_KEY，或开启 dry-run。"
        return "缺少 API Key。请在任务配置中填写 API Key，或设置 OPENAI_API_KEY，或开启 dry-run。"

    def _dry_run_response(self, request: LLMRequest) -> str:
        return """# Dry-run 章节结构分析

## 1. 一句话结构功能

这是 dry-run 结果，系统没有调用外部模型。它用于验证上传、章节切分、Prompt 渲染、后台任务、oh-story 兼容目录和 Markdown 输出链路。

## 2. 开头状态

- 主角状态：待模型分析。
- 关键关系：待模型分析。
- 主要矛盾：待模型分析。
- 读者期待：待模型分析。

## 3. 结尾状态

- 主角状态变化：待模型分析。
- 关系变化：待模型分析。
- 新目标/新危机：待模型分析。
- 章尾钩子：待模型分析。

## 4. 状态变化表

| 维度 | 内容 |
|---|---|
| 获得 | 待模型分析 |
| 失去 | 待模型分析 |
| 知道 | 待模型分析 |
| 误解 | 待模型分析 |
| 关系变化 | 待模型分析 |
| 地位/能力变化 | 待模型分析 |

## 5. 冲突与推进

待模型分析。

## 6. 信息投放

待模型分析。

## 7. 爽点循环拆解

| 层级 | 本章表现 | 说明 |
|---|---|---|
| 铺垫层 | 待模型分析 | dry-run 占位 |
| 释放层 | 待模型分析 | dry-run 占位 |
| 反应层 | 待模型分析 | dry-run 占位 |
| 衔接层 | 待模型分析 | dry-run 占位 |

## 8. 情绪触动点

| 触动点 | 触发事件 | 目标情绪 | 爆发点 | 余波/冷却 | 复现提示 |
|---|---|---|---|---|---|
| TR-001 | 待模型分析 | 待模型分析 | 待模型分析 | 待模型分析 | 待模型分析 |

## 9. 语言与场景技法

待模型分析。

## 10. 可复现模块卡

### EM-001 Dry-run 模块

| 字段 | 内容 |
|---|---|
| 读者想看什么 | 待模型分析 |
| 情绪链 | 缺口 → 加压 → 触发 → 爆发 → 余波 |
| 戏剧单元 | 待模型分析 |
| 关键功能位 | 待模型分析 |
| 复现步骤 | 待模型分析 |
| 可替换项 | 待模型分析 |
| 不可照搬 | 原文专名、具体桥段顺序、标志性台词、独特设定 |

## 11. 可学习规律

- 用 dry-run 验证项目流程，不输出原文。
- 长篇文本必须先切分章节，再逐章分析，避免一次性把整本书送入模型。

## 12. 不建议模仿

- 不应把 dry-run 结果当成真实拆书结论。

## 13. 可加入知识库的规则

- 长篇文本必须先切分章节，再逐章分析，避免一次性把整本书送入模型。
- 拆书输出应抽象结构、情绪链和功能位，不搬运原文素材。
"""


class DoubaoResponsesProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str, disable_thinking: bool = True):
        self.base_url = self._normalize_base_url(base_url)
        self.api_key = (api_key or "").strip()
        self.disable_thinking = disable_thinking

    async def complete(self, request: LLMRequest) -> str:
        if request.dry_run:
            return self._dry_run_response(request)
        if not self.api_key:
            raise ValueError("缺少豆包 Ark API Key。请设置 DOUBAO_API_KEY 或 ARK_API_KEY，或开启 dry-run。")
        if not request.model:
            raise ValueError("缺少豆包模型名称。请设置 DOUBAO_MODEL，或在 Agent 写作页选择模型。")

        payload: dict = {
            "model": request.model,
            "input": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "max_output_tokens": request.max_tokens,
        }
        if self.disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_error: Exception | None = None
        for attempt in range(request.retry_count + 1):
            try:
                async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                    response = await client.post(self.responses_url, json=payload, headers=headers)
                    response.raise_for_status()
                    content = self._extract_response_text(response.json())
                    if not content:
                        raise ValueError("豆包返回为空")
                    return content
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:800]
                last_error = RuntimeError(f"{exc.response.status_code} {exc.response.reason_phrase}: {detail}")
                if attempt < request.retry_count:
                    await asyncio.sleep(1.5 * (attempt + 1))
            except Exception as exc:  # noqa: BLE001 - persisted into UI/API error for diagnosis.
                last_error = exc
                if attempt < request.retry_count:
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"豆包调用失败: {last_error}") from last_error

    @property
    def responses_url(self) -> str:
        if self.base_url.endswith("/responses"):
            return self.base_url
        return f"{self.base_url}/responses"

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        cleaned = (base_url or "https://ark.cn-beijing.volces.com/api/v3").strip().rstrip("/")
        if cleaned and "://" not in cleaned:
            cleaned = f"https://{cleaned}"
        if cleaned.endswith("/responses"):
            return cleaned.removesuffix("/responses").rstrip("/")
        return cleaned

    @staticmethod
    def _extract_response_text(data: dict) -> str:
        for key in ("output_text", "text", "content"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        output = data.get("output")
        if isinstance(output, list):
            texts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, str) and content.strip():
                    texts.append(content.strip())
                elif isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        text = part.get("text") or part.get("content")
                        if isinstance(text, str) and text.strip():
                            texts.append(text.strip())
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
            if texts:
                return "\n".join(texts)

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
        return ""

    def _dry_run_response(self, request: LLMRequest) -> str:
        return f"""# Dry-run 豆包调用

未调用豆包 Ark API。真实生成会使用模型：{request.model or "未选择"}。

这条结果只用于验证 Agent 写作页的模型选择、知识检索和 Prompt 组装流程。
"""
