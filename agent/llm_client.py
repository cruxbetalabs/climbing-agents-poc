"""
Provider-agnostic LLM client.
Currently supports: openai (and ollama via openai-compatible endpoint).
Anthropic support stub included for future use.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict  # already parsed from JSON


@dataclass
class LLMResponse:
    content: str | None           # final text, None if tool calls present
    tool_calls: list[ToolCall]
    finish_reason: str            # "stop" | "tool_calls" | "length" | "error"
    usage: dict = field(default_factory=dict)


class LLMClient:
    def __init__(self, cfg: dict):
        self.provider = cfg["provider"]
        self.model = cfg["model"]
        self.temperature = cfg.get("temperature", 0.3)
        self.max_tokens = cfg.get("max_tokens", 2048)
        self._client = self._build_client(cfg)

    def _build_client(self, cfg: dict):
        if self.provider in ("openai", "ollama"):
            from openai import AsyncOpenAI
            api_key = os.environ.get(cfg.get("api_key_env", "OPENAI_API_KEY"))
            base_url = cfg.get("base_url") or None
            return AsyncOpenAI(api_key=api_key, base_url=base_url)
        elif self.provider == "anthropic":
            raise NotImplementedError("Anthropic support coming soon.")
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        if self.provider in ("openai", "ollama"):
            return await self._complete_openai(messages, tools)
        raise NotImplementedError

    async def _complete_openai(
        self,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> LLMResponse:
        import json
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        finish_reason = choice.finish_reason

        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                ))

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            }

        return LLMResponse(
            content=choice.message.content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )
