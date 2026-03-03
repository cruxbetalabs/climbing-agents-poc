"""
Tool registry. Each tool is:
  - A Python async function
  - A JSON schema definition for the OpenAI tools API

Register tools with @registry.register(schema=...).
"""

from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolResult:
    data: Any
    status: str = "ok"           # ok | empty | error | needs_confirmation
    message: str | None = None   # human-readable summary, surfaced on needs_confirmation
    terminal: bool = False       # if True, orchestrator surfaces immediately without further reasoning


class ToolRegistry:
    def __init__(self):
        self._functions: dict[str, Callable] = {}
        self._schemas: list[dict] = []

    def register(self, schema: dict):
        """Decorator to register a tool function with its OpenAI schema."""
        def decorator(fn: Callable) -> Callable:
            name = schema["function"]["name"]
            self._functions[name] = fn
            self._schemas.append(schema)
            return fn
        return decorator

    @property
    def schemas(self) -> list[dict]:
        return self._schemas

    async def dispatch(self, name: str, arguments: dict) -> ToolResult:
        fn = self._functions.get(name)
        if fn is None:
            return ToolResult(data=None, status="error", message=f"Unknown tool: {name}")
        try:
            result = fn(**arguments)
            if asyncio.iscoroutine(result):
                result = await result
            return result if isinstance(result, ToolResult) else ToolResult(data=result)
        except Exception as e:
            return ToolResult(data=None, status="error", message=f"Tool {name} failed: {e}")


# Global registry instance — all tool modules import and use this
registry = ToolRegistry()
