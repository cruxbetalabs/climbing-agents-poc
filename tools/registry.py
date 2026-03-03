"""
Tool registry. Each tool is:
  - A Python async function
  - A JSON schema definition for the OpenAI tools API

Register tools with @registry.register(schema=...).

Two-phase commit pattern for mutation tools:
  1. The tool function returns ToolResult(status="needs_confirmation") with the
     proposed change in `data` and a human-readable `message`.
  2. The orchestrator pauses, asks the user to confirm, then calls
     registry.commit(name, data) which routes to the registered commit_fn.
"""

from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolResult:
    data: Any
    status: str = "ok"  # ok | empty | error | needs_confirmation
    message: str | None = None  # human-readable summary, surfaced on needs_confirmation
    terminal: bool = (
        False  # if True, orchestrator surfaces immediately without further reasoning
    )


class ToolRegistry:
    def __init__(self):
        self._functions: dict[str, Callable] = {}
        self._schemas: list[dict] = []
        self._commit_fns: dict[str, Callable] = {}

    def register(self, schema: dict, commit_fn: Callable | None = None):
        """Decorator to register a tool function with its OpenAI schema.

        commit_fn: optional. If provided, called by registry.commit() after the
        orchestrator receives user confirmation for a needs_confirmation result.
        Signature: commit_fn(data: Any) -> ToolResult
        """

        def decorator(fn: Callable) -> Callable:
            name = schema["function"]["name"]
            self._functions[name] = fn
            self._schemas.append(schema)
            if commit_fn is not None:
                self._commit_fns[name] = commit_fn
            return fn

        return decorator

    @property
    def schemas(self) -> list[dict]:
        return self._schemas

    async def dispatch(self, name: str, arguments: dict) -> ToolResult:
        fn = self._functions.get(name)
        if fn is None:
            return ToolResult(
                data=None, status="error", message=f"Unknown tool: {name}"
            )
        try:
            result = fn(**arguments)
            if asyncio.iscoroutine(result):
                result = await result
            return result if isinstance(result, ToolResult) else ToolResult(data=result)
        except Exception as e:
            return ToolResult(
                data=None, status="error", message=f"Tool {name} failed: {e}"
            )

    async def commit(self, name: str, data: Any) -> ToolResult:
        """Execute the commit function for a needs_confirmation tool.

        Called by the orchestrator after the user confirms an action.
        """
        fn = self._commit_fns.get(name)
        if fn is None:
            return ToolResult(
                data=None,
                status="error",
                message=f"No commit handler registered for tool: {name}",
            )
        try:
            result = fn(data)
            if asyncio.iscoroutine(result):
                result = await result
            return result if isinstance(result, ToolResult) else ToolResult(data=result)
        except Exception as e:
            return ToolResult(
                data=None, status="error", message=f"Commit for {name} failed: {e}"
            )


# Global registry instance — all tool modules import and use this
registry = ToolRegistry()
